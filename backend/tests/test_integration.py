import asyncio
import json
from pathlib import Path
import cv2
import numpy as np
import pytest
from backend.app.api import sessions, videos
from backend.app.core import video_processor
from backend.app.core.congestion import CongestionAnalyzer
from backend.app.core.detector import DemoVehicleDetector
from backend.app.models import AnalysisSession
from sample_generator import generate_sample_traffic_video


def line(y):
    return {"p1": {"x": 0.25, "y": y}, "p2": {"x": 0.75, "y": y}}


def upload_sample(client, tmp_path, duration=3):
    path = tmp_path / "input.mp4"
    generate_sample_traffic_video(str(path), duration_sec=duration)
    with path.open("rb") as source:
        response = client.post("/api/videos/upload", files={"file": ("demo.mp4", source, "video/mp4")})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("field,value", [
    ("frame_skip", 0), ("frame_skip", 11), ("confidence_threshold", 2),
    ("target_classes", []), ("target_classes", [0]), ("video_id", -1),
    ("counting_line", {"enabled": True}),
    ("speed_calibration", {"enabled": True}),
    ("speed_calibration", {"distance_meters": 0}),
    ("roi_polygon", [{"x": 0.1, "y": 0.1}]),
    ("roi_polygon", [{"x": -1, "y": 0}]),
    ("congestion_thresholds", {"min_duration_seconds": -1}),
])
def test_invalid_config_rejected(api, field, value):
    response = api[0].post("/api/sessions", json={"video_id": 1, field: value})
    assert response.status_code == 422


def test_upload_rejects_corruption_and_cleans_file(api):
    client, _, uploads, _ = api
    assert client.post("/api/videos/upload", files={"file": ("bad.mp4", b"broken", "video/mp4")}).status_code == 400
    assert list(uploads.iterdir()) == []
    assert client.post("/api/videos/upload", files={"file": ("bad.exe", b"bad")}).status_code == 400


def test_upload_size_limit_cleans_file(api, monkeypatch):
    monkeypatch.setattr(videos, "MAX_FILE_SIZE_BYTES", 10)
    assert api[0].post("/api/videos/upload", files={"file": ("big.mp4", b"x" * 11)}).status_code == 413
    assert list(api[2].iterdir()) == []


def test_uploaded_mp4v_has_browser_playable_preview(api, tmp_path):
    from backend.app.core.video_writer import find_ffmpeg
    if not find_ffmpeg():
        pytest.skip("FFmpeg is needed for browser preview")
    source_path = tmp_path / "legacy.mp4"
    writer = cv2.VideoWriter(str(source_path), cv2.VideoWriter_fourcc(*"mp4v"), 15, (160, 120))
    assert writer.isOpened()
    for index in range(15):
        writer.write(np.full((120, 160, 3), 40 + index, np.uint8))
    writer.release()
    with source_path.open("rb") as source:
        video = api[0].post("/api/videos/upload", files={"file": ("legacy.mp4", source)}).json()
    response = api[0].get(f"/api/videos/{video['id']}/preview")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("video/mp4")
    assert b"ftyp" in response.content[:32]
    preview_path = api[2] / f"{Path(video['filename']).stem}_preview.mp4"
    cap = cv2.VideoCapture(str(preview_path))
    assert cap.isOpened()
    codec_code = int(cap.get(cv2.CAP_PROP_FOURCC))
    codec = "".join(chr((codec_code >> (8 * i)) & 255) for i in range(4)).lower()
    assert codec in {"h264", "avc1"}
    assert int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) == 15
    cap.release()


def test_h264_mkv_preview_remuxes_without_reencoding(api, tmp_path):
    import subprocess
    from backend.app.core.video_writer import AnnotatedVideoWriter, find_ffmpeg
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        pytest.skip("FFmpeg is needed for browser preview")
    h264_path = tmp_path / "source.mp4"
    writer = AnnotatedVideoWriter(h264_path, 15, 15, 160, 120)
    for index in range(15):
        writer.write(np.full((120, 160, 3), 40 + index, np.uint8))
    writer.release()
    mkv_path = tmp_path / "source.mkv"
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(h264_path),
                    "-c", "copy", str(mkv_path)], check=True, capture_output=True)
    with mkv_path.open("rb") as source:
        video = api[0].post("/api/videos/upload", files={"file": ("source.mkv", source)}).json()
    response = api[0].get(f"/api/videos/{video['id']}/preview")
    assert response.status_code == 200, response.text
    assert b"ftyp" in response.content[:32]
    preview_path = api[2] / f"{Path(video['filename']).stem}_preview.mp4"
    cap = cv2.VideoCapture(str(preview_path))
    assert cap.isOpened()
    assert int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) == 15
    cap.release()


