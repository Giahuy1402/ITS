import os
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.app.database import init_db
from backend.app.config import UPLOADS_DIR, OUTPUTS_DIR, BASE_DIR
from backend.app.api.videos import router as videos_router
from backend.app.api.sessions import router as sessions_router
from backend.app.api.calibration import router as calibration_router
from backend.app.api.reports import router as reports_router

@asynccontextmanager
async def lifespan(app):
    init_db()
    from backend.app.database import SessionLocal
    from backend.app.models import AnalysisSession
    from datetime import datetime, timezone
    with SessionLocal() as db:
        for session in db.query(AnalysisSession).filter(AnalysisSession.status.in_(["pending", "processing"])):
            session.status = "failed"
            session.error_message = "Máy chủ đã khởi động lại. Bạn có thể chạy lại phiên này."
            session.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
    # Avoid a first-upload pause while the detector model is being loaded.
    try:
        from backend.app.core.video_processor import get_detector
        await asyncio.to_thread(get_detector)
    except Exception:
        logging.getLogger(__name__).exception("Could not warm up the vehicle detector")
    yield


app = FastAPI(
    lifespan=lifespan,
    title="TrafficVision AI Backend",
    description="Hệ thống phân tích video giao thông thông minh: nhận diện, đếm xe, đo tốc độ và nhận biết ùn tắc.",
    version="1.0.0"
)

# CORS Middleware setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health check endpoint
@app.get("/api/health")
def health_check():
    return {
        "status": "online",
        "service": "TrafficVision AI Backend",
        "system": "Operational"
    }

# Include API routers
app.include_router(videos_router)
app.include_router(sessions_router)
app.include_router(calibration_router)
app.include_router(reports_router)

# Mount uploaded files and output files static directories
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")
app.mount("/outputs", StaticFiles(directory=str(OUTPUTS_DIR)), name="outputs")

# Mount frontend static directory if exists
frontend_dir = BASE_DIR / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
