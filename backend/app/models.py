from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from backend.app.database import Base

class Video(Base):
    __tablename__ = "videos"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, nullable=False)
    original_name = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    file_size_bytes = Column(Integer, nullable=False)
    width = Column(Integer, nullable=False)
    height = Column(Integer, nullable=False)
    fps = Column(Float, nullable=False)
    total_frames = Column(Integer, nullable=False)
    duration_sec = Column(Float, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    sessions = relationship("AnalysisSession", back_populates="video", cascade="all, delete-orphan")


class AnalysisSession(Base):
    __tablename__ = "analysis_sessions"

    id = Column(Integer, primary_key=True, index=True)
    video_id = Column(Integer, ForeignKey("videos.id"), nullable=False)
    status = Column(String, default="pending")  # pending, processing, completed, failed, cancelled
    config_json = Column(Text, nullable=False)  # JSON string of configuration (ROI, lines, thresholds)
    progress_pct = Column(Float, default=0.0)
    processed_frames = Column(Integer, default=0)
    total_frames = Column(Integer, default=0)
    processing_fps = Column(Float, default=0.0)
    estimated_time_remaining_sec = Column(Float, default=0.0)

    # Result metrics
    total_vehicles_counted = Column(Integer, default=0)
    car_count = Column(Integer, default=0)
    motorcycle_count = Column(Integer, default=0)
    bus_count = Column(Integer, default=0)
    truck_count = Column(Integer, default=0)
    avg_speed_kmh = Column(Float, nullable=True)  # Null if not enough valid speed measurements
    final_traffic_status = Column(String, default="Chưa đủ dữ liệu")
    final_status_reason = Column(Text, default="")
    
    # Export paths
    annotated_video_path = Column(String, nullable=True)
    csv_report_path = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    completed_at = Column(DateTime, nullable=True)

    video = relationship("Video", back_populates="sessions")
    vehicle_records = relationship("VehicleRecord", back_populates="session", cascade="all, delete-orphan")
    congestion_logs = relationship("CongestionLog", back_populates="session", cascade="all, delete-orphan")


class VehicleRecord(Base):
    __tablename__ = "vehicle_records"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("analysis_sessions.id"), nullable=False)
    track_id = Column(Integer, nullable=False)
    vehicle_type = Column(String, nullable=False)  # Ô tô, Xe máy, Xe buýt, Xe tải
    
    # Time info
    first_seen_sec = Column(Float, nullable=False)
    last_seen_sec = Column(Float, nullable=False)
    line_crossed = Column(Boolean, default=False)
    line_cross_timestamp_sec = Column(Float, nullable=True)

    # Speed measurement info
    line_a_crossed_sec = Column(Float, nullable=True)
    line_b_crossed_sec = Column(Float, nullable=True)
    travel_time_sec = Column(Float, nullable=True)
    direction = Column(String, default="N/A")  # A->B or B->A
    speed_kmh = Column(Float, nullable=True)
    is_valid_speed = Column(Boolean, default=False)
    speed_status_reason = Column(String, default="Chưa đủ dữ liệu")

    session = relationship("AnalysisSession", back_populates="vehicle_records")


class CongestionLog(Base):
    __tablename__ = "congestion_logs"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("analysis_sessions.id"), nullable=False)
    frame_idx = Column(Integer, nullable=False)
    timestamp_sec = Column(Float, nullable=False)
    vehicle_count_roi = Column(Integer, nullable=False)
    avg_speed_kmh = Column(Float, nullable=True)
    slow_vehicle_ratio = Column(Float, nullable=False)
    traffic_status = Column(String, nullable=False)  # Thông thoáng, Đông xe, Ùn tắc, Chưa đủ dữ liệu
    reason = Column(Text, nullable=False)

    session = relationship("AnalysisSession", back_populates="congestion_logs")


class CalibrationPreset(Base):
    __tablename__ = "calibration_presets"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(String, default="")
    config_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
