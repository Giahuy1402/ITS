"""Suggest normalized road regions and cross-lines from sampled image motion.
No physical distance or calibrated speed is inferred from pixels.
"""
import cv2
import numpy as np


def suggest_setup(file_path):
    cap = cv2.VideoCapture(str(file_path))
    locations = []
    horizontal_energy = 0.0
    vertical_energy = 0.0
    try:
        if not cap.isOpened():
            raise ValueError("Không thể mở video để thiết lập tự động.")
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        readable = False
        for index in np.unique(np.linspace(0, max(0, total - 3), min(16, max(1, total)), dtype=int)):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(index))
            ok, first = cap.read()
            if not ok:
                continue
            readable = True
            ok, second = cap.read()
            if not ok:
                continue
            scale = min(480 / first.shape[1], 320 / first.shape[0], 1.0)
            size = (max(1, round(first.shape[1] * scale)), max(1, round(first.shape[0] * scale)))
            a, b = [cv2.cvtColor(cv2.resize(frame, size), cv2.COLOR_BGR2GRAY) for frame in (first, second)]
            flow = cv2.calcOpticalFlowFarneback(a, b, None, 0.5, 3, 15, 3, 5, 1.2, 0)
            magnitude = np.linalg.norm(flow, axis=2)
            mask = ((magnitude > 0.35) & (cv2.absdiff(a, b) > 8)).astype(np.uint8)
            mask = cv2.dilate(mask, np.ones((5, 5), np.uint8))
            # Global motion often means camera movement; do not call it a road region.
            if np.mean(mask) > 0.45:
                continue
            count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
            for component in range(1, count):
                if stats[component, cv2.CC_STAT_AREA] < max(12, mask.size * 0.0005):
                    continue
                ys, xs = np.where(labels == component)
                locations.append(np.column_stack((xs / size[0], ys / size[1])))
                # Textureless edges can produce large flow outliers; use the median
                # per moving component so those outliers do not flip the cross-line.
                median = np.median(np.abs(flow[ys, xs]), axis=0)
                horizontal_energy += float(median[0] ** 2) * len(xs)
                vertical_energy += float(median[1] ** 2) * len(xs)
        if not readable:
            raise ValueError("Video không có khung hình đọc được.")
    finally:
        cap.release()

    if locations:
        pts = np.concatenate(locations)
        low, high = np.quantile(pts, [0.02, 0.98], axis=0)
        center = (low + high) / 2
        half = np.maximum((high - low) / 2 + 0.06, 0.18)
        low = np.clip(center - half, 0.03, 0.61)
        high = np.clip(center + half, low + 0.3, 0.97)
        x1, y1 = map(float, low)
        x2, y2 = map(float, high)
        axis = "horizontal" if horizontal_energy > vertical_energy else "vertical"
        method = "motion"
        note = "Đã tự đặt vùng quan sát và vạch theo chuyển động trong video."
    else:
        x1, y1, x2, y2 = 0.05, 0.1, 0.95, 0.95
        axis, method = "vertical", "default"
        note = "Chưa thấy chuyển động rõ; đang dùng vùng quan sát rộng và vạch giữa khung hình."

    def point(x, y):
        return {"x": round(x, 6), "y": round(y, 6)}

    def line(fraction):
        if axis == "vertical":
            y = y1 + (y2 - y1) * fraction
            return {"p1": point(x1, y), "p2": point(x2, y)}
        x = x1 + (x2 - x1) * fraction
        return {"p1": point(x, y1), "p2": point(x, y2)}

    return {"roi_polygon": [point(x1, y1), point(x2, y1), point(x2, y2), point(x1, y2)],
            "count_line": line(0.5), "line_a": line(0.3), "line_b": line(0.7),
            "count_enabled": True, "speed_enabled": False, "distance_meters": None,
            "method": method, "motion_axis": axis,
            "note": note + " Chưa hiệu chỉnh khoảng cách thực nên chưa đo tốc độ km/h."}
