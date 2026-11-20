import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = Path(os.environ.get("ITS_DATA_DIR", str(BASE_DIR))).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR = DATA_DIR / "uploads"
OUTPUTS_DIR = DATA_DIR / "outputs"
DATABASE_PATH = DATA_DIR / "trafficvision.db"

# Create required directories
UPLOADS_DIR.mkdir(exist_ok=True)
OUTPUTS_DIR.mkdir(exist_ok=True)

DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

# YOLO vehicle class mapping (COCO dataset IDs)
# 2: car, 3: motorcycle, 5: bus, 7: truck
VEHICLE_CLASS_MAP = {
    2: "Ô tô",
    3: "Xe máy",
    5: "Xe buýt",
    7: "Xe tải"
}

# English keys for database and internal normalization
VEHICLE_TYPE_KEYS = {
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck"
}

DEFAULT_YOLO_MODEL = str(BASE_DIR / "yolov8n.pt")
DEFAULT_CONFIDENCE_THRESHOLD = 0.35

# Congestion detection defaults
DEFAULT_CONGESTION_CONFIG = {
    "max_occupancy_heavy": 8,       # Vehicle count in ROI for heavy traffic
    "slow_speed_threshold_kmh": 20.0, # Below this speed is considered slow
    "slow_vehicle_ratio_threshold": 0.5, # 50% slow vehicles triggers congestion warning
    "min_duration_seconds": 3.0,     # Must persist for at least 3 seconds
    "min_valid_speed_samples": 1    # Minimum speed measurements required for speed-based congestion
}