@pytest.mark.parametrize("frame_skip", [1, 2])
def test_video_pipeline_and_exports(api, tmp_path, frame_skip):
    client, _, _, _ = api
    video = upload_sample(client, tmp_path)
    preview = client.get(f"/api/videos/{video['id']}/frame")
    assert preview.status_code == 200 and preview.content.startswith(b"\xff\xd8")
    config = {"video_id": video["id"], "detection_mode": "demo", "frame_skip": frame_skip,
              "counting_line": {"enabled": True, "line": line(0.5)},
              "speed_calibration": {"enabled": True, "line_a": line(0.3), "line_b": line(0.65), "distance_meters": 10},
              "save_annotated_video": True}
    response = client.post("/api/sessions", json=config)
    assert response.status_code == 200, response.text
    sid = response.json()["id"]
    detail = client.get(f"/api/sessions/{sid}").json()
    assert detail["status"] == "completed", detail.get("error_message")
    assert detail["progress_pct"] == 100
    assert detail["processed_frames"] == video["total_frames"]
    assert detail["total_vehicles_counted"] == 2
    assert sum(detail[k] for k in ("car_count", "motorcycle_count", "bus_count", "truck_count")) == detail["total_vehicles_counted"]
    assert detail["avg_speed_kmh"] is not None
    assert detail["recent_records"] and detail["congestion_timeline"]
    first_log_frame = detail["congestion_timeline"][0]["frame_idx"]
    later_logs = client.get(f"/api/sessions/{sid}?since_frame={first_log_frame}").json()["congestion_timeline"]
    assert len(later_logs) == len(detail["congestion_timeline"]) - 1
    assert all(log["frame_idx"] > first_log_frame for log in later_logs)
    assert client.get(f"/api/reports/sessions/{sid}/csv").content.startswith(b"\xef\xbb\xbf")
    download = client.get(f"/api/reports/sessions/{sid}/video")
    assert download.status_code == 200 and len(download.content) > 1000
    cap = cv2.VideoCapture(detail["annotated_video_path"])
    assert cap.isOpened()
    assert cap.get(cv2.CAP_PROP_FPS) == pytest.approx(60)
    assert cap.get(cv2.CAP_PROP_FRAME_COUNT) / cap.get(cv2.CAP_PROP_FPS) == pytest.approx(video["duration_sec"], abs=0.1)
    cap.release()
    if video_processor.find_ffmpeg():
        assert "browser.mp4" in detail["annotated_video_path"]


def test_sample_endpoint_idempotent(api):
    client = api[0]
    first = client.post("/api/videos/sample")
    second = client.post("/api/videos/sample")
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert client.get(f"/api/videos/{first.json()['id']}/frame").status_code == 200


def test_cancel_pending_worker_never_starts(api, tmp_path):
    client, factory, _, outputs = api
    video = upload_sample(client, tmp_path, duration=1)
    with factory() as db:
        session = AnalysisSession(video_id=video["id"], status="pending", config_json=json.dumps({"video_id": video["id"]}))
        db.add(session)
        db.commit()
        sid = session.id
    assert client.post(f"/api/sessions/{sid}/cancel").status_code == 200
    video_processor.process_video_session(sid)
    assert client.get(f"/api/sessions/{sid}").json()["status"] == "cancelled"
    assert list(outputs.iterdir()) == []
    assert sid not in video_processor.CANCEL_REQUESTS


def test_missing_video_fails_with_timestamp(api, tmp_path):
    client, factory, _, _ = api
    video = upload_sample(client, tmp_path, duration=1)
    (api[2] / video["filename"]).unlink()
    response = client.post("/api/sessions", json={"video_id": video["id"], "detection_mode": "demo"})
    detail = client.get(f"/api/sessions/{response.json()['id']}").json()
    assert detail["status"] == "failed" and detail["completed_at"]


def test_congestion_requires_continuous_video_duration():
    analyzer = CongestionAnalyzer({"max_occupancy_heavy": 1, "min_duration_seconds": 3})
    vehicles = [{"track_id": 1}]
    for t in (0, 0.01, 1, 2.99):
        assert analyzer.evaluate(vehicles, timestamp_sec=t)["status"] == "Chưa đủ dữ liệu"
    assert analyzer.evaluate(vehicles, timestamp_sec=3)["status"] == "Đông xe"
    assert analyzer.evaluate([], timestamp_sec=4)["status"] == "Đông xe"
    analyzer.evaluate(vehicles, timestamp_sec=5)
    assert analyzer.evaluate([], timestamp_sec=6)["status"] == "Đông xe"
    assert analyzer.evaluate([], timestamp_sec=9)["status"] == "Thông thoáng"


def test_worker_broadcast_uses_asgi_loop(monkeypatch):
    messages = []
    async def broadcast(sid, message):
        messages.append((sid, message))
    def worker(sid, callback):
        callback({"session_id": sid, "progress_pct": 50})
    monkeypatch.setattr(sessions, "process_video_session", worker)
    monkeypatch.setattr(sessions.manager, "broadcast", broadcast)
    async def run():
        await sessions.run_worker(42)
        await asyncio.sleep(0.01)
    asyncio.run(run())
    assert messages == [(42, {"session_id": 42, "progress_pct": 50})]


