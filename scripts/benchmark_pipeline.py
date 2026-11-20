"""Benchmark a 300-frame real-video excerpt without changing the working database."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import cv2
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.config import DATABASE_PATH, OUTPUTS_DIR
from backend.app.database import Base
from backend.app.models import Video, AnalysisSession
from backend.app.schemas import SessionStartConfig
from backend.app.core.auto_setup import suggest_setup
from backend.app.core import video_processor as worker

with sqlite3.connect(f"file:{DATABASE_PATH.as_posix()}?mode=ro", uri=True) as db:
    source = db.execute("select id,file_path,fps,width,height from videos order by id desc limit 1").fetchone()
with tempfile.TemporaryDirectory(prefix="its-perf-") as folder:
    directory = Path(folder)
    clip = directory / "clip.mp4"
    cap = cv2.VideoCapture(source[1])
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(5*source[2]))
    out = cv2.VideoWriter(str(clip), cv2.VideoWriter_fourcc(*"mp4v"), source[2], (source[3], source[4]))
    frames = 0
    first = None
    while frames < 300:
        ok, frame = cap.read()
        if not ok: break
        if first is None: first = frame.copy()
        out.write(frame)
        frames += 1
    out.release()
    cap.release()
    setup = suggest_setup(clip)
    engine = create_engine(f"sqlite:///{directory/'test.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    worker.SessionLocal, worker.OUTPUTS_DIR = factory, directory
    with factory() as db:
        video = Video(filename=clip.name, original_name=clip.name, file_path=str(clip), file_size_bytes=clip.stat().st_size,
            width=source[3], height=source[4], fps=source[2], total_frames=frames, duration_sec=frames/source[2])
        db.add(video)
        db.flush()
        config = SessionStartConfig(video_id=video.id, roi_polygon=setup["roi_polygon"],
            counting_line={"enabled":True, "line":setup["count_line"]}, output_fps=60)
        session = AnalysisSession(video_id=video.id, status="pending", config_json=config.model_dump_json())
        db.add(session)
        db.commit()
        sid = session.id
    detector = worker.get_detector()
    for _ in range(3): detector.detect(first)
    # Save one annotated frame to inspect actual motorcycle predictions.
    example = first.copy()
    for detection in detector.detect(first):
        x1,y1,x2,y2 = map(int,detection["bbox"])
        label = "motorcycle" if detection["class_id"] == 3 else str(detection["class_id"])
        color = (255,200,0) if detection["class_id"] == 3 else (0,255,0)
        cv2.rectangle(example,(x1,y1),(x2,y2),color,2)
        cv2.putText(example, f"{label} {detection['conf']:.2f}", (x1,max(12,y1-4)),cv2.FONT_HERSHEY_SIMPLEX,0.4,color,1)
    cv2.imwrite(str(OUTPUTS_DIR / "verification_motorcycles.jpg"), example)
    started = time.perf_counter()
    worker.process_video_session(sid, lambda data: None)
    elapsed = time.perf_counter()-started
    with factory() as db:
        session = db.get(AnalysisSession, sid)
        assert session.status == "completed", session.error_message
        result = cv2.VideoCapture(session.annotated_video_path)
        report = {"device":detector.device, "model":Path(detector.model_name).name, "inference_size":detector.inference_size,
                  "nvenc": __import__("backend.app.core.video_writer", fromlist=["nvenc_available"]).nvenc_available(), "source_video_id":source[0],
                  "source_fps":source[2], "source_frames":frames, "elapsed_seconds":round(elapsed,2),
                  "full_pipeline_source_fps":round(frames/elapsed,1),
                  "output_fps":result.get(cv2.CAP_PROP_FPS), "output_frames":int(result.get(cv2.CAP_PROP_FRAME_COUNT)),
                  "counted_vehicles":session.total_vehicles_counted, "counted_motorcycles":session.motorcycle_count}
        result.release()
    engine.dispose()
    OUTPUTS_DIR.mkdir(exist_ok=True)
    (OUTPUTS_DIR / "performance_report.json").write_text(json.dumps(report, indent=2),encoding="utf-8")
    print(json.dumps(report))
