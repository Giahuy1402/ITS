import pytest
from backend.app.core.congestion import CongestionAnalyzer
from backend.app.core.speed_estimator import SpeedEstimator

def test_high_volume_fast_speed_not_congested():
    """
    Test requirement:
    Many vehicles moving FAST in ROI must NOT be declared as congested!
    """
    analyzer = CongestionAnalyzer({
        "max_occupancy_heavy": 5,
        "slow_speed_threshold_kmh": 20.0,
        "slow_vehicle_ratio_threshold": 0.5,
        "min_duration_seconds": 1.0,
        "min_valid_speed_samples": 1
    })

    estimator = SpeedEstimator((0, 100), (500, 100), (0, 200), (500, 200), distance_meters=10.0)
    
    # 6 vehicles in ROI, all moving at 50 km/h (fast)
    roi_vehicles = []
    for tid in range(1, 7):
        roi_vehicles.append({"track_id": tid, "bbox": [0, 0, 50, 50]})
        estimator.records[tid] = {
            "t_a": 0.0,
            "t_b": 0.72,  # delta_t = 0.72s -> speed = 3.6 * 10 / 0.72 = 50 km/h
            "speed_kmh": 50.0,
            "is_valid": True,
            "direction": "A -> B",
            "reason": "Hợp lệ"
        }

    # Evaluate multiple times to pass window
    res = None
    for t in range(10):
        res = analyzer.evaluate(roi_vehicles, speed_estimator=estimator, speed_calibration_enabled=True, timestamp_sec=t*0.2)

    assert res["status"] != "Ùn tắc"
    assert res["status"] in ["Thông thoáng", "Đông xe"]

def test_congestion_triggered_when_slow_and_heavy():
    """
    Test requirement:
    High vehicle count + low average speed + high slow vehicle ratio -> 'Ùn tắc'.
    """
    analyzer = CongestionAnalyzer({
        "max_occupancy_heavy": 5,
        "slow_speed_threshold_kmh": 20.0,
        "slow_vehicle_ratio_threshold": 0.5,
        "min_duration_seconds": 1.0,
        "min_valid_speed_samples": 1
    })

    estimator = SpeedEstimator((0, 100), (500, 100), (0, 200), (500, 200), distance_meters=10.0)

    # 6 vehicles, moving at 8 km/h (slow)
    roi_vehicles = []
    for tid in range(1, 7):
        roi_vehicles.append({"track_id": tid, "bbox": [0, 0, 50, 50]})
        estimator.records[tid] = {
            "t_a": 0.0,
            "t_b": 4.5,  # speed = 3.6 * 10 / 4.5 = 8 km/h
            "speed_kmh": 8.0,
            "is_valid": True,
            "direction": "A -> B",
            "reason": "Hợp lệ"
        }

    for t in range(10):
        res = analyzer.evaluate(roi_vehicles, speed_estimator=estimator, speed_calibration_enabled=True, timestamp_sec=t*0.2)

    assert res["status"] == "Ùn tắc"
