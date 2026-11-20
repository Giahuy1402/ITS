import os
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.models import AnalysisSession, VehicleRecord
from backend.app.schemas import SessionStatusResponse

router = APIRouter(prefix="/api/reports", tags=["reports"])

@router.get("/sessions", response_model=list[SessionStatusResponse])
def get_all_sessions(db: Session = Depends(get_db)):
    return db.query(AnalysisSession).order_by(AnalysisSession.created_at.desc()).all()

@router.get("/sessions/{session_id}/csv")
def download_session_csv(session_id: int, db: Session = Depends(get_db)):
    session_obj = db.query(AnalysisSession).filter(AnalysisSession.id == session_id).first()
    if not session_obj or not session_obj.csv_report_path:
        raise HTTPException(status_code=404, detail="Không tìm thấy file Báo cáo CSV cho phiên phân tích này.")

    path = Path(session_obj.csv_report_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="File Báo cáo CSV không tồn tại trên hệ thống.")

    return FileResponse(
        path=path,
        media_type="text/csv",
        filename=f"TrafficVision_Report_Session_{session_id}.csv"
    )

@router.get("/sessions/{session_id}/video")
def download_session_video(session_id: int, db: Session = Depends(get_db)):
    session_obj = db.query(AnalysisSession).filter(AnalysisSession.id == session_id).first()
    if not session_obj or not session_obj.annotated_video_path:
        raise HTTPException(status_code=404, detail="Không tìm thấy file Video kết quả cho phiên phân tích này.")

    path = Path(session_obj.annotated_video_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="File Video kết quả không tồn tại trên hệ thống.")

    return FileResponse(
        path=path,
        media_type="video/mp4",
        filename=f"TrafficVision_Annotated_Session_{session_id}.mp4"
    )
