from pydantic import BaseModel, Field, ConfigDict, model_validator
from typing import List, Optional, Dict, Any, Literal
from datetime import datetime

# ROI point representation
class Point(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)

class LineSegment(BaseModel):
    p1: Point
    p2: Point

    @model_validator(mode="after")
    def validate_length(self):
        if self.p1 == self.p2:
            raise ValueError("Hai đầu vạch phải khác nhau.")
        return self

class SpeedCalibrationConfig(BaseModel):
    enabled: bool = False
    mode: Literal["two_line", "auto"] = "two_line"
    line_a: Optional[LineSegment] = None
    line_b: Optional[LineSegment] = None
    distance_meters: float = Field(default=10.0, gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_lines(self):
        if self.enabled and self.mode == "two_line":
            if not self.line_a or not self.line_b:
                raise ValueError("Đo tốc độ cần cả vạch A và vạch B.")
            from backend.app.core.speed_estimator import intersect_point
            a, b = self.line_a, self.line_b
            points = [(p.x, p.y) for p in (a.p1, a.p2, b.p1, b.p2)]
            if intersect_point(*points) is not None:
                raise ValueError("Hai vạch đo tốc độ không được giao nhau.")
            dx, dy = a.p2.x-a.p1.x, a.p2.y-a.p1.y
            if all(abs(dx*(p.y-a.p1.y)-dy*(p.x-a.p1.x)) < 1e-9 for p in (b.p1,b.p2)):
                raise ValueError("Hai vạch đo tốc độ không được cùng một đường thẳng.")
        return self

class CountingLineConfig(BaseModel):
    enabled: bool = False
    line: Optional[LineSegment] = None
    direction: Literal["in", "out", "both"] = "both"

    @model_validator(mode="after")
    def validate_line(self):
        if self.enabled and self.line is None:
            raise ValueError("Cần vẽ vạch đếm xe.")
        return self

class CongestionThresholds(BaseModel):
    max_occupancy_heavy: int = Field(default=8, ge=1)
    slow_speed_threshold_kmh: float = Field(default=20.0, gt=0, allow_inf_nan=False)
    slow_vehicle_ratio_threshold: float = Field(default=0.5, gt=0, le=1, allow_inf_nan=False)
    min_duration_seconds: float = Field(default=3.0, ge=0, allow_inf_nan=False)
    min_valid_speed_samples: int = Field(default=1, ge=1)

class SessionStartConfig(BaseModel):
    video_id: int = Field(gt=0)
    confidence_threshold: float = Field(default=0.35, gt=0, le=1, allow_inf_nan=False)
    target_classes: List[Literal[2, 3, 5, 7]] = Field(default_factory=lambda: [2, 3, 5, 7], min_length=1) # car, moto, bus, truck
    roi_polygon: Optional[List[Point]] = None
    counting_line: Optional[CountingLineConfig] = None
    speed_calibration: Optional[SpeedCalibrationConfig] = None
    congestion_thresholds: Optional[CongestionThresholds] = None
    save_annotated_video: bool = True
    frame_skip: int = Field(default=1, ge=1, le=10)
    output_fps: int = Field(default=60, ge=1, le=240)
    live_overlay_fps: int = Field(default=60, ge=1, le=60)
    motorcycle_confidence_threshold: float = Field(default=0.20, gt=0, le=1, allow_inf_nan=False)
    detection_mode: Literal["yolo", "demo"] = "yolo"

    @model_validator(mode="after")
    def validate_roi(self):
        pts = self.roi_polygon
        if pts:
            area = sum(p.x*q.y-q.x*p.y for p,q in zip(pts, pts[1:]+pts[:1]))
            if len(pts) < 3 or abs(area) < 1e-9:
                raise ValueError("ROI cần ít nhất 3 điểm tạo thành vùng có diện tích.")
        return self

# Responses
class VideoResponse(BaseModel):
    id: int
    filename: str
    original_name: str
    file_size_bytes: int
    width: int
    height: int
    fps: float
    total_frames: int
    duration_sec: float
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class VehicleRecordResponse(BaseModel):
    id: int
    track_id: int
    vehicle_type: str
    first_seen_sec: float
    last_seen_sec: float
    direction: str
    speed_kmh: Optional[float]
    is_valid_speed: bool
    speed_status_reason: str

    model_config = ConfigDict(from_attributes=True)

class CongestionLogResponse(BaseModel):
    id: int
    frame_idx: int
    timestamp_sec: float
    vehicle_count_roi: int
    avg_speed_kmh: Optional[float]
    slow_vehicle_ratio: float
    traffic_status: str
    reason: str

    model_config = ConfigDict(from_attributes=True)

class SessionStatusResponse(BaseModel):
    id: int
    video_id: int = Field(gt=0)
    status: str
    progress_pct: float
    processed_frames: int
    total_frames: int
    processing_fps: float
    estimated_time_remaining_sec: float
    total_vehicles_counted: int
    car_count: int
    motorcycle_count: int
    bus_count: int
    truck_count: int
    avg_speed_kmh: Optional[float]
    final_traffic_status: str
    final_status_reason: str
    annotated_video_path: Optional[str] = None
    csv_report_path: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

class SessionDetailResponse(SessionStatusResponse):
    config: Dict[str, Any]
    recent_records: List[VehicleRecordResponse] = Field(default_factory=list)
    congestion_timeline: List[CongestionLogResponse] = Field(default_factory=list)

class CalibrationPresetResponse(BaseModel):
    id: int
    name: str
    description: str
    config_json: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
