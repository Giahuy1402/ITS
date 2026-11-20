import numpy as np
from collections import defaultdict
from backend.app.config import VEHICLE_CLASS_MAP

class SimpleByteTracker:
    """
    Greedy IoU tracker with trajectory memory.
    Intended for a fixed camera; this is not the full ByteTrack algorithm.
    """
    def __init__(self, max_disappeared: int = 30, iou_threshold: float = 0.3):
        self.next_id = 1
        self.tracks = {}  # track_id -> dict of track info
        self.disappeared = defaultdict(int)
        self.max_disappeared = max_disappeared
        self.iou_threshold = iou_threshold
        self.trajectories = defaultdict(list)  # track_id -> list of (x, y, timestamp_sec, frame_idx)

    def _compute_iou(self, box1, box2):
        x1_1, y1_1, x2_1, y2_1 = box1
        x1_2, y1_2, x2_2, y2_2 = box2

        xi1 = max(x1_1, x1_2)
        yi1 = max(y1_1, y1_2)
        xi2 = min(x2_1, x2_2)
        yi2 = min(y2_1, y2_2)

        inter_area = max(0.0, xi2 - xi1) * max(0.0, yi2 - yi1)
        box1_area = (x2_1 - x1_1) * (y2_1 - y1_1)
        box2_area = (x2_2 - x1_2) * (y2_2 - y1_2)

        union_area = box1_area + box2_area - inter_area
        if union_area <= 0:
            return 0.0
        return inter_area / union_area

    def update(self, detections: list, timestamp_sec: float, frame_idx: int):
        """
        Detections: list of dicts with 'bbox', 'class_id', 'class_name', 'conf', 'bottom_center'
        Returns: list of tracked objects with 'track_id' field added.
        """
        if len(self.tracks) == 0:
            # Register all as new tracks
            updated_objects = []
            for det in detections:
                track_id = self.next_id
                self.next_id += 1
                
                track_data = {
                    "track_id": track_id,
                    "bbox": det["bbox"],
                    "class_id": det["class_id"],
                    "class_name": det["class_name"],
                    "conf": det["conf"],
                    "bottom_center": det["bottom_center"],
                    "first_seen": timestamp_sec,
                    "last_seen": timestamp_sec
                }
                self.tracks[track_id] = track_data
                self.trajectories[track_id].append((det["bottom_center"][0], det["bottom_center"][1], timestamp_sec, frame_idx))
                updated_objects.append(track_data)
            return updated_objects

        track_ids = list(self.tracks.keys())
        predicted = {track["track_id"]: track for track in self.predict(timestamp_sec, include_missing=True)}
        existing_boxes = [predicted[tid]["bbox"] for tid in track_ids]

        if len(detections) == 0:
            # Mark all as disappeared
            for tid in track_ids:
                self.disappeared[tid] += 1
                if self.disappeared[tid] > self.max_disappeared:
                    del self.tracks[tid]
                    # Keep trajectory for offline speed/count analysis
            return []

        # Build IoU cost matrix
        det_boxes = [d["bbox"] for d in detections]
        iou_matrix = np.zeros((len(existing_boxes), len(det_boxes)), dtype=np.float32)
        for i, eb in enumerate(existing_boxes):
            for j, db in enumerate(det_boxes):
                iou_matrix[i, j] = self._compute_iou(eb, db)

        # Simple greedy assignment by max IoU
        matched_tracks = set()
        matched_dets = set()

        if iou_matrix.size > 0:
            # Find best pairs
            flat_indices = np.argsort(-iou_matrix.ravel())
            for idx in flat_indices:
                r = idx // iou_matrix.shape[1]
                c = idx % iou_matrix.shape[1]
                val = iou_matrix[r, c]

                if val < self.iou_threshold:
                    break
                if r in matched_tracks or c in matched_dets:
                    continue

                matched_tracks.add(r)
                matched_dets.add(c)

                tid = track_ids[r]
                det = detections[c]

                # Update existing track
                self.tracks[tid]["bbox"] = det["bbox"]
                self.tracks[tid]["conf"] = det["conf"]
                self.tracks[tid]["bottom_center"] = det["bottom_center"]
                self.tracks[tid]["last_seen"] = timestamp_sec
                # Update class if confidence is higher
                self.tracks[tid]["class_id"] = det["class_id"]
                self.tracks[tid]["class_name"] = det["class_name"]

                self.disappeared[tid] = 0
                self.trajectories[tid].append((det["bottom_center"][0], det["bottom_center"][1], timestamp_sec, frame_idx))

        # Handle unmatched tracks
        for r, tid in enumerate(track_ids):
            if r not in matched_tracks:
                self.disappeared[tid] += 1
                if self.disappeared[tid] > self.max_disappeared:
                    del self.tracks[tid]

        # Handle unmatched detections -> register new tracks
        updated_objects = []
        for c, det in enumerate(detections):
            if c in matched_dets:
                # Find track id
                for tid in track_ids:
                    if self.tracks.get(tid) and self.tracks[tid]["bbox"] == det["bbox"]:
                        t_data = dict(self.tracks[tid])
                        updated_objects.append(t_data)
                        break
            else:
                track_id = self.next_id
                self.next_id += 1

                track_data = {
                    "track_id": track_id,
                    "bbox": det["bbox"],
                    "class_id": det["class_id"],
                    "class_name": det["class_name"],
                    "conf": det["conf"],
                    "bottom_center": det["bottom_center"],
                    "first_seen": timestamp_sec,
                    "last_seen": timestamp_sec
                }
                self.tracks[track_id] = track_data
                self.trajectories[track_id].append((det["bottom_center"][0], det["bottom_center"][1], timestamp_sec, frame_idx))
                updated_objects.append(track_data)

        return updated_objects

    def predict(self, timestamp_sec, include_missing=False):
        result = []
        for tid, track in self.tracks.items():
            if not include_missing and self.disappeared[tid]:
                continue
            obj = dict(track)
            history = self.trajectories[tid]
            gap = max(0, min(timestamp_sec - track["last_seen"], 0.25))
            dx = dy = 0.0
            if len(history) >= 2 and history[-1][2] > history[-2][2]:
                dt = history[-1][2] - history[-2][2]
                dx = (history[-1][0] - history[-2][0]) / dt * gap
                dy = (history[-1][1] - history[-2][1]) / dt * gap
            x1, y1, x2, y2 = track["bbox"]
            obj["bbox"] = [x1+dx, y1+dy, x2+dx, y2+dy]
            obj["bottom_center"] = (track["bottom_center"][0]+dx, track["bottom_center"][1]+dy)
            result.append(obj)
        return result

    def get_trajectory(self, track_id: int):
        return self.trajectories.get(track_id, [])