def test_websocket_replays_recent_tracks_after_fast_worker():
    sent = []
    class Socket:
        async def accept(self): pass
        async def send_json(self, message): sent.append(message)
    async def run():
        manager = sessions.ConnectionManager()
        for frame_idx in range(1, 6):
            await manager.broadcast(12, {"kind": "tracks", "frame_idx": frame_idx, "tracks": []})
        socket = Socket()
        await manager.connect(12, socket)
        await manager.broadcast(12, {"kind": "tracks", "frame_idx": 6, "tracks": []})
        manager.disconnect(12, socket)
    asyncio.run(run())
    assert [item["frame_idx"] for item in sent] == list(range(1, 7))


def test_demo_empty_road_has_no_vehicles():
    frame = np.full((720, 1280, 3), 60, np.uint8)
    frame[:, :300] = (40, 100, 40)
    frame[:, 980:] = (40, 100, 40)
    cv2.line(frame, (640, 0), (640, 720), (0, 220, 255), 3)
    assert DemoVehicleDetector().detect(frame) == []


def test_yolo_empty_result_never_falls_back_to_demo():
    from threading import Lock
    from types import SimpleNamespace
    from backend.app.core.detector import VehicleDetector
    detector = VehicleDetector.__new__(VehicleDetector)
    detector.lock = Lock()
    detector.model = lambda *args, **kwargs: [SimpleNamespace(boxes=None)]
    frame = np.full((720, 1280, 3), 60, np.uint8)
    cv2.rectangle(frame, (450, 200), (510, 300), (50, 200, 50), -1)
    assert DemoVehicleDetector().detect(frame)
    assert detector.detect(frame) == []


def test_cancel_during_processing_removes_partial_video(api, tmp_path, monkeypatch):
    client, factory, _, outputs = api
    video = upload_sample(client, tmp_path, duration=1)
    with factory() as db:
        session = AnalysisSession(video_id=video["id"], status="pending", config_json=json.dumps({"video_id": video["id"], "detection_mode": "demo"}))
        db.add(session)
        db.commit()
        sid = session.id
    def cancel_on_detect(self, *args, **kwargs):
        video_processor.CANCEL_REQUESTS[sid] = True
        return []
    monkeypatch.setattr(DemoVehicleDetector, "detect", cancel_on_detect)
    video_processor.process_video_session(sid)
    detail = client.get(f"/api/sessions/{sid}").json()
    assert detail["status"] == "cancelled" and detail["completed_at"]
    assert detail["annotated_video_path"] is None
    assert list(outputs.iterdir()) == []
    assert sid not in video_processor.CANCEL_REQUESTS


def test_detector_failure_releases_partial_video(api, tmp_path, monkeypatch):
    client = api[0]
    video = upload_sample(client, tmp_path, duration=1)
    def fail(self, *args, **kwargs):
        raise RuntimeError("test inference failure")
    monkeypatch.setattr(DemoVehicleDetector, "detect", fail)
    response = client.post("/api/sessions", json={"video_id": video["id"], "detection_mode": "demo"})
    detail = client.get(f"/api/sessions/{response.json()['id']}").json()
    assert detail["status"] == "failed"
    assert detail["error_message"] == "test inference failure"
    assert list(api[3].iterdir()) == []


def test_rerun_preserves_config_and_old_result(api, tmp_path):
    client = api[0]
    video = upload_sample(client, tmp_path, duration=1)
    first = client.post("/api/sessions", json={"video_id": video["id"], "detection_mode": "demo", "save_annotated_video": False}).json()
    original = client.get(f"/api/sessions/{first['id']}").json()
    rerun = client.post(f"/api/sessions/{first['id']}/rerun")
    assert rerun.status_code == 200
    latest = client.get(f"/api/sessions/{rerun.json()['id']}").json()
    assert latest["id"] != original["id"]
    assert latest["config"] == original["config"]
    assert latest["status"] == original["status"] == "completed"
    assert latest["annotated_video_path"] is None
    assert client.get(f"/api/sessions/{first['id']}").json() == original


def test_auto_speed_mode_pipeline(api, tmp_path):
    client = api[0]
    video = upload_sample(client, tmp_path, duration=3)
    config = {
        "video_id": video["id"],
        "detection_mode": "demo",
        "counting_line": {"enabled": True, "line": line(0.5)},
        "speed_calibration": {"enabled": True, "mode": "auto"},
        "save_annotated_video": False,
    }
    response = client.post("/api/sessions", json=config)
    assert response.status_code == 200, response.text
    detail = client.get(f"/api/sessions/{response.json()['id']}").json()
    assert detail["status"] == "completed", detail.get("error_message")
    assert detail["avg_speed_kmh"] is not None
    assert detail["avg_speed_kmh"] > 0
    assert any(r["is_valid_speed"] and r["speed_kmh"] is not None for r in detail["recent_records"])
