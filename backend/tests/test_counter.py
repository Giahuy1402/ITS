import pytest
from backend.app.core.counter import LineCounter

def test_line_counter_single_increment():
    """
    Test requirement:
    A vehicle track crossing the line MUST be counted exactly ONCE, avoiding duplicate counts per frame.
    """
    counter = LineCounter((0, 200), (500, 200), direction_mode="both")
    track_id = 101

    # Trajectory crossing y=200
    traj_step1 = [(100, 150, 0.0, 0), (100, 180, 0.1, 3)]
    assert counter.check_crossing(track_id, traj_step1, "Ô tô") is False

    traj_step2 = traj_step1 + [(100, 220, 0.2, 6)]
    assert counter.check_crossing(track_id, traj_step2, "Ô tô") is True
    assert counter.total_count == 1
    assert counter.counts_by_type["Ô tô"] == 1

    # Subsequent frames crossing back or hovering near line for SAME track_id
    traj_step3 = traj_step2 + [(100, 250, 0.3, 9)]
    assert counter.check_crossing(track_id, traj_step3, "Ô tô") is False
    assert counter.total_count == 1  # Total count remains exactly 1!
