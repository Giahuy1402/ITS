import numpy as np

def intersect_point(A, B, C, D):
    """
    Find intersection point of segment AB and line segment CD.
    Returns (x, y) or None.
    """
    x1, y1 = A
    x2, y2 = B
    x3, y3 = C
    x4, y4 = D

    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-6:
        return None  # Parallel or collinear

    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
    u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / denom

    if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
    return None


# Typical real-world vehicle dimensions (width_m, length_m)
VEHICLE_DIMENSIONS_M = {
    "Ô tô": (1.80, 4.40),
    "Xe máy": (0.75, 1.95),
    "Xe buýt": (2.50, 10.50),
    "Xe tải": (2.40, 7.50),
}


class SpeedEstimator:
    """
    Vehicle speed estimator supporting:
    - 'two_line': Two-line landmark speed estimator using video timestamps.
      Formula: Speed (km/h) = 3.6 * Distance (m) / Delta_t (s)
    - 'auto': Perspective-aware automatic speed estimator using standard vehicle
      dimensions and smoothed displacement over a sliding time window.
    """
    def __init__(
        self,
        line_a_p1=None,
        line_a_p2=None,
        line_b_p1=None,
        line_b_p2=None,
        distance_meters: float = 10.0,
        mode: str = "two_line",
    ):
        self.mode = mode
        self.line_a_p1 = np.array(line_a_p1, dtype=float) if line_a_p1 is not None else None
        self.line_a_p2 = np.array(line_a_p2, dtype=float) if line_a_p2 is not None else None
        self.line_b_p1 = np.array(line_b_p1, dtype=float) if line_b_p1 is not None else None
        self.line_b_p2 = np.array(line_b_p2, dtype=float) if line_b_p2 is not None else None
        self.distance_meters = float(distance_meters)

        # track_id -> {'t_a': float, 't_b': float, 'speed_kmh': float, 'direction': str, ...}
        self.records = {}
        # Auto-mode per-track bbox history: track_id -> list of (w_px, h_px)
        self._bbox_sizes = {}

    def _interpolate_crossing_time(self, prev_pt, curr_pt, line_p1, line_p2, t_prev, t_curr):
        """
        Interpolates exact time fraction when moving from prev_pt (t_prev) to curr_pt (t_curr).
        """
        ix = intersect_point(prev_pt, curr_pt, line_p1, line_p2)
        if ix is None or t_curr == t_prev:
            return t_curr
        
        # Distance ratios
        dist_total = np.hypot(curr_pt[0] - prev_pt[0], curr_pt[1] - prev_pt[1])
        if dist_total < 1e-6:
            return t_curr

        dist_to_ix = np.hypot(ix[0] - prev_pt[0], ix[1] - prev_pt[1])
        ratio = min(max(dist_to_ix / dist_total, 0.0), 1.0)
        return t_prev + ratio * (t_curr - t_prev)

    def process_track(self, track_id: int, trajectory: list, bbox=None, class_name: str = "Ô tô"):
        """
        trajectory: list of (x, y, timestamp_sec, frame_idx)
        Updates speed record for track_id.
        Returns record dict or None.
        """
        if self.mode == "auto":
            return self._process_auto(track_id, trajectory, bbox=bbox, class_name=class_name)

        if len(trajectory) < 2:
            return self.records.get(track_id)

        rec = self.records.get(track_id, {
            "t_a": None,
            "t_b": None,
            "speed_kmh": None,
            "direction": "N/A",
            "is_valid": False,
            "reason": "Chưa đủ dữ liệu"
        })

        if rec["is_valid"]:
            return rec  # Already computed valid speed

        prev_pt = (trajectory[-2][0], trajectory[-2][1])
        curr_pt = (trajectory[-1][0], trajectory[-1][1])
        t_prev = trajectory[-2][2]
        t_curr = trajectory[-1][2]

        from backend.app.core.counter import intersect

        # Check line A crossing
        if rec["t_a"] is None and self.line_a_p1 is not None and self.line_a_p2 is not None:
            if intersect(prev_pt, curr_pt, self.line_a_p1, self.line_a_p2):
                rec["t_a"] = self._interpolate_crossing_time(prev_pt, curr_pt, self.line_a_p1, self.line_a_p2, t_prev, t_curr)

        # Check line B crossing
        if rec["t_b"] is None and self.line_b_p1 is not None and self.line_b_p2 is not None:
            if intersect(prev_pt, curr_pt, self.line_b_p1, self.line_b_p2):
                rec["t_b"] = self._interpolate_crossing_time(prev_pt, curr_pt, self.line_b_p1, self.line_b_p2, t_prev, t_curr)

        # If both lines A and B have been crossed, calculate speed
        if rec["t_a"] is not None and rec["t_b"] is not None and not rec["is_valid"]:
            delta_t = abs(rec["t_b"] - rec["t_a"])

            if delta_t > 0.05:  # Minimum 50ms delta_t sanity check
                speed_kmh = 3.6 * self.distance_meters / delta_t
                
                # Sanity check range for road vehicles (1 km/h to 200 km/h)
                if 1.0 <= speed_kmh <= 200.0:
                    rec["speed_kmh"] = round(speed_kmh, 1)
                    rec["is_valid"] = True
                    rec["direction"] = "A -> B" if rec["t_a"] < rec["t_b"] else "B -> A"
                    rec["reason"] = "Hợp lệ"
                else:
                    rec["reason"] = "Tốc độ ngoài dải đo cho phép"
            else:
                rec["reason"] = "Khoảng thời gian di chuyển quá ngắn"

        self.records[track_id] = rec
        return rec

    def _process_auto(self, track_id: int, trajectory: list, bbox=None, class_name: str = "Ô tô"):
        """
        Perspective-aware automatic speed estimation from vehicle dimensions and trajectory.
        """
        if bbox is not None:
            w_px = max(float(bbox[2] - bbox[0]), 1.0)
            h_px = max(float(bbox[3] - bbox[1]), 1.0)
            sizes = self._bbox_sizes.setdefault(track_id, [])
            sizes.append((w_px, h_px))
            if len(sizes) > 15:
                del sizes[:-15]

        rec = self.records.get(track_id, {
            "t_a": None,
            "t_b": None,
            "speed_kmh": None,
            "direction": "N/A",
            "is_valid": False,
            "reason": "Chưa đủ dữ liệu"
        })

        if len(trajectory) < 3:
            self.records[track_id] = rec
            return rec

        t_curr = trajectory[-1][2]
        # Pick a reference point ~0.4s - 0.8s earlier in the trajectory for noise immunity
        ref_idx = None
        for idx in range(len(trajectory) - 2, -1, -1):
            dt = t_curr - trajectory[idx][2]
            if dt >= 0.35:
                ref_idx = idx
                break

        if ref_idx is None:
            self.records[track_id] = rec
            return rec

        x0, y0, t0, _ = trajectory[ref_idx]
        x1, y1, t1, _ = trajectory[-1]
        dt = t1 - t0
        if dt <= 0.05:
            self.records[track_id] = rec
            return rec

        dx = x1 - x0
        dy = y1 - y0
        dist_px = float(np.hypot(dx, dy))

        # Determine dominant direction label
        if dist_px < 3.0:
            direction = "Đứng yên"
        elif abs(dy) >= abs(dx):
            direction = "Đi xuống" if dy > 0 else "Đi lên"
        else:
            direction = "Trái -> Phải" if dx > 0 else "Phải -> Trái"

        sizes = self._bbox_sizes.get(track_id)
        if not sizes:
            self.records[track_id] = rec
            return rec

        # Use median recent box dimensions to resist single-frame jitter
        med_w = float(np.median([s[0] for s in sizes]))
        med_h = float(np.median([s[1] for s in sizes]))

        phys_w, phys_l = VEHICLE_DIMENSIONS_M.get(class_name, (1.80, 4.40))

        if dist_px < 3.0:
            raw_speed = 0.0
        else:
            cos_a = abs(dx) / dist_px
            sin_a = abs(dy) / dist_px
            expected_w_m = phys_w * sin_a + phys_l * cos_a
            scale_x = expected_w_m / max(med_w, 4.0)

            # Compensate perspective foreshortening along the vertical image axis
            aspect_ratio = phys_l / max(phys_w, 0.1)
            foreshorten = float(np.clip(med_h / max(med_w * aspect_ratio, 1.0), 0.35, 1.0))
            scale_y = scale_x / (foreshorten * sin_a + 1.0 * cos_a)

            dist_m = float(np.hypot(dx * scale_x, dy * scale_y))
            raw_speed = 3.6 * dist_m / dt

        if raw_speed > 200.0:
            self.records[track_id] = rec
            return rec

        if rec["is_valid"] and rec["speed_kmh"] is not None:
            smoothed = 0.35 * raw_speed + 0.65 * rec["speed_kmh"]
        else:
            smoothed = raw_speed

        rec["speed_kmh"] = round(float(smoothed), 1)
        rec["is_valid"] = True
        rec["direction"] = direction
        rec["reason"] = "Ước lượng tự động"
        self.records[track_id] = rec
        return rec
