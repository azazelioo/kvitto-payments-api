from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models import Payment


@pytest.fixture
def populated_client(database_url: str):
    application = create_app(database_url, webhook_secret="")
    with TestClient(application) as client:
        tariff_id = next(
            t["id"] for t in client.get("/tariffs").json() if t["title"] == "standard"
        )
        rows = []
        for email, status in (
            ("alice@example.com", "pending"),
            ("bob@example.com", "succeeded"),
            ("alice@example.com", "succeeded"),
            ("alice@example.com", "failed"),
            ("bob@example.com", "refunded"),
        ):
            response = client.post(
                "/payments",
                json={
                    "tariff_id": tariff_id,
                    "email": email,
                    "method": "installment",
                    "installment_months": 3,
                    "promo_code": "kvitto10",
                },
            )
            assert response.status_code == 201
            row = response.json()
            with application.state.session_factory() as session:
                session.get(Payment, row["id"]).status = status
                session.commit()
            rows.append({**row, "status": status})
        yield client, rows


def test_empty_database(database_url: str) -> None:
    with TestClient(create_app(database_url)) as client:
        response = client.get("/payments")
        assert response.status_code == 200
        assert response.json() == []


@pytest.mark.parametrize(
    "params,indexes",
    [
        ({}, [0, 1, 2, 3, 4]),
        ({"email": "alice@example.com"}, [0, 2, 3]),
        ({"email": "bob@example.com"}, [1, 4]),
        ({"status": "pending"}, [0]),
        ({"status": "succeeded"}, [1, 2]),
        ({"status": "failed"}, [3]),
        ({"status": "refunded"}, [4]),
        ({"email": "alice@example.com", "status": "succeeded"}, [2]),
        ({"email": "bob@example.com", "status": "pending"}, []),
        ({"email": "missing@example.com"}, []),
        ({"email": "Alice@example.com"}, []),
        ({"email": "ali@example.com"}, []),
    ],
)
def test_filters(populated_client, params: dict, indexes: list[int]) -> None:
    client, rows = populated_client
    response = client.get("/payments", params=params)
    assert response.status_code == 200
    assert response.json() == [rows[index] for index in indexes]
    assert client.get("/payments", params=params).json() == response.json()


def test_response_and_get_by_id(populated_client) -> None:
    client, expected = populated_client
    rows = client.get("/payments").json()
    assert rows == expected
    assert [row["id"] for row in rows] == sorted(row["id"] for row in rows)
    for row in rows:
        assert set(row) == {
            "id",
            "status",
            "tariff_id",
            "amount",
            "discount",
            "method",
            "installment_months",
            "schedule",
            "email",
            "created_at",
        }
        assert row["amount"] == 1791000 and type(row["amount"]) is int
        assert row["discount"] == 199000 and type(row["discount"]) is int
        assert row["schedule"] == [597000, 597000, 597000]
        assert all(type(value) is int for value in row["schedule"])
        assert row["created_at"].endswith("Z")
        assert (
            datetime.fromisoformat(row["created_at"]).utcoffset().total_seconds() == 0
        )
        response = client.get(f"/payments/{row['id']}")
        assert response.status_code == 200
        assert response.json() == row


@pytest.mark.parametrize(
    "params,field",
    [
        ({"email": "invalid"}, "email"),
        ({"email": ""}, "email"),
        ({"status": "unknown"}, "status"),
        ({"status": ""}, "status"),
        ({"status": "SUCCEEDED"}, "status"),
    ],
)
def test_invalid_filters(populated_client, params: dict, field: str) -> None:
    client, rows = populated_client
    response = client.get("/payments", params=params)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list)
    assert detail[0]["loc"] == ["query", field]
    assert client.get("/payments").json() == rows
