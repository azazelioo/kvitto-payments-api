import hashlib
import hmac
import re
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Payment
from app.schemas import BankWebhook

router = APIRouter()
ALLOWED_TRANSITIONS = {
    ("pending", "succeeded"),
    ("pending", "failed"),
    ("succeeded", "refunded"),
}


class PaymentNotFound(ValueError):
    pass


class InvalidTransition(ValueError):
    pass


def can_transition(source: str, target: str) -> bool:
    return (source, target) in ALLOWED_TRANSITIONS


def update_payment_status(session: Session, payment_id: int, target: str) -> None:
    try:
        payment = session.get(Payment, payment_id)
        if payment is None:
            raise PaymentNotFound("Payment not found")
        source = payment.status
        if not can_transition(source, target):
            raise InvalidTransition("Invalid payment status transition")
        result = session.execute(
            update(Payment)
            .where(Payment.id == payment_id, Payment.status == source)
            .values(status=target)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            raise InvalidTransition("Payment status changed concurrently")
        session.commit()
    except (SQLAlchemyError, PaymentNotFound, InvalidTransition):
        session.rollback()
        raise


async def verify_signature(
    request: Request,
    signature: Annotated[str | None, Header(alias="X-Signature")] = None,
) -> None:
    secret = request.app.state.webhook_secret
    if not secret:
        return
    if signature is None or re.fullmatch(r"[0-9a-fA-F]{64}", signature) is None:
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    expected = hmac.new(
        secret.encode("utf-8"), await request.body(), hashlib.sha256
    ).digest()
    if not hmac.compare_digest(expected, bytes.fromhex(signature)):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")


@router.post(
    "/webhooks/bank", response_model=None, dependencies=[Depends(verify_signature)]
)
def bank_webhook(
    data: BankWebhook, session: Annotated[Session, Depends(get_session)]
) -> dict[str, str] | JSONResponse:
    try:
        update_payment_status(session, data.payment_id, data.status)
    except PaymentNotFound as error:
        raise HTTPException(status_code=404, detail="Payment not found") from error
    except InvalidTransition:
        return JSONResponse(status_code=409, content={"error": "invalid_transition"})
    return {"result": "ok"}
