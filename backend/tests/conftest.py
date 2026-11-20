import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.app.database import Base, get_db
from backend.app.main import app
from backend.app.api import videos
from backend.app.core import video_processor


@pytest.fixture
def api(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    factory = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    uploads = tmp_path / "uploads"
    outputs = tmp_path / "outputs"
    uploads.mkdir()
    outputs.mkdir()
    monkeypatch.setattr(videos, "UPLOADS_DIR", uploads)
    monkeypatch.setattr(video_processor, "OUTPUTS_DIR", outputs)
    monkeypatch.setattr(video_processor, "SessionLocal", factory)
    def database():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = database
    client = TestClient(app)  # Do not run the production database lifespan.
    yield client, factory, uploads, outputs
    client.close()
    app.dependency_overrides.clear()
    video_processor.CANCEL_REQUESTS.clear()
    engine.dispose()
