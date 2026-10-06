from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


def test_openapi(tmp_path: Path) -> None:
    with TestClient(create_app(f"sqlite:///{tmp_path / 'test.db'}")) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert "openapi" in schema
    assert schema["info"]["title"] == "Kvitto Payments API"
