import cv2
import time
import json
import csv
from threading import Lock
import numpy as np
from pathlib import Path
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from backend.app.config import OUTPUTS_DIR
from backend.app.database import SessionLocal
from backend.app.models import AnalysisSession, Video, VehicleRecord, CongestionLog
from backend.app.core.detector import VehicleDetector, DemoVehicleDetector
from backend.app.core.tracker import SimpleByteTracker
from backend.app.core.video_writer import AnnotatedVideoWriter, find_ffmpeg
from backend.app.core.counter import LineCounter
from backend.app.core.speed_estimator import SpeedEstimator
from backend.app.core.congestion import CongestionAnalyzer

# Active session cancellation flags: session_id -> bool
CANCEL_REQUESTS = {}
# Global detector instance reuse for memory efficiency
_GLOBAL_DETECTOR = None
_DETECTOR_LOCK = Lock()

def get_detector():
    global _GLOBAL_DETECTOR
    with _DETECTOR_LOCK:
        if _GLOBAL_DETECTOR is None:
            _GLOBAL_DETECTOR = VehicleDetector()
    return _GLOBAL_DETECTOR

def point_in_polygon(pt, poly_pts):
    """
    pt: (x, y)
    poly_pts: np.array of shape (N, 1, 2)
    """
    if poly_pts is None or len(poly_pts) < 3:
        return True
    res = cv2.pointPolygonTest(poly_pts, (float(pt[0]), float(pt[1])), False)
    return res >= 0

def update_counts(session_obj, records, counter):
    if counter:
        counts = counter.counts_by_type
        total = counter.total_count
    else:
        counts = {}
        for record in records.values():
            key = record["vehicle_type"]
            counts[key] = counts.get(key, 0) + 1
        total = len(records)
    session_obj.total_vehicles_counted = total
    for attr, key in [("car_count", "Ô tô"), ("motorcycle_count", "Xe máy"),
                      ("bus_count", "Xe buýt"), ("truck_count", "Xe tải")]:
        setattr(session_obj, attr, counts.get(key, 0))


