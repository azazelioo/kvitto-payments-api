from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utc_now() -> datetime:
    """Return UTC without tzinfo: SQLite stores naive UTC by convention."""
    return datetime.now(UTC).replace(tzinfo=None)


class Tariff(Base):
    __tablename__ = "tariffs"
    __table_args__ = (
        CheckConstraint("price > 0", name="ck_tariffs_price_positive"),
        UniqueConstraint("title", name="uq_tariffs_title"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    price: Mapped[int] = mapped_column(Integer, nullable=False)


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
        CheckConstraint("discount >= 0", name="ck_payments_discount_nonnegative"),
        CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed', 'refunded')",
            name="ck_payments_status_allowed",
        ),
        CheckConstraint(
            "method IN ('card', 'sbp', 'installment')",
            name="ck_payments_method_allowed",
        ),
        CheckConstraint(
            "(method = 'installment' AND installment_months IS NOT NULL "
            "AND installment_months IN (3, 6, 12)) "
            "OR (method IN ('card', 'sbp') AND installment_months IS NULL)",
            name="ck_payments_installment_months",
        ),
        UniqueConstraint("idempotency_key", name="uq_payments_idempotency_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tariff_id: Mapped[int] = mapped_column(
        ForeignKey("tariffs.id", name="fk_payments_tariff_id"), nullable=False
    )
    email: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    discount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    method: Mapped[str] = mapped_column(String, nullable=False)
    installment_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    schedule: Mapped[list[int] | None] = mapped_column(
        JSON(none_as_null=True), nullable=True
    )
    idempotency_key: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, default=utc_now
    )
