"""Encode annotated frames directly to H.264, independently of inference cadence."""
import shutil
import subprocess
import tempfile
import cv2
from functools import lru_cache
import os


@lru_cache(maxsize=1)
def find_ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        return shutil.which("ffmpeg")


@lru_cache(maxsize=1)
def nvenc_available():
    binary = find_ffmpeg()
    if not binary or os.environ.get("ITS_ENCODER") == "cpu":
        return False
    try:
        check = subprocess.run([binary, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
            "-i", "color=c=black:s=320x240:r=60", "-frames:v", "2", "-c:v", "h264_nvenc",
            "-preset", "p4", "-f", "null", "-"], capture_output=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return check.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


class AnnotatedVideoWriter:
    def __init__(self, path, source_fps, output_fps, width, height, max_dimension=1280):
        scale = min(1.0, max_dimension / max(width, height))
        self.size = (max(2, int(width*scale)//2*2), max(2, int(height*scale)//2*2))
        self.source_fps, self.output_fps = source_fps, output_fps
        self.frames_in = self.frames_out = 0
        self.closed = False
        self.process = self.fallback = self.log = None
        ffmpeg = find_ffmpeg()
        self.encoder = "h264_nvenc" if min(self.size) >= 144 and max(self.size) >= 256 and nvenc_available() else "libx264"
        if ffmpeg:
            self.log = tempfile.TemporaryFile()
            codec_args = (["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "23", "-b:v", "0"]
                          if self.encoder == "h264_nvenc" else
                          ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-threads", "2"])
            args = [ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
                    "-s", f"{self.size[0]}x{self.size[1]}", "-framerate", str(source_fps),
                    "-i", "pipe:0", "-an", "-vf", f"fps={output_fps}", *codec_args,
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path)]
            try:
                self.process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                    stderr=self.log, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except Exception:
                self.log.close()
                raise
        else:
            self.fallback = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), output_fps, self.size)
            if not self.fallback.isOpened():
                self.fallback.release()
                raise RuntimeError("Không thể tạo video kết quả.")

    def write(self, frame):
        if (frame.shape[1], frame.shape[0]) != self.size:
            frame = cv2.resize(frame, self.size, interpolation=cv2.INTER_AREA)
        self.frames_in += 1
        if self.process:
            self.process.stdin.write(frame.tobytes())
        else:
            target = round(self.frames_in * self.output_fps / self.source_fps)
            while self.frames_out < target:
                self.fallback.write(frame)
                self.frames_out += 1

    def release(self):
        if self.closed:
            return
        self.closed = True
        if self.fallback:
            self.fallback.release()
        if self.process:
            try:
                try:
                    self.process.stdin.close()
                except BrokenPipeError:
                    pass
                code = self.process.wait(timeout=120)
                if code:
                    self.log.seek(0)
                    raise RuntimeError("Lỗi xuất H.264: " + self.log.read().decode(errors="replace")[-500:])
            finally:
                if self.process.poll() is None:
                    self.process.kill()
                    self.process.wait(timeout=10)
                self.log.close()

    def abort(self):
        """Stop a cancelled export without waiting for FFmpeg to finalize it."""
        if self.closed:
            return
        self.closed = True
        if self.process:
            if self.process.poll() is None:
                self.process.kill()
            try:
                self.process.stdin.close()
            except (BrokenPipeError, OSError):
                pass
            self.process.wait(timeout=10)
            self.log.close()
        elif self.fallback:
            self.fallback.release()