def process_video_session(session_id: int, broadcast_callback=None):
    """
    Main worker entry point for processing a video session.
    Runs asynchronously in a background thread or pool.
    """
    db: Session = SessionLocal()
    cap = None
    writer = None
    out_video_path = None
    vehicle_rows = {}
    dirty_tracks = set()
    session_obj = None
    try:
        session_obj = db.query(AnalysisSession).filter(AnalysisSession.id == session_id).first()
        if not session_obj:
            return

        if session_obj.status == "cancelled" or CANCEL_REQUESTS.get(session_id):
            session_obj.status = "cancelled"
            session_obj.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.commit()
            return
        if session_obj.status != "pending":
            return

        video_obj = db.query(Video).filter(Video.id == session_obj.video_id).first()
        if not video_obj:
            session_obj.status = "failed"
            session_obj.error_message = "Không tìm thấy file video trong cơ sở dữ liệu."
            session_obj.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.commit()
            return

        session_obj.status = "processing"
        db.commit()

        config = json.loads(session_obj.config_json)
        frame_skip = config.get("frame_skip", 1)
        output_fps = config.get("output_fps", 60)
        conf_thresh = config.get("confidence_threshold", 0.35)
        target_classes = config.get("target_classes", [2, 3, 5, 7])
        save_annotated_video = config.get("save_annotated_video", True)

        cap = cv2.VideoCapture(video_obj.file_path)
        if not cap.isOpened():
            session_obj.status = "failed"
            session_obj.error_message = "Không thể mở file video để xử lý."
            session_obj.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.commit()
            return

        fps = video_obj.fps if video_obj.fps > 0 else 30.0
        # Send compact track data to the live player, capped at 60 updates/sec.
        live_overlay_fps = min(60, max(1, int(config.get("live_overlay_fps", 60))))
        live_overlay_stride = max(1, int(np.ceil(fps / live_overlay_fps)))
        width = video_obj.width
        height = video_obj.height
        total_frames = video_obj.total_frames if video_obj.total_frames > 0 else int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        # Setup ROI polygon
        roi_pts = None
        if config.get("roi_polygon") and len(config["roi_polygon"]) >= 3:
            pts = []
            for p in config["roi_polygon"]:
                # Convert normalized coordinates if between 0 and 1
                px = p["x"] * width if p["x"] <= 1.0 else p["x"]
                py = p["y"] * height if p["y"] <= 1.0 else p["y"]
                pts.append([px, py])
            roi_pts = np.array(pts, dtype=np.int32).reshape((-1, 1, 2))

        # Setup Counting Line
        counter = None
        counting_config = config.get("counting_line")
        if counting_config and counting_config.get("enabled") and counting_config.get("line"):
            l = counting_config["line"]
            p1 = (l["p1"]["x"] * width if l["p1"]["x"] <= 1.0 else l["p1"]["x"],
                  l["p1"]["y"] * height if l["p1"]["y"] <= 1.0 else l["p1"]["y"])
            p2 = (l["p2"]["x"] * width if l["p2"]["x"] <= 1.0 else l["p2"]["x"],
                  l["p2"]["y"] * height if l["p2"]["y"] <= 1.0 else l["p2"]["y"])
            counter = LineCounter(p1, p2, direction_mode=counting_config.get("direction", "both"))

        # Setup Speed Calibration
        speed_estimator = None
        speed_enabled = False
        speed_config = config.get("speed_calibration")
        if speed_config and speed_config.get("enabled"):
            speed_mode = speed_config.get("mode", "two_line")
            if speed_mode == "auto":
                speed_estimator = SpeedEstimator(mode="auto")
                speed_enabled = True
            elif speed_config.get("line_a") and speed_config.get("line_b"):
                la = speed_config["line_a"]
                lb = speed_config["line_b"]
                la_p1 = (la["p1"]["x"] * width if la["p1"]["x"] <= 1.0 else la["p1"]["x"],
                         la["p1"]["y"] * height if la["p1"]["y"] <= 1.0 else la["p1"]["y"])
                la_p2 = (la["p2"]["x"] * width if la["p2"]["x"] <= 1.0 else la["p2"]["x"],
                         la["p2"]["y"] * height if la["p2"]["y"] <= 1.0 else la["p2"]["y"])

                lb_p1 = (lb["p1"]["x"] * width if lb["p1"]["x"] <= 1.0 else lb["p1"]["x"],
                         lb["p1"]["y"] * height if lb["p1"]["y"] <= 1.0 else lb["p1"]["y"])
                lb_p2 = (lb["p2"]["x"] * width if lb["p2"]["x"] <= 1.0 else lb["p2"]["x"],
                         lb["p2"]["y"] * height if lb["p2"]["y"] <= 1.0 else lb["p2"]["y"])

                dist_m = float(speed_config.get("distance_meters", 10.0))
                speed_estimator = SpeedEstimator(la_p1, la_p2, lb_p1, lb_p2, distance_meters=dist_m, mode="two_line")
                speed_enabled = True

        # Setup Congestion Analyzer
        congestion_config = config.get("congestion_thresholds", {})
        congestion_analyzer = CongestionAnalyzer(config=congestion_config)

        # Setup Video Writer
        out_video_path = None
        writer = None
        if save_annotated_video:
            suffix = "browser" if find_ffmpeg() else "output"
            out_video_path = str(OUTPUTS_DIR / f"session_{session_id}_{suffix}.mp4")
            writer = AnnotatedVideoWriter(out_video_path, fps, output_fps, width, height)

        # Detector and Tracker
        detector = DemoVehicleDetector() if config.get("detection_mode") == "demo" else get_detector()
        tracker = SimpleByteTracker()

        frame_idx = 0
        start_time = time.time()
        last_db_update = start_time
        vehicle_records_map = {}  # track_id -> VehicleRecord model kwargs
        last_log_second = -1
        congestion_res = None

        while cap.isOpened():
            # Check cancel request
            if CANCEL_REQUESTS.get(session_id, False):
                session_obj.status = "cancelled"
                session_obj.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
                session_obj.estimated_time_remaining_sec = 0
                db.commit()
                break

            ret, frame = cap.read()
            if not ret:
                break

            frame_idx += 1
            timestamp_sec = (frame_idx - 1) / fps
            detection_frame = (frame_idx - 1) % frame_skip == 0
            if detection_frame:
                # Step 1: Detect objects
                raw_detections = detector.detect(frame, conf_threshold=conf_thresh, target_classes=target_classes,
                        motorcycle_conf_threshold=config.get("motorcycle_confidence_threshold", 0.20))

                # Step 2: Track objects
                tracked_objs = tracker.update(raw_detections, timestamp_sec=timestamp_sec, frame_idx=frame_idx)

                # Step 3: Filter by ROI & Process speed & counting
                roi_vehicles = []
                for obj in tracked_objs:
                    tid = obj["track_id"]
                    bottom_pt = obj["bottom_center"]
                    traj = tracker.get_trajectory(tid)
                    v_type = obj["class_name"]

                    # Track history initialization in DB map
                    if tid not in vehicle_records_map:
                        vehicle_records_map[tid] = {
                            "track_id": tid,
                            "vehicle_type": v_type,
                            "first_seen_sec": timestamp_sec,
                            "last_seen_sec": timestamp_sec,
                            "line_crossed": False,
                            "line_cross_timestamp_sec": None,
                            "line_a_crossed_sec": None,
                            "line_b_crossed_sec": None,
                            "travel_time_sec": None,
                            "direction": "N/A",
                            "speed_kmh": None,
                            "is_valid_speed": False,
                            "speed_status_reason": "Chưa đủ dữ liệu"
                        }
                    else:
                        vehicle_records_map[tid]["last_seen_sec"] = timestamp_sec

                    dirty_tracks.add(tid)

                    # Check line counter
                    if counter:
                        if counter.check_crossing(tid, traj, v_type):
                            vehicle_records_map[tid]["line_crossed"] = True
                            vehicle_records_map[tid]["line_cross_timestamp_sec"] = timestamp_sec

                    # Check speed calibration
                    if speed_estimator:
                        speed_rec = speed_estimator.process_track(tid, traj, bbox=obj["bbox"], class_name=v_type)
                        if speed_rec:
                            vehicle_records_map[tid]["line_a_crossed_sec"] = speed_rec.get("t_a")
                            vehicle_records_map[tid]["line_b_crossed_sec"] = speed_rec.get("t_b")
                            if speed_rec.get("t_a") is not None and speed_rec.get("t_b") is not None:
                                vehicle_records_map[tid]["travel_time_sec"] = abs(speed_rec["t_b"] - speed_rec["t_a"])
                            vehicle_records_map[tid]["direction"] = speed_rec.get("direction", "N/A")
                            vehicle_records_map[tid]["speed_kmh"] = speed_rec.get("speed_kmh")
                            vehicle_records_map[tid]["is_valid_speed"] = speed_rec.get("is_valid", False)
                            vehicle_records_map[tid]["speed_status_reason"] = speed_rec.get("reason", "Chưa đủ dữ liệu")

                    # Check ROI occupancy
                    if point_in_polygon(bottom_pt, roi_pts):
                        roi_vehicles.append(obj)

                # Step 4: Evaluate Congestion
                congestion_res = congestion_analyzer.evaluate(
                    roi_vehicles,
                    speed_estimator=speed_estimator,
                    speed_calibration_enabled=speed_enabled,
                    timestamp_sec=timestamp_sec
                )

                # Record congestion log every 1 second (or every 30 frames)
                if int(timestamp_sec) > last_log_second:
                    last_log_second = int(timestamp_sec)
                    clog = CongestionLog(
                        session_id=session_id,
                        frame_idx=frame_idx,
                        timestamp_sec=timestamp_sec,
                        vehicle_count_roi=congestion_res["vehicle_count"],
                        avg_speed_kmh=congestion_res["avg_speed_kmh"],
                        slow_vehicle_ratio=congestion_res["slow_vehicle_ratio"],
                        traffic_status=congestion_res["status"],
                        reason=congestion_res["reason"]
                    )
                    db.add(clog)

            else:
                # Predict boxes only for drawing. Counts and speed use observed detections.
                tracked_objs = tracker.predict(timestamp_sec)

            # Step 5: Draw Annotations on Frame
            if writer or broadcast_callback:
                # Draw ROI polygon
                if roi_pts is not None:
                    cv2.polylines(frame, [roi_pts], True, (0, 255, 255), 2)
                    overlay = frame.copy()
                    cv2.fillPoly(overlay, [roi_pts], (0, 255, 255))
                    cv2.addWeighted(overlay, 0.1, frame, 0.9, 0, frame)

                # Draw Counting Line
                if counter:
                    cv2.line(frame, tuple(counter.p1.astype(int)), tuple(counter.p2.astype(int)), (255, 255, 0), 3)
                    cv2.putText(frame, f"Vach dem xe (Count: {counter.total_count})", tuple(counter.p1.astype(int)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)

                # Draw Speed Calibration Lines
                if speed_estimator and speed_estimator.mode == "two_line" and speed_estimator.line_a_p1 is not None:
                    cv2.line(frame, tuple(speed_estimator.line_a_p1.astype(int)), tuple(speed_estimator.line_a_p2.astype(int)), (255, 0, 255), 2)
                    cv2.putText(frame, "Vach A", tuple(speed_estimator.line_a_p1.astype(int)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 255), 2)

                    cv2.line(frame, tuple(speed_estimator.line_b_p1.astype(int)), tuple(speed_estimator.line_b_p2.astype(int)), (0, 165, 255), 2)
                    cv2.putText(frame, f"Vach B ({speed_estimator.distance_meters}m)", tuple(speed_estimator.line_b_p1.astype(int)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 165, 255), 2)

                # Draw Tracked Bounding Boxes & Trajectories
                for obj in tracked_objs:
                    tid = obj["track_id"]
                    x1, y1, x2, y2 = map(int, obj["bbox"])
                    v_type = obj["class_name"]
                    
                    # Trajectory line
                    traj = tracker.get_trajectory(tid)
                    if len(traj) > 1:
                        pts_list = [np.array([p[0], p[1]], dtype=np.int32) for p in traj[-15:]]
                        for i in range(1, len(pts_list)):
                            cv2.line(frame, tuple(pts_list[i-1]), tuple(pts_list[i]), (0, 255, 0), 2)

                    # Speed badge string
                    speed_str = "Chua du du lieu"
                    if speed_estimator:
                        rec = speed_estimator.records.get(tid)
                        if rec and rec.get("is_valid"):
                            speed_str = f"{rec['speed_kmh']} km/h"

                    # Box color based on vehicle type
                    box_color = (0, 255, 0)
                    if v_type == "Xe máy":
                        box_color = (255, 200, 0)
                    elif v_type == "Xe buýt":
                        box_color = (0, 100, 255)
                    elif v_type == "Xe tải":
                        box_color = (0, 0, 255)

                    cv2.rectangle(frame, (x1, y1), (x2, y2), box_color, 2)
                    label = f"#{tid} {v_type} | {speed_str}"
                    cv2.putText(frame, label, (x1, max(y1 - 10, 20)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, box_color, 2)
                    cv2.circle(frame, (int(obj["bottom_center"][0]), int(obj["bottom_center"][1])), 4, (0, 0, 255), -1)

                # Top Overlay Dashboard Panel
                panel_color = (30, 30, 30)
                cv2.rectangle(frame, (10, 10), (450, 100), panel_color, -1)
                cv2.rectangle(frame, (10, 10), (450, 100), (100, 100, 100), 1)

                status_text = f"Trang thai: {congestion_res['status']}"
                status_color = (0, 255, 0) if congestion_res['status'] == "Thông thoáng" else ((0, 165, 255) if congestion_res['status'] == "Đông xe" else (0, 0, 255))
                cv2.putText(frame, status_text, (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.6, status_color, 2)

                count_text = f"ROI: {congestion_res['vehicle_count']} xe | Tong dem: {counter.total_count if counter else len(vehicle_records_map)}"
                cv2.putText(frame, count_text, (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

                spd_text = f"Toc do TB ROI: {congestion_res['avg_speed_kmh'] if congestion_res['avg_speed_kmh'] else 'Chua du du lieu'} km/h"
                cv2.putText(frame, spd_text, (20, 85), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

                if writer:
                    writer.write(frame)

            # Coordinates are far smaller than JPEG previews and align to the
            # exact frame shown by the source video in the browser.
            if broadcast_callback and ((frame_idx - 1) % live_overlay_stride == 0):
                broadcast_callback({
                    "kind": "tracks",
                    "session_id": session_id,
                    "frame_idx": frame_idx,
                    "timestamp_sec": round(timestamp_sec, 4),
                    "tracks": [
                        {
                            "track_id": int(obj["track_id"]),
                            "class_name": obj["class_name"],
                            "bbox": [round(float(value), 1) for value in obj["bbox"]],
                            "speed_kmh": (
                                speed_estimator.records[obj["track_id"]]["speed_kmh"]
                                if speed_estimator
                                and obj["track_id"] in speed_estimator.records
                                and speed_estimator.records[obj["track_id"]].get("is_valid")
                                else None
                            ),
                        }
                        for obj in tracked_objs
                    ],
                })

            # Periodic Database & Progress update
            now = time.time()
            if now - last_db_update >= 0.5 or frame_idx == total_frames:
                elapsed = max(now - start_time, 0.001)
                proc_fps = round(frame_idx / elapsed, 1)
                rem_frames = total_frames - frame_idx
                eta_sec = round(rem_frames / max(proc_fps, 0.1), 1)
                progress = round((frame_idx / max(total_frames, 1)) * 100.0, 1)

                session_obj.progress_pct = min(progress, 100.0)
                session_obj.processed_frames = frame_idx
                session_obj.total_frames = total_frames
                session_obj.processing_fps = proc_fps
                session_obj.estimated_time_remaining_sec = eta_sec

                valid_speeds = [r["speed_kmh"] for r in vehicle_records_map.values() if r["is_valid_speed"]]
                session_obj.avg_speed_kmh = round(float(np.mean(valid_speeds)), 1) if len(valid_speeds) > 0 else None
                update_counts(session_obj, vehicle_records_map, counter)
                for tid in dirty_tracks:
                    data = vehicle_records_map[tid]
                    if tid not in vehicle_rows:
                        vehicle_rows[tid] = VehicleRecord(session_id=session_id, **data)
                        db.add(vehicle_rows[tid])
                    else:
                        for key, value in data.items():
                            setattr(vehicle_rows[tid], key, value)
                session_obj.final_traffic_status = congestion_res["status"]
                session_obj.final_status_reason = congestion_res["reason"]

                db.commit()
                dirty_tracks.clear()
                last_db_update = now

                if broadcast_callback:
                    broadcast_callback({
                        "kind": "progress",
                        "status": "processing",
                        "session_id": session_id,
                        "progress_pct": progress,
                        "processed_frames": frame_idx,
                        "total_frames": total_frames,
                        "processing_fps": proc_fps,
                        "eta_sec": eta_sec,
                        "traffic_status": congestion_res["status"],
                        "reason": congestion_res["reason"],
                        "avg_speed_kmh": session_obj.avg_speed_kmh
                    })

        cap.release()
        if writer:
            if CANCEL_REQUESTS.get(session_id, False):
                writer.abort()
            else:
                writer.release()

        if frame_idx == 0 and not CANCEL_REQUESTS.get(session_id):
            raise RuntimeError("Video không có khung hình đọc được.")

        # If completed normally without cancellation
        if not CANCEL_REQUESTS.get(session_id, False):
            # Save all VehicleRecords to DB
            for tid, rec_data in vehicle_records_map.items():
                if tid not in vehicle_rows:
                    vehicle_rows[tid] = VehicleRecord(session_id=session_id, **rec_data)
                    db.add(vehicle_rows[tid])
                else:
                    for key, value in rec_data.items():
                        setattr(vehicle_rows[tid], key, value)
            update_counts(session_obj, vehicle_records_map, counter)
            valid_speeds = [r["speed_kmh"] for r in vehicle_records_map.values() if r["is_valid_speed"]]
            session_obj.avg_speed_kmh = round(float(np.mean(valid_speeds)), 1) if valid_speeds else None
            if congestion_res:
                session_obj.final_traffic_status = congestion_res["status"]
                session_obj.final_status_reason = congestion_res["reason"]
            session_obj.processed_frames = frame_idx
            session_obj.progress_pct = 100.0
            session_obj.estimated_time_remaining_sec = 0
            if CANCEL_REQUESTS.get(session_id):
                session_obj.status = "cancelled"
                session_obj.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
                db.commit()
                return

            # Generate CSV Export
            csv_filename = f"session_{session_id}_report.csv"
            csv_path = OUTPUTS_DIR / csv_filename
            with open(csv_path, mode="w", newline="", encoding="utf-8-sig") as csv_file:
                writer_csv = csv.writer(csv_file)
                writer_csv.writerow(["Track ID", "Loai xe", "Thoi diem xuat hien (s)", "Thoi diem roi di (s)", "Huong di chuyen", "Toc do (km/h)", "Phep do hop le", "Ly do / Ghi chu", "Da qua vach dem", "Thoi diem qua vach (s)"])
                for r in vehicle_records_map.values():
                    writer_csv.writerow([
                        r["track_id"],
                        r["vehicle_type"],
                        f"{r['first_seen_sec']:.2f}",
                        f"{r['last_seen_sec']:.2f}",
                        r["direction"],
                        f"{r['speed_kmh']:.1f}" if r['speed_kmh'] is not None else "Chua du du lieu",
                        "Co" if r["is_valid_speed"] else "Khong",
                        r["speed_status_reason"],
                        "Co" if r["line_crossed"] else "Khong",
                        f"{r['line_cross_timestamp_sec']:.2f}" if r["line_cross_timestamp_sec"] is not None else ""
                    ])

            session_obj.annotated_video_path = out_video_path
            session_obj.csv_report_path = str(csv_path)
            session_obj.status = "completed"
            session_obj.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.commit()

    except Exception as e:
        db.rollback()
        session_obj = db.query(AnalysisSession).filter(AnalysisSession.id == session_id).first()
        if session_obj:
            session_obj.status = "failed"
            session_obj.error_message = str(e)
            session_obj.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            session_obj.estimated_time_remaining_sec = 0
            db.commit()
    finally:
        if cap is not None:
            cap.release()
        if writer is not None:
            try:
                writer.abort()
            except Exception:
                pass  # Preserve the original worker error after stopping the encoder.
        if out_video_path and session_obj and session_obj.status != "completed":
            Path(out_video_path).unlink(missing_ok=True)
        db.close()
        if session_id in CANCEL_REQUESTS:
            del CANCEL_REQUESTS[session_id]
