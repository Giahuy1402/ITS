import numpy as np

def ccw(A, B, C):
    """
    Check if 3 points A, B, C are in counter-clockwise order.
    Returns boolean / float cross product sign.
    """
    return (C[1] - A[1]) * (B[0] - A[0]) > (B[1] - A[1]) * (C[0] - A[0])

def intersect(A, B, C, D):
    """
    Returns True if line segment AB intersects line segment CD.
    A, B: trajectory points (prev, curr)
    C, D: counting line points (p1, p2)
    """
    return ccw(A, C, D) != ccw(B, C, D) and ccw(A, B, C) != ccw(A, B, D)

class LineCounter:
    """
    Virtual line vehicle counter.
    Tracks crossed IDs to guarantee each vehicle track is counted at most once per line.
    """
    def __init__(self, line_p1: tuple, line_p2: tuple, direction_mode: str = "both"):
        """
        line_p1, line_p2: (x, y) coordinates of virtual line
        direction_mode: 'in', 'out', 'both'
        """
        self.p1 = np.array(line_p1, dtype=float)
        self.p2 = np.array(line_p2, dtype=float)
        self.direction_mode = direction_mode
        self.counted_ids = set()
        self.counts_by_type = {"Ô tô": 0, "Xe máy": 0, "Xe buýt": 0, "Xe tải": 0}
        self.total_count = 0

    def check_crossing(self, track_id: int, trajectory: list, vehicle_type: str):
        """
        trajectory: list of (x, y, timestamp_sec, frame_idx)
        Returns True if a new line crossing event occurred.
        """
        if track_id in self.counted_ids or len(trajectory) < 2:
            return False

        # Get previous point and current point
        prev_pt = (trajectory[-2][0], trajectory[-2][1])
        curr_pt = (trajectory[-1][0], trajectory[-1][1])

        # Check line segment intersection
        if intersect(prev_pt, curr_pt, self.p1, self.p2):
            # Direction check using cross product vector
            line_vec = self.p2 - self.p1
            move_vec = np.array(curr_pt) - np.array(prev_pt)
            cross_val = line_vec[0] * move_vec[1] - line_vec[1] * move_vec[0]

            if self.direction_mode == "in" and cross_val < 0:
                return False
            elif self.direction_mode == "out" and cross_val > 0:
                return False

            # Valid crossing event!
            self.counted_ids.add(track_id)
            self.total_count += 1
            if vehicle_type in self.counts_by_type:
                self.counts_by_type[vehicle_type] += 1
            else:
                self.counts_by_type[vehicle_type] = 1

            return True

        return False
