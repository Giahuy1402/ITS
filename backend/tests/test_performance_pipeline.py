import cv2
import numpy as np
import pytest
from threading import Lock
from types import SimpleNamespace
from backend.app.core.detector import VehicleDetector, make_detection
from backend.app.core.tracker import SimpleByteTracker
from backend.app.core.video_writer import AnnotatedVideoWriter


@pytest.mark.parametrize("source_fps", [15, 30, 60])
def test_60fps_writer_preserves_duration_and_motion(tmp_path, source_fps):
    path = tmp_path / "result.mp4"
    writer = AnnotatedVideoWriter(path, source_fps, 60, 160, 120)
    for i in range(source_fps):
        writer.write(np.full((120, 160, 3), i*3, np.uint8))
    writer.release()
    cap = cv2.VideoCapture(str(path))
    assert cap.get(cv2.CAP_PROP_FPS) == pytest.approx(60)
    values = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        values.append(int(frame[60, 80].mean()))
    cap.release()
    assert len(values) == 60
    assert len(set(values)) >= source_fps - 2


def test_motorcycle_uses_its_own_threshold():
    class Tensor:
        def __init__(self, data): self.data = data
        def cpu(self): return self
        def tolist(self): return self.data
    boxes = SimpleNamespace(xyxy=Tensor([[0, 0, 40, 40]]*4),
                            conf=Tensor([0.25, 0.1, 0.25, 0.6]), cls=Tensor([3, 3, 2, 2]))
    calls = []
    def model(frame, **kwargs):
        calls.append(kwargs)
        return [SimpleNamespace(boxes=boxes)]
    detector = VehicleDetector.__new__(VehicleDetector)
    detector.model, detector.lock = model, Lock()
    result = detector.detect(np.zeros((100,100,3), np.uint8), conf_threshold=0.35)
    assert [item["class_id"] for item in result] == [3, 2]
    assert result[0]["class_name"] == "Xe máy"
    assert calls[0]["conf"] == 0.2 and 3 in calls[0]["classes"]


def test_prediction_preserves_id_without_creating_measurements():
    tracker = SimpleByteTracker()
    tracker.update([make_detection([0,0,40,40], 0.9, 3)], 0, 0)
    tracker.update([make_detection([10,0,50,40], 0.9, 3)], 0.1, 1)
    prediction = tracker.predict(0.35)
    assert prediction[0]["bbox"][0] == pytest.approx(35)
    assert len(tracker.get_trajectory(1)) == 2
    observed = tracker.update([make_detection([35,0,75,40], 0.9, 3)], 0.35, 3)
    assert observed[0]["track_id"] == 1
    assert len(tracker.get_trajectory(1)) == 3


def test_skipping_inference_does_not_discard_source_frames(api, tmp_path, monkeypatch):
    from backend.app.core.detector import DemoVehicleDetector
    path = tmp_path / "source60.mp4"
    source = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 60, (320,240))
    for i in range(60):
        source.write(np.full((240,320,3), i*3, np.uint8))
    source.release()
    calls = []
    def detect(self, frame, **kwargs):
        calls.append(1)
        return []
    monkeypatch.setattr(DemoVehicleDetector, "detect", detect)
    with path.open("rb") as stream:
        video = api[0].post("/api/videos/upload", files={"file": ("source.mp4", stream)}).json()
    session = api[0].post("/api/sessions", json={"video_id": video["id"], "detection_mode": "demo", "frame_skip": 3}).json()
    result = api[0].get(f"/api/sessions/{session['id']}").json()
    assert result["status"] == "completed", result["error_message"]
    assert len(calls) == 20
    capture = cv2.VideoCapture(result["annotated_video_path"])
    assert capture.get(cv2.CAP_PROP_FPS) == pytest.approx(60)
    values = []
    while True:
        ok, frame = capture.read()
        if not ok: break
        values.append(int(frame[220,300].mean()))
    capture.release()
    assert len(values) == 60
    assert len(set(values)) >= 55


def test_native_120fps_is_not_reduced(tmp_path):
    from backend.app.schemas import SessionStartConfig
    assert SessionStartConfig(video_id=1, output_fps=120).output_fps == 120
    path = tmp_path / "high_fps.mp4"
    writer = AnnotatedVideoWriter(path, 120, 120, 160, 120)
    for i in range(120):
        writer.write(np.full((120,160,3), i, np.uint8))
    writer.release()
    cap = cv2.VideoCapture(str(path))
    assert cap.get(cv2.CAP_PROP_FPS) == pytest.approx(120)
    assert cap.get(cv2.CAP_PROP_FRAME_COUNT) == 120
    cap.release()
