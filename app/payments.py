import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from fastapi.exceptions import RequestValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Payment, Tariff
from app.money import build_schedule, calculate_amount
from app.schemas import PaymentCreate, PaymentResponse

router = APIRouter()


def create_payment(
    session: Session,
    data: PaymentCreate,
    tariff: Tariff,
    idempotency_key: str | None = None,
) -> Payment:
    amount, discount = calculate_amount(tariff.price, data.promo_code)
    schedule = None
    if data.method == "installment":
        # PaymentCreate guarantees the duration is present and valid.
        assert data.installment_months is not None
        schedule = build_schedule(amount, data.installment_months)
    payment = Payment(
        tariff_id=tariff.id,
        email=str(data.email),
        method=data.method,
        installment_months=data.installment_months,
        amount=amount,
        discount=discount,
        schedule=schedule,
        status="pending",
        idempotency_key=idempotency_key,
    )
    session.add(payment)
    try:
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise
    session.refresh(payment)
    return payment


def find_payment_by_key(session: Session, key: str) -> Payment | None:
    return session.scalar(select(Payment).where(Payment.idempotency_key == key))


def is_key_conflict(error: IntegrityError) -> bool:
    original = error.orig
    if isinstance(original, sqlite3.IntegrityError):
        return (
            original.sqlite_errorcode == sqlite3.SQLITE_CONSTRAINT_UNIQUE
            and str(original) == "UNIQUE constraint failed: payments.idempotency_key"
        )
    return (
        getattr(getattr(original, "diag", None), "constraint_name", None)
        == "uq_payments_idempotency_key"
    )


@router.post("/payments", status_code=201, response_model=PaymentResponse)
def post_payment(
    data: PaymentCreate,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Payment:
    if idempotency_key is not None:
        if not idempotency_key.strip():
            raise RequestValidationError(
                [
                    {
                        "type": "value_error",
                        "loc": ("header", "Idempotency-Key"),
                        "msg": "Value error, Idempotency-Key must not be blank",
                        "input": idempotency_key,
                    }
                ]
            )
        existing = find_payment_by_key(session, idempotency_key)
        if existing is not None:
            response.status_code = 200
            return existing
    tariff = session.get(Tariff, data.tariff_id)
    if tariff is None:
        raise RequestValidationError(
            [
                {
                    "type": "value_error",
                    "loc": ("body", "tariff_id"),
                    "msg": "Value error, Unknown tariff_id",
                    "input": data.tariff_id,
                }
            ]
        )
    try:
        return create_payment(session, data, tariff, idempotency_key)
    except IntegrityError as error:
        # create_payment has already rolled back the failed INSERT.
        if idempotency_key is None or not is_key_conflict(error):
            raise
        existing = find_payment_by_key(session, idempotency_key)
        if existing is None:
            raise
        response.status_code = 200
        return existing


@router.get("/payments/{id}", response_model=PaymentResponse)
def get_payment(id: int, session: Annotated[Session, Depends(get_session)]) -> Payment:
    payment = session.get(Payment, id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    return payment
