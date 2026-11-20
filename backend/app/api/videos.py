import os
import cv2
import uuid
import subprocess
from threading import Lock
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Response
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from backend.app.config import UPLOADS_DIR
from backend.app.database import get_db
from backend.app.models import Video
from backend.app.schemas import VideoResponse
from backend.app.core.video_writer import find_ffmpeg, nvenc_available

router = APIRouter(prefix="/api/videos", tags=["videos"])

ALLOWED_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv"}
SAMPLE_LOCK = Lock()
PREVIEW_LOCK = Lock()
MAX_FILE_SIZE_BYTES = 500 * 1024 * 1024  # 500 MB limit

def inspect_video(path, original_name, db):
    import math
    cap = cv2.VideoCapture(str(path))
    try:
        ok, frame = cap.read()
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if not ok or frame is None or width <= 0 or height <= 0 or total_frames <= 0 or not math.isfinite(fps) or fps <= 0:
            raise HTTPException(status_code=400, detail="Video không đọc được hoặc thiếu thông tin FPS hợp lệ.")
    finally:
        cap.release()
    video = Video(filename=path.name, original_name=original_name, file_path=str(path),
                  file_size_bytes=path.stat().st_size, width=width, height=height,
                  fps=fps, total_frames=total_frames, duration_sec=round(total_frames/fps, 2))
    db.add(video)
    db.commit()
    db.refresh(video)
    return video


@router.post("/upload", response_model=VideoResponse)
def upload_video(file: UploadFile = File(...), db: Session = Depends(get_db)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Hỗ trợ video MP4, AVI, MOV, MKV.")
    path = UPLOADS_DIR / f"{uuid.uuid4().hex}{ext}"
    try:
        size = 0
        with path.open("wb") as output:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_FILE_SIZE_BYTES:
                    raise HTTPException(status_code=413, detail="Dung lượng file vượt quá giới hạn 500 MB.")
                output.write(chunk)
        return inspect_video(path, file.filename, db)
    except Exception:
        db.rollback()
        path.unlink(missing_ok=True)
        raise
    finally:
        file.file.close()


@router.post("/sample", response_model=VideoResponse)
def create_sample_video(db: Session = Depends(get_db)):
    from sample_generator import generate_sample_traffic_video
    # Serialize sample creation for simultaneous button clicks.
    with SAMPLE_LOCK:
        path = UPLOADS_DIR / "sample_traffic.mp4"
        existing = db.query(Video).filter(Video.file_path == str(path)).first()
        regenerate = not path.exists()
        if not regenerate:
            cap = cv2.VideoCapture(str(path))
            codec = int(cap.get(cv2.CAP_PROP_FOURCC))
            cap.release()
            fourcc = "".join(chr((codec >> (8 * index)) & 255) for index in range(4)).lower()
            regenerate = fourcc not in {"h264", "avc1"}
        if regenerate:
            generate_sample_traffic_video(str(path))
        if existing:
            if regenerate:
                existing.file_size_bytes = path.stat().st_size
                db.commit()
                db.refresh(existing)
            return existing
        return inspect_video(path, "sample_traffic.mp4", db)


@router.get("", response_model=list[VideoResponse])
def list_videos(db: Session = Depends(get_db)):
    return db.query(Video).order_by(Video.created_at.desc()).all()


@router.get("/{video_id}", response_model=VideoResponse)
def get_video(video_id: int, db: Session = Depends(get_db)):
    v = db.query(Video).filter(Video.id == video_id).first()
    if not v:
        raise HTTPException(status_code=404, detail="Không tìm thấy video.")
    return v


@router.get("/{video_id}/preview")
def get_browser_preview(video_id: int, db: Session = Depends(get_db)):
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Không tìm thấy video.")
    source = Path(video.file_path)
    if not source.is_file():
        raise HTTPException(status_code=404, detail="Không tìm thấy tệp video.")
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise HTTPException(status_code=503, detail="Thiếu FFmpeg để tạo video phát trên trình duyệt.")
    preview = UPLOADS_DIR / f"{source.stem}_preview.mp4"
    with PREVIEW_LOCK:
        if not preview.exists() or preview.stat().st_mtime_ns < source.stat().st_mtime_ns:
            cap = cv2.VideoCapture(str(source))
            codec_code = int(cap.get(cv2.CAP_PROP_FOURCC))
            cap.release()
            codec = "".join(chr((codec_code >> (8 * index)) & 255) for index in range(4)).lower()
            encoder = (["-c:v", "copy"] if codec in {"h264", "avc1"} else
                       ["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-c:v", "h264_nvenc", "-preset", "p4", "-cq", "23"]
                       if nvenc_available() else
                       ["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-threads", "2"])
            temporary = preview.with_suffix(".tmp.mp4")
            try:
                command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(source),
                           "-map", "0:v:0", "-an", *encoder, "-pix_fmt", "yuv420p",
                           "-movflags", "+faststart", str(temporary)]
                result = subprocess.run(command, capture_output=True, timeout=3600,
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if result.returncode or not temporary.is_file() or temporary.stat().st_size == 0:
                    raise RuntimeError(result.stderr.decode(errors="replace")[-500:])
                os.replace(temporary, preview)
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
                temporary.unlink(missing_ok=True)
                raise HTTPException(status_code=500, detail=f"Không thể tạo video phát trên trình duyệt: {error}") from error
    return FileResponse(preview, media_type="video/mp4")


@router.get("/{video_id}/frame")
def get_video_frame(video_id: int, frame_idx: int = 1, db: Session = Depends(get_db)):
    """
    Extracts a single frame from the video as JPEG image for interactive canvas setup.
    """
    v = db.query(Video).filter(Video.id == video_id).first()
    if not v:
        raise HTTPException(status_code=404, detail="Không tìm thấy video.")

    cap = cv2.VideoCapture(v.file_path)
    if not cap.isOpened():
        raise HTTPException(status_code=500, detail="Không thể mở file video.")

    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, frame_idx - 1))
    ret, frame = cap.read()
    cap.release()

    if not ret or frame is None:
        raise HTTPException(status_code=400, detail="Không thể đọc frame được yêu cầu.")

    is_success, buffer = cv2.imencode(".jpg", frame)
    if not is_success:
        raise HTTPException(status_code=500, detail="Không thể mã hóa khung hình thành ảnh.")

    return Response(content=buffer.tobytes(), media_type="image/jpeg")


@router.get("/{video_id}/auto-setup")
def auto_setup_video(video_id: int, db: Session = Depends(get_db)):
    from backend.app.core.auto_setup import suggest_setup
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Không tìm thấy video.")
    try:
        return suggest_setup(video.file_path)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
