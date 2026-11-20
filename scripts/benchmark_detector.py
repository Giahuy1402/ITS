"""Measure real inference on sampled frames of the newest uploaded video."""
import json
from pathlib import Path
import sqlite3
import sys
import time
import cv2
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.config import DATABASE_PATH
from backend.app.core.detector import VehicleDetector

with sqlite3.connect(f"file:{DATABASE_PATH.as_posix()}?mode=ro", uri=True) as db:
    row = db.execute("select id,file_path,fps,total_frames from videos order by id desc limit 1").fetchone()
cap = cv2.VideoCapture(row[1])
frames = []
for seconds in (5, 15, 30, 60):
    cap.set(cv2.CAP_PROP_POS_FRAMES, min(int(seconds*row[2]), row[3]-1))
    ok, frame = cap.read()
    if ok: frames.append(frame)
cap.release()
detector = VehicleDetector()
for _ in range(3): detector.detect(frames[0])
started = time.perf_counter()
counts = []
for _ in range(3):
    for frame in frames:
        detections = detector.detect(frame)
        counts.append(sum(item["class_id"] == 3 for item in detections))
elapsed = time.perf_counter() - started
print(json.dumps({"device":detector.device, "video_id": row[0], "source_fps": row[2],
                  "inference_fps": round(len(counts)/elapsed, 1), "frames_tested":len(counts),
                  "motorcycle_detections_per_sample":counts[:len(frames)]}))
