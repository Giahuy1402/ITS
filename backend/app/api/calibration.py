import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from backend.app.database import get_db
from backend.app.models import CalibrationPreset
from backend.app.schemas import CalibrationPresetResponse

router = APIRouter(prefix="/api/calibration", tags=["calibration"])

class PresetCreate(BaseModel):
    name: str
    description: str = ""
    config: dict

@router.post("", response_model=CalibrationPresetResponse)
def create_preset(preset_in: PresetCreate, db: Session = Depends(get_db)):
    preset = CalibrationPreset(
        name=preset_in.name,
        description=preset_in.description,
        config_json=json.dumps(preset_in.config)
    )
    db.add(preset)
    db.commit()
    db.refresh(preset)
    return preset

@router.get("", response_model=list[CalibrationPresetResponse])
def list_presets(db: Session = Depends(get_db)):
    return db.query(CalibrationPreset).order_by(CalibrationPreset.created_at.desc()).all()

@router.delete("/{preset_id}")
def delete_preset(preset_id: int, db: Session = Depends(get_db)):
    preset = db.query(CalibrationPreset).filter(CalibrationPreset.id == preset_id).first()
    if not preset:
        raise HTTPException(status_code=404, detail="Không tìm thấy cấu hình hiệu chỉnh.")
    db.delete(preset)
    db.commit()
    return {"message": "Đã xóa cấu hình hiệu chỉnh thành công."}
