import cv2
import numpy as np
import pytest
from backend.app.core.auto_setup import suggest_setup
from backend.app.schemas import SessionStartConfig


def make_video(path, axis=None, frames=30):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (320, 240))
    assert writer.isOpened()
    for i in range(frames):
        frame = np.full((240, 320, 3), 50, np.uint8)
        if axis:
            x, y = (20 + i*7, 100) if axis == "horizontal" else (140, 10 + i*5)
            cv2.rectangle(frame, (x, y), (x+30, y+35), (50, 200, 220), -1)
        writer.write(frame)
    writer.release()
    return path


@pytest.mark.parametrize("axis", ["horizontal", "vertical"])
def test_motion_places_cross_line_perpendicular(tmp_path, axis):
    setup = suggest_setup(make_video(tmp_path / "motion.mp4", axis))
    assert setup["method"] == "motion"
    assert setup["motion_axis"] == axis
    line = setup["count_line"]
    if axis == "horizontal":
        assert line["p1"]["x"] == line["p2"]["x"]
        assert line["p1"]["y"] < line["p2"]["y"]
    else:
        assert line["p1"]["y"] == line["p2"]["y"]
        assert line["p1"]["x"] < line["p2"]["x"]
    assert setup["distance_meters"] is None and setup["speed_enabled"] is False
    SessionStartConfig(video_id=1, roi_polygon=setup["roi_polygon"],
                       counting_line={"enabled": True, "line": line},
                       speed_calibration={"enabled": False, "line_a": setup["line_a"], "line_b": setup["line_b"]})


@pytest.mark.parametrize("frames", [1, 30])
def test_stationary_or_short_video_uses_valid_default(tmp_path, frames):
    result = suggest_setup(make_video(tmp_path / "still.mp4", frames=frames))
    assert result["method"] == "default"
    assert len(result["roi_polygon"]) == 4
    assert result["count_line"]["p1"] != result["count_line"]["p2"]
    assert result["distance_meters"] is None


def test_uploaded_video_auto_setup_and_analysis(api, tmp_path):
    client = api[0]
    path = make_video(tmp_path / "input.mp4", "vertical")
    with path.open("rb") as source:
        video = client.post("/api/videos/upload", files={"file": ("road.mp4", source, "video/mp4")}).json()
    response = client.get(f"/api/videos/{video['id']}/auto-setup")
    assert response.status_code == 200
    setup = response.json()
    started = client.post("/api/sessions", json={"video_id": video["id"], "detection_mode": "demo",
        "roi_polygon": setup["roi_polygon"], "counting_line": {"enabled": True, "line": setup["count_line"]},
        "speed_calibration": {"enabled": False}, "save_annotated_video": False})
    assert started.status_code == 200
    detail = client.get(f"/api/sessions/{started.json()['id']}").json()
    assert detail["status"] == "completed"
    assert detail["avg_speed_kmh"] is None
    assert detail["total_vehicles_counted"] == 1
    assert client.get("/api/videos/99999/auto-setup").status_code == 404
