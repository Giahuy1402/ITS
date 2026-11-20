import json
import asyncio
from collections import OrderedDict, deque
from typing import Dict, Set
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.models import AnalysisSession, Video, VehicleRecord, CongestionLog
from backend.app.schemas import SessionStartConfig, SessionStatusResponse, SessionDetailResponse
from backend.app.core.video_processor import process_video_session, CANCEL_REQUESTS

router = APIRouter(prefix="/api/sessions", tags=["sessions"])

# Connection manager for WebSockets
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, Set[WebSocket]] = {}
        self.send_locks: Dict[WebSocket, asyncio.Lock] = {}
        # A session may start producing frames before the browser opens its
        # WebSocket. Keep a short replay window so the first visible frame has
        # detection data even when model inference is very fast.
        self.recent_tracks = OrderedDict()

    async def connect(self, session_id: int, websocket: WebSocket):
        await websocket.accept()
        lock = asyncio.Lock()
        self.send_locks[websocket] = lock
        if session_id not in self.active_connections:
            self.active_connections[session_id] = set()
        self.active_connections[session_id].add(websocket)
        async with lock:
            try:
                for message in self.recent_tracks.get(session_id, ()):
                    await websocket.send_json(message)
            except Exception:
                self.disconnect(session_id, websocket)

    def disconnect(self, session_id: int, websocket: WebSocket):
        self.send_locks.pop(websocket, None)
        if session_id in self.active_connections:
            self.active_connections[session_id].discard(websocket)
            if len(self.active_connections[session_id]) == 0:
                del self.active_connections[session_id]

    async def broadcast(self, session_id: int, message: dict):
        if message.get("kind") == "tracks":
            if session_id not in self.recent_tracks:
                self.recent_tracks[session_id] = deque(maxlen=120)
                if len(self.recent_tracks) > 16:
                    self.recent_tracks.popitem(last=False)
            self.recent_tracks[session_id].append(message)
        if session_id in self.active_connections:
            for connection in list(self.active_connections[session_id]):
                try:
                    async with self.send_locks[connection]:
                        await connection.send_json(message)
                except Exception:
                    self.disconnect(session_id, connection)

manager = ConnectionManager()

async def run_worker(session_id):
    # Capture the ASGI loop before entering the worker thread.
    loop = asyncio.get_running_loop()
    pending = set()
    def broadcast(data):
        # Track metadata is small and ordered. Do not drop it, or boxes drift
        # from the source frame being played in the browser.
        future = asyncio.run_coroutine_threadsafe(manager.broadcast(session_id, data), loop)
        pending.add(future)
        future.add_done_callback(pending.discard)
    await asyncio.to_thread(process_video_session, session_id, broadcast)
    if pending:
        deliveries = [asyncio.wrap_future(future) for future in tuple(pending)]
        finished, unfinished = await asyncio.wait(deliveries, timeout=2)
        for delivery in unfinished:
            delivery.cancel()


@router.post("", response_model=SessionStatusResponse)
def create_and_start_session(
    config: SessionStartConfig,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    video_obj = db.query(Video).filter(Video.id == config.video_id).first()
    if not video_obj:
        raise HTTPException(status_code=404, detail="Không tìm thấy video được chỉ định.")

    session_obj = AnalysisSession(
        video_id=config.video_id,
        status="pending",
        config_json=json.dumps(config.model_dump()),
        total_frames=video_obj.total_frames
    )
    db.add(session_obj)
    db.commit()
    db.refresh(session_obj)

    # Trigger background worker thread
    background_tasks.add_task(run_worker, session_obj.id)

    return session_obj


@router.get("/{session_id}", response_model=SessionDetailResponse)
def get_session_details(session_id: int, since_frame: int | None = Query(default=None, ge=0), db: Session = Depends(get_db)):
    session_obj = db.query(AnalysisSession).filter(AnalysisSession.id == session_id).first()
    if not session_obj:
        raise HTTPException(status_code=404, detail="Không tìm thấy phiên phân tích.")

    records = db.query(VehicleRecord).filter(VehicleRecord.session_id == session_id).order_by(VehicleRecord.id.desc()).limit(100).all()
    logs_query = db.query(CongestionLog).filter(CongestionLog.session_id == session_id)
    if since_frame is not None:
        logs_query = logs_query.filter(CongestionLog.frame_idx > since_frame)
    c_logs = logs_query.order_by(CongestionLog.frame_idx.asc()).all()

    resp_dict = SessionStatusResponse.model_validate(session_obj).model_dump()
    resp_dict["config"] = json.loads(session_obj.config_json)
    resp_dict["recent_records"] = records
    resp_dict["congestion_timeline"] = c_logs

    return resp_dict


@router.post("/{session_id}/cancel")
def cancel_session(session_id: int, db: Session = Depends(get_db)):
    session_obj = db.query(AnalysisSession).filter(AnalysisSession.id == session_id).first()
    if not session_obj:
        raise HTTPException(status_code=404, detail="Không tìm thấy phiên phân tích.")

    if session_obj.status in {"pending", "processing"}:
        CANCEL_REQUESTS[session_id] = True
        session_obj.status = "cancelled"
        from datetime import datetime, timezone
        session_obj.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        session_obj.estimated_time_remaining_sec = 0
        db.commit()
        return {"message": "Đã gửi yêu cầu hủy phiên phân tích.", "session_id": session_id}
    else:
        return {"message": "Phiên phân tích không ở trạng thái đang xử lý.", "status": session_obj.status}


@router.post("/{session_id}/rerun", response_model=SessionStatusResponse)
def rerun_session(
    session_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    old_session = db.query(AnalysisSession).filter(AnalysisSession.id == session_id).first()
    if not old_session:
        raise HTTPException(status_code=404, detail="Không tìm thấy phiên phân tích để chạy lại.")

    new_session = AnalysisSession(
        video_id=old_session.video_id,
        status="pending",
        config_json=old_session.config_json,
        total_frames=old_session.total_frames
    )
    db.add(new_session)
    db.commit()
    db.refresh(new_session)

    background_tasks.add_task(run_worker, new_session.id)

    return new_session


@router.websocket("/ws/{session_id}")
async def websocket_session_progress(websocket: WebSocket, session_id: int):
    await manager.connect(session_id, websocket)
    try:
        while True:
            # Keep connection alive
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(session_id, websocket)
