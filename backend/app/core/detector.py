from threading import Lock
from pathlib import Path
import os
import cv2
from backend.app.config import VEHICLE_CLASS_MAP, DEFAULT_YOLO_MODEL, DEFAULT_CONFIDENCE_THRESHOLD


class VehicleDetector:
    """YOLO inference for real traffic. A lock protects the shared model."""
    def __init__(self, model_name=None):
        import torch
        from ultralytics import YOLO
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        # The larger model helps with dense motorcycles; retain the lightweight CPU fallback.
        gpu_model = Path(DEFAULT_YOLO_MODEL).with_name("yolov8s.pt")
        model_name = model_name or os.environ.get("ITS_YOLO_MODEL") or (str(gpu_model) if self.device == "cuda" and gpu_model.exists() else DEFAULT_YOLO_MODEL)
        self.model_name = str(model_name)
        self.model = YOLO(model_name)
        self.model.to(self.device)
        self.model.fuse(verbose=False)
        self.lock = Lock()
        from ultralytics.cfg import DEFAULT_CFG_DICT
        self.precision_args = ({"quantize": 16 if self.device == "cuda" else 32}
                               if "quantize" in DEFAULT_CFG_DICT else {"half": self.device == "cuda"})
        self.inference_size = 640

    def detect(self, frame, conf_threshold=DEFAULT_CONFIDENCE_THRESHOLD, target_classes=None, motorcycle_conf_threshold=0.20):
        classes = list(VEHICLE_CLASS_MAP) if target_classes is None else target_classes
        with self.lock:
            threshold = min(conf_threshold, motorcycle_conf_threshold) if 3 in classes else conf_threshold
            result = self.model(frame, verbose=False, conf=threshold, classes=classes, iou=0.5,
                                imgsz=getattr(self, "inference_size", 640), **getattr(self, "precision_args", {}))[0]
            detections = []
            if result.boxes is not None:
                for box, conf, cls in zip(result.boxes.xyxy.cpu().tolist(),
                                          result.boxes.conf.cpu().tolist(),
                                          result.boxes.cls.cpu().tolist()):
                    required = motorcycle_conf_threshold if int(cls) == 3 else conf_threshold
                    if conf >= required:
                        detections.append(make_detection(box, conf, int(cls)))
            return detections


def make_detection(box, confidence, class_id):
    x1, y1, x2, y2 = map(float, box)
    return {"bbox": [x1, y1, x2, y2], "conf": float(confidence),
            "class_id": class_id, "class_name": VEHICLE_CLASS_MAP[class_id],
            "bottom_center": ((x1+x2)/2, y2)}


class DemoVehicleDetector:
    """Colored rectangles from sample_generator only; never used as a YOLO fallback."""
    def detect(self, frame, conf_threshold=0.35, target_classes=None, motorcycle_conf_threshold=0.20):
        classes = list(VEHICLE_CLASS_MAP) if target_classes is None else target_classes
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, (0, 90, 140), (179, 255, 255))
        detections = []
        for contour in cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
            x, y, w, h = cv2.boundingRect(contour)
            if 25 <= w <= 90 and 15 <= h <= 140 and cv2.contourArea(contour) >= 400:
                cls = 7 if w >= 67 else (3 if w < 45 else 2)
                if cls in classes and (motorcycle_conf_threshold if cls == 3 else conf_threshold) <= 0.85:
                    detections.append(make_detection((x, y, x+w, y+h), 0.85, cls))
        return detections
