import json
from datetime import UTC, datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.models import Payment
from app.schemas import PaymentCreate, PaymentResponse


def payload(**updates) -> dict:
    return {"tariff_id": 1, "email": "student@example.com", "method": "card", **updates}


@pytest.mark.parametrize("method", ["card", "sbp"])
@pytest.mark.parametrize("months", [{}, {"installment_months": None}])
def test_noninstallment(method: str, months: dict) -> None:
    value = PaymentCreate.model_validate(payload(method=method, **months))
    assert value.installment_months is None
    assert value.promo_code is None


@pytest.mark.parametrize("months", [3, 6, 12])
def test_installment(months: int) -> None:
    value = PaymentCreate.model_validate(
        payload(method="installment", installment_months=months)
    )
    assert value.installment_months == months


@pytest.mark.parametrize(
    "updates",
    [
        {"method": "installment"},
        {"method": "installment", "installment_months": None},
        {"method": "installment", "installment_months": 4},
        {"method": "installment", "installment_months": 0},
        {"method": "card", "installment_months": 3},
        {"method": "sbp", "installment_months": 6},
        {"email": "bad"},
        {"method": "cash"},
    ],
)
def test_invalid_request(updates: dict) -> None:
    with pytest.raises(ValidationError):
        PaymentCreate.model_validate(payload(**updates))


@pytest.mark.parametrize("code", [None, "KVITTO10", "kvitto10", "KvItTo10"])
def test_promo(code: str | None) -> None:
    assert PaymentCreate.model_validate(payload(promo_code=code)).promo_code == code


@pytest.mark.parametrize("code", ["", "UNKNOWN", " KVITTO10", "KVITTO10 ", "KVIT TO10"])
def test_invalid_promo(code: str) -> None:
    with pytest.raises(ValidationError, match="Unknown promo code"):
        PaymentCreate.model_validate(payload(promo_code=code))


@pytest.mark.parametrize("value", [True, False, 1.5, 1.0, "1", 0, -1, None])
def test_invalid_id(value) -> None:
    with pytest.raises(ValidationError):
        PaymentCreate.model_validate(payload(tariff_id=value))


@pytest.mark.parametrize("value", [True, False, 3.5, 3.0, "3"])
def test_invalid_month_type(value) -> None:
    with pytest.raises(ValidationError):
        PaymentCreate.model_validate(
            payload(method="installment", installment_months=value)
        )


def response_values(**updates) -> dict:
    return dict(
        id=1,
        status="pending",
        tariff_id=1,
        amount=100,
        discount=0,
        method="installment",
        installment_months=3,
        schedule=[34, 33, 33],
        email="student@example.com",
        created_at=datetime(2026, 10, 6, 12),
        **updates,
    )


@pytest.mark.parametrize(
    "created_at",
    [
        datetime(2026, 10, 6, 12),
        datetime(2026, 10, 6, 12, tzinfo=UTC),
        datetime(2026, 10, 6, 15, tzinfo=timezone(timedelta(hours=3))),
    ],
)
def test_response_orm_and_utc(created_at: datetime) -> None:
    values = response_values()
    values["created_at"] = created_at
    model = Payment(**values, idempotency_key="private-key")
    response = PaymentResponse.model_validate(model)
    data = json.loads(response.model_dump_json())
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
    assert data["created_at"] == "2026-10-06T12:00:00Z"
    assert data["schedule"] == [34, 33, 33]
    assert type(data["amount"]) is int
    assert type(data["discount"]) is int
    assert all(type(item) is int for item in data["schedule"])
    assert model.created_at == created_at


@pytest.mark.parametrize(
    "updates",
    [
        {"amount": 100.0},
        {"amount": True},
        {"discount": 0.0},
        {"schedule": [34, 33.0, 33]},
        {"schedule": [True, 33, 33]},
    ],
)
def test_response_rejects_noninteger_money(updates: dict) -> None:
    values = response_values()
    values.update(updates)
    with pytest.raises(ValidationError):
        PaymentResponse.model_validate(values)


def test_response_nullable_fields() -> None:
    values = response_values()
    values.update(method="card", installment_months=None, schedule=None)
    data = PaymentResponse.model_validate(values).model_dump(mode="json")
    assert data["schedule"] is None
    assert data["installment_months"] is None


def test_standard_http_validation_error() -> None:
    application = FastAPI()

    @application.post("/validate")
    def validate(body: PaymentCreate) -> dict:
        return body.model_dump()

    with TestClient(application) as client:
        response = client.post("/validate", json=payload(promo_code="UNKNOWN"))
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail[0]["loc"] == ["body", "promo_code"]
    assert detail[0]["type"] == "value_error"
