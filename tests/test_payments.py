from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import create_app
from app.models import Payment


@pytest.mark.parametrize(
    "method,months",
    [
        ("card", None),
        ("sbp", None),
        ("installment", 3),
        ("installment", 6),
        ("installment", 12),
    ],
)
@pytest.mark.parametrize("promo", [None, "KVITTO10", "kvitto10"])
def test_create_and_get(database_url: str, method: str, months: int | None, promo):
    application = create_app(database_url)
    with TestClient(application) as client:
        tariff = next(
            t for t in client.get("/tariffs").json() if t["title"] == "standard"
        )
        before = datetime.now(UTC)
        response = client.post(
            "/payments",
            json={
                "tariff_id": tariff["id"],
                "email": "student@example.com",
                "method": method,
                "installment_months": months,
                "promo_code": promo,
            },
        )
        after = datetime.now(UTC)
        assert response.status_code == 201
        data = response.json()
        assert set(data) == {
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
        expected_amount = 1990000 if promo is None else 1791000
        expected_discount = 0 if promo is None else 199000
        expected_schedules = {
            1990000: {
                3: [663334, 663333, 663333],
                6: [331667, 331667, 331667, 331667, 331666, 331666],
                12: [165834] * 4 + [165833] * 8,
            },
            1791000: {3: [597000] * 3, 6: [298500] * 6, 12: [149250] * 12},
        }
        expected_schedule = (
            None if months is None else expected_schedules[expected_amount][months]
        )
        assert data["amount"] == expected_amount
        assert data["discount"] == expected_discount
        assert type(data["amount"]) is int
        assert type(data["discount"]) is int
        assert data["schedule"] == expected_schedule
        assert data["status"] == "pending"
        assert data["tariff_id"] == tariff["id"]
        assert data["method"] == method
        assert data["installment_months"] == months
        assert data["email"] == "student@example.com"
        assert data["created_at"].endswith("Z")
        created_at = datetime.fromisoformat(data["created_at"])
        assert before <= created_at <= after
        with application.state.session_factory() as session:
            rows = session.scalars(select(Payment)).all()
            assert len(rows) == 1
            saved = rows[0]
            for field in (
                "id",
                "status",
                "tariff_id",
                "amount",
                "discount",
                "method",
                "installment_months",
                "schedule",
                "email",
            ):
                assert getattr(saved, field) == data[field]
            assert saved.created_at.replace(tzinfo=UTC) == created_at
            assert saved.idempotency_key is None
        fetched = client.get(f"/payments/{data['id']}")
        assert fetched.status_code == 200
        assert fetched.json() == data


def test_missing_payment(database_url: str) -> None:
    with TestClient(create_app(database_url)) as client:
        assert client.get("/payments/999999").status_code == 404


@pytest.mark.parametrize(
    "changes",
    [
        {"tariff_id": 999999},
        {"tariff_id": True},
        {"tariff_id": 1.5},
        {"email": "invalid"},
        {"method": "cash"},
        {"method": "installment"},
        {"method": "installment", "installment_months": 4},
        {"method": "installment", "installment_months": 3.0},
        {"installment_months": 3},
        {"promo_code": "UNKNOWN"},
        {"promo_code": ""},
    ],
)
def test_invalid_request_does_not_insert(database_url: str, changes: dict) -> None:
    application = create_app(database_url)
    with TestClient(application) as client:
        tariff = client.get("/tariffs").json()[0]
        payload = {
            "tariff_id": tariff["id"],
            "email": "student@example.com",
            "method": "card",
            **changes,
        }
        response = client.post("/payments", json=payload)
        assert response.status_code == 422
        assert isinstance(response.json()["detail"], list)
        if changes == {"tariff_id": 999999}:
            assert response.json()["detail"][0]["loc"] == ["body", "tariff_id"]
        with application.state.session_factory() as session:
            assert session.scalars(select(Payment)).all() == []
