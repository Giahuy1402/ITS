import pytest
import numpy as np
from backend.app.core.speed_estimator import SpeedEstimator

def test_speed_calculation_10m_0_8s():
    """
    Test requirement:
    Two landmarks 10m apart, movement time 0.8 seconds -> speed MUST be 45.0 km/h.
    Formula: 3.6 * 10 / 0.8 = 45.0 km/h
    """
    line_a_p1 = (0, 100)
    line_a_p2 = (500, 100)
    line_b_p1 = (0, 200)
    line_b_p2 = (500, 200)

    estimator = SpeedEstimator(line_a_p1, line_a_p2, line_b_p1, line_b_p2, distance_meters=10.0)

    track_id = 1
    trajectory = [
        (250, 50, 0.0, 0),
        (250, 90, 0.1, 3),
        (250, 110, 0.2, 6),
        (250, 150, 0.55, 165),
        (250, 190, 0.9, 27),
        (250, 210, 1.0, 30)
    ]

    for i in range(2, len(trajectory) + 1):
        rec = estimator.process_track(track_id, trajectory[:i])

    assert rec is not None
    assert rec["is_valid"] is True
    assert rec["speed_kmh"] == 45.0
    assert rec["direction"] == "A -> B"

def test_uncalibrated_speed_handling():
    """
    Test requirement:
    If speed calibration is disabled or missing line crossings, speed MUST be None (Chưa đủ dữ liệu).
    """
    line_a_p1 = (0, 100)
    line_a_p2 = (500, 100)
    line_b_p1 = (0, 200)
    line_b_p2 = (500, 200)

    estimator = SpeedEstimator(line_a_p1, line_a_p2, line_b_p1, line_b_p2, distance_meters=10.0)
    track_id = 2

    trajectory = [
        (250, 50, 0.0, 0),
        (250, 110, 0.2, 6)
    ]

    rec = estimator.process_track(track_id, trajectory)
    assert rec["is_valid"] is False
    assert rec["speed_kmh"] is None
    assert rec["reason"] == "Chưa đủ dữ liệu"

def test_processing_speed_independence():
    """
    Test requirement:
    Changing backend processing speed (or frame skip/delay) MUST NOT alter vehicle speed calculation.
    Timestamp comes from video frame index / FPS, not system clock.
    """
    estimator = SpeedEstimator((0, 100), (500, 100), (0, 200), (500, 200), distance_meters=10.0)
    track_id = 3

    fps = 30.0
    frame_start = 10
    frame_end = 34

    t_start = frame_start / fps
    t_end = frame_end / fps

    trajectory = [
        (250, 90, t_start - 0.033, frame_start - 1),
        (250, 105, t_start + 0.033, frame_start + 1),  # t_a ~ 0.333s
        (250, 195, t_end - 0.033, frame_end - 1),
        (250, 205, t_end + 0.033, frame_end + 1)      # t_b ~ 1.133s
    ]

    rec = None
    for i in range(2, len(trajectory) + 1):
        rec = estimator.process_track(track_id, trajectory[:i])

    assert rec["is_valid"] is True
    assert abs(rec["speed_kmh"] - 45.0) < 1.0


def test_auto_speed_estimation_horizontal():
    """
    Auto mode estimates speed from standard vehicle dimensions when moving horizontally.
    Car length ~ 4.4m; bbox width = 88px -> 0.05 m/px.
    Moving 100px in 0.5s = 5.0m in 0.5s = 36.0 km/h.
    """
    estimator = SpeedEstimator(mode="auto")
    track_id = 10
    trajectory = [
        (100, 200, 0.0, 0),
        (150, 200, 0.25, 7),
        (200, 200, 0.5, 15),
    ]
    bbox = [156, 180, 244, 220]  # w=88, h=40
    rec = None
    for i in range(1, len(trajectory) + 1):
        rec = estimator.process_track(track_id, trajectory[:i], bbox=bbox, class_name="Ô tô")

    assert rec is not None
    assert rec["is_valid"] is True
    assert abs(rec["speed_kmh"] - 36.0) < 1.0
    assert rec["direction"] == "Trái -> Phải"


def test_auto_speed_estimation_vertical_perspective():
    """
    Auto mode compensates perspective foreshortening when vehicles move vertically.
    """
    estimator = SpeedEstimator(mode="auto")
    track_id = 11
    trajectory = [
        (300, 100, 0.0, 0),
        (300, 150, 0.25, 7),
        (300, 200, 0.5, 15),
    ]
    bbox = [255, 90, 345, 200]  # w=90, h=110
    rec = None
    for i in range(1, len(trajectory) + 1):
        rec = estimator.process_track(track_id, trajectory[:i], bbox=bbox, class_name="Ô tô")

    assert rec is not None
    assert rec["is_valid"] is True
    assert 10.0 <= rec["speed_kmh"] <= 80.0
    assert rec["direction"] == "Đi xuống"


def test_auto_speed_estimation_stationary():
    estimator = SpeedEstimator(mode="auto")
    track_id = 12
    trajectory = [
        (200, 200, 0.0, 0),
        (201, 200, 0.25, 7),
        (201, 201, 0.5, 15),
    ]
    bbox = [160, 160, 240, 220]
    rec = None
    for i in range(1, len(trajectory) + 1):
        rec = estimator.process_track(track_id, trajectory[:i], bbox=bbox, class_name="Ô tô")

    assert rec is not None
    assert rec["is_valid"] is True
    assert rec["speed_kmh"] == 0.0
    assert rec["direction"] == "Đứng yên"
