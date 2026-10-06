from fastapi.testclient import TestClient

from app.main import create_app


def test_openapi(database_url: str) -> None:
    with TestClient(create_app(database_url)) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert "openapi" in schema
    assert schema["info"]["title"] == "Kvitto Payments API"
