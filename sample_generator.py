import cv2
import numpy as np
from pathlib import Path
from backend.app.config import UPLOADS_DIR
from backend.app.core.video_writer import AnnotatedVideoWriter

def generate_sample_traffic_video(output_path: str = None, duration_sec: int = 10, fps: int = 30):
    if output_path is None:
        UPLOADS_DIR.mkdir(exist_ok=True)
        output_path = str(UPLOADS_DIR / "sample_traffic.mp4")

    if duration_sec <= 0 or fps <= 0:
        raise ValueError("Thời lượng và FPS phải lớn hơn 0.")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    width, height = 1280, 720
    total_frames = int(duration_sec * fps)

    writer = AnnotatedVideoWriter(output_path, fps, fps, width, height)

    # Vehicles to simulate: (start_frame, x_pos, speed_px_per_frame, color, width, height_box, label)
    vehicles = [
        {"start_frame": 0, "x": 450, "speed": 6.5, "color": (200, 50, 50), "w": 60, "h": 100, "name": "Car 1"},
        {"start_frame": 15, "x": 650, "speed": 8.0, "color": (50, 200, 50), "w": 55, "h": 90, "name": "Car 2"},
        {"start_frame": 45, "x": 480, "speed": 5.0, "color": (50, 50, 200), "w": 70, "h": 120, "name": "Truck 1"},
        {"start_frame": 75, "x": 620, "speed": 7.2, "color": (220, 220, 50), "w": 40, "h": 60, "name": "Motorcycle 1"},
        {"start_frame": 120, "x": 520, "speed": 6.0, "color": (200, 100, 200), "w": 65, "h": 100, "name": "Car 3"},
        {"start_frame": 150, "x": 680, "speed": 9.0, "color": (50, 200, 220), "w": 50, "h": 85, "name": "Car 4"},
    ]

    for frame_idx in range(total_frames):
        # Draw road background
        frame = np.full((height, width, 3), (60, 60, 60), dtype=np.uint8)

        # Draw grass/borders
        frame[:, :300] = (40, 100, 40)
        frame[:, 980:] = (40, 100, 40)

        # Draw road lines (white solid borders, yellow center dashed)
        cv2.line(frame, (300, 0), (300, height), (255, 255, 255), 4)
        cv2.line(frame, (980, 0), (980, height), (255, 255, 255), 4)

        # Center dashed line
        dash_len = 30
        for y in range(0, height, dash_len * 2):
            cv2.line(frame, (640, y), (640, y + dash_len), (0, 220, 255), 3)

        # Draw Landmark Reference Marks on road surface
        cv2.putText(frame, f"SYNTHETIC DEMO - 720P @ {fps}FPS", (330, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        # Render moving vehicles
        for v in vehicles:
            if frame_idx >= v["start_frame"]:
                elapsed_f = frame_idx - v["start_frame"]
                y_pos = int(elapsed_f * v["speed"]) - v["h"]
                
                if -v["h"] <= y_pos <= height + v["h"]:
                    x1 = v["x"]
                    y1 = y_pos
                    x2 = x1 + v["w"]
                    y2 = y1 + v["h"]

                    # Vehicle body
                    cv2.rectangle(frame, (x1, y1), (x2, y2), v["color"], -1)
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 255, 255), 2)
                    
                    # Windshield
                    cv2.rectangle(frame, (x1 + 5, y1 + 15), (x2 - 5, y1 + 35), (220, 220, 220), -1)

        writer.write(frame)

    writer.release()
    print(f"Sample traffic video generated successfully at: {output_path}")
    return output_path

if __name__ == "__main__":
    generate_sample_traffic_video()
