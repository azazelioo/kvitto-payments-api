from pathlib import Path
from typing import Annotated
from unittest.mock import Mock, patch

from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import create_db_engine, create_session_factory, get_session
from app.main import create_app


def test_sqlite_connection(tmp_path: Path) -> None:
    database = tmp_path / "connection.db"
    engine = create_db_engine(f"sqlite:///{database}")
    assert not database.exists()
    try:
        with engine.connect() as connection:
            assert connection.execute(text("SELECT 1")).scalar_one() == 1
            assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        # A second simultaneous connection must get the same PRAGMA setting.
        with engine.connect() as first, engine.connect() as second:
            assert first.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
            assert second.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        with create_session_factory(engine)() as session:
            assert session.execute(text("SELECT 1")).scalar_one() == 1
    finally:
        engine.dispose()
    assert database.exists()


def test_request_sessions(tmp_path: Path) -> None:
    application = create_app(f"sqlite:///{tmp_path / 'requests.db'}")
    sessions: list[Session] = []

    @application.get("/session-check")
    def session_check(session: Annotated[Session, Depends(get_session)]) -> dict:
        sessions.append(session)
        return {"value": session.execute(text("SELECT 1")).scalar_one()}

    with TestClient(application) as client:
        closed: list[Session] = []
        original_close = Session.close

        def record_close(session: Session) -> None:
            closed.append(session)
            original_close(session)

        with patch.object(Session, "close", record_close):
            for _ in range(2):
                response = client.get("/session-check")
                assert response.status_code == 200
                assert response.json() == {"value": 1}
        assert sessions[0] is not sessions[1]
        assert closed == sessions


def test_lifespan_disposes_engine(tmp_path: Path, monkeypatch) -> None:
    database = tmp_path / "lifecycle.db"
    application = create_app(f"sqlite:///{database}")
    assert not hasattr(application.state, "engine")
    with TestClient(application):
        dispose = Mock(wraps=application.state.engine.dispose)
        monkeypatch.setattr(application.state.engine, "dispose", dispose)
        assert not database.exists()
    dispose.assert_called_once_with()


def test_database_url_from_environment(tmp_path: Path, monkeypatch) -> None:
    url = f"sqlite:///{tmp_path / 'environment.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    with TestClient(create_app()) as client:
        assert str(client.app.state.engine.url) == url
