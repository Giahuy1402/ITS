import numpy as np
from backend.app.config import DEFAULT_CONGESTION_CONFIG

class CongestionAnalyzer:
    """
    Traffic Congestion Classifier using multi-metric analysis & temporal hysteresis.
    States:
    - 'Chưa đủ dữ liệu' (Insufficient Data)
    - 'Thông thoáng' (Clear Traffic)
    - 'Đông xe' (Heavy Traffic)
    - 'Ùn tắc' (Congested)
    """
    def __init__(self, config: dict = None):
        if config is None:
            config = DEFAULT_CONGESTION_CONFIG
        
        self.max_occupancy_heavy = config.get("max_occupancy_heavy", 8)
        self.slow_speed_threshold_kmh = config.get("slow_speed_threshold_kmh", 20.0)
        self.slow_vehicle_ratio_threshold = config.get("slow_vehicle_ratio_threshold", 0.5)
        self.min_duration_seconds = config.get("min_duration_seconds", 3.0)
        self.min_valid_speed_samples = config.get("min_valid_speed_samples", 1)

        # Sliding window history for temporal hysteresis
        self.pending_state = None
        self.pending_since = None
        self.current_state = "Chưa đủ dữ liệu"
        self.current_reason = "Đang khởi tạo phân tích"

    def evaluate(self, roi_vehicles: list, speed_estimator=None, speed_calibration_enabled: bool = False, timestamp_sec: float = 0.0):
        """
        roi_vehicles: list of active tracked vehicles inside ROI [{'track_id': int, 'bbox': [...], ...}]
        speed_estimator: SpeedEstimator instance (or None)
        speed_calibration_enabled: bool
        timestamp_sec: float

        Returns dict:
        {
            'status': str,
            'reason': str,
            'vehicle_count': int,
            'avg_speed_kmh': float or None,
            'slow_vehicle_ratio': float
        }
        """
        vehicle_count = len(roi_vehicles)
        valid_speeds = []
        slow_count = 0

        for v in roi_vehicles:
            tid = v["track_id"]
            if speed_estimator and speed_calibration_enabled:
                rec = speed_estimator.records.get(tid)
                if rec and rec.get("is_valid"):
                    spd = rec["speed_kmh"]
                    valid_speeds.append(spd)
                    if spd <= self.slow_speed_threshold_kmh:
                        slow_count += 1

        avg_speed_kmh = float(np.mean(valid_speeds)) if len(valid_speeds) > 0 else None
        slow_ratio = float(slow_count / len(valid_speeds)) if len(valid_speeds) > 0 else 0.0

        raw_status = "Thông thoáng"
        reason_parts = []

        if vehicle_count == 0:
            raw_status = "Thông thoáng"
            reason_parts.append("Không có phương tiện trong vùng khảo sát (ROI).")
        elif not speed_calibration_enabled or len(valid_speeds) < self.min_valid_speed_samples:
            # Without calibrated speed measurement, base estimate strictly on ROI occupancy
            if vehicle_count >= self.max_occupancy_heavy:
                raw_status = "Đông xe"
                reason_parts.append(f"Mật độ phương tiện cao ({vehicle_count} xe trong ROI). Chưa có hiệu chỉnh tốc độ thực (km/h).")
            else:
                raw_status = "Thông thoáng"
                reason_parts.append(f"Mật độ phương tiện bình thường ({vehicle_count} xe trong ROI). Chưa có hiệu chỉnh tốc độ.")
        else:
            # Full multi-metric analysis with calibrated speed
            if vehicle_count >= self.max_occupancy_heavy and avg_speed_kmh <= self.slow_speed_threshold_kmh and slow_ratio >= self.slow_vehicle_ratio_threshold:
                raw_status = "Ùn tắc"
                reason_parts.append(f"Mật độ xe cao ({vehicle_count} xe), tốc độ trung bình thấp ({avg_speed_kmh:.1f} km/h) và tỷ lệ xe chậm đạt {slow_ratio*100:.0f}%.")
            elif vehicle_count >= self.max_occupancy_heavy or avg_speed_kmh <= self.slow_speed_threshold_kmh:
                raw_status = "Đông xe"
                reason_parts.append(f"Có dấu hiệu đông xe ({vehicle_count} xe, tốc độ TB {avg_speed_kmh:.1f} km/h).")
            else:
                raw_status = "Thông thoáng"
                reason_parts.append(f"Lưu lượng ổn định ({vehicle_count} xe, tốc độ TB {avg_speed_kmh:.1f} km/h).")

        # Require uninterrupted evidence measured in video seconds, independent of FPS.
        reason = " ".join(reason_parts)
        if raw_status != self.pending_state:
            self.pending_state = raw_status
            self.pending_since = timestamp_sec
        if raw_status == self.current_state:
            self.current_reason = reason
        elif timestamp_sec - self.pending_since >= self.min_duration_seconds - 1e-9:
            self.current_state = raw_status
            self.current_reason = reason
        elif self.current_state == "Chưa đủ dữ liệu":
            self.current_reason = f"Đang xác nhận trạng thái trong {self.min_duration_seconds:g} giây."

        return {
            "status": self.current_state,
            "reason": self.current_reason,
            "vehicle_count": vehicle_count,
            "avg_speed_kmh": round(avg_speed_kmh, 1) if avg_speed_kmh is not None else None,
            "slow_vehicle_ratio": round(slow_ratio, 2)
        }
