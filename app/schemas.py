from datetime import UTC, datetime
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StrictInt,
    field_validator,
    model_validator,
)

from app.money import UnknownPromoCode, calculate_amount

PaymentMethod = Literal["card", "sbp", "installment"]
PaymentStatus = Literal["pending", "succeeded", "failed", "refunded"]
PositiveInt = Annotated[int, Field(strict=True, gt=0)]
NonnegativeInt = Annotated[int, Field(strict=True, ge=0)]


class PaymentCreate(BaseModel):
    tariff_id: PositiveInt
    email: EmailStr
    method: PaymentMethod
    installment_months: StrictInt | None = None
    promo_code: str | None = None

    @field_validator("installment_months")
    @classmethod
    def validate_months(cls, value: int | None) -> int | None:
        if value is not None and value not in (3, 6, 12):
            raise ValueError("Installment months must be 3, 6 or 12")
        return value

    @field_validator("promo_code")
    @classmethod
    def validate_promo(cls, value: str | None) -> str | None:
        try:
            # A nominal price checks the code without looking up a tariff.
            calculate_amount(10, value)
        except UnknownPromoCode as error:
            raise ValueError(str(error)) from error
        return value

    @model_validator(mode="after")
    def validate_method_and_months(self) -> Self:
        if self.method == "installment" and self.installment_months is None:
            raise ValueError("Installment payment requires installment_months")
        if self.method != "installment" and self.installment_months is not None:
            raise ValueError("Only installment payment accepts installment_months")
        return self


class PaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: PositiveInt
    status: PaymentStatus
    tariff_id: PositiveInt
    amount: PositiveInt
    discount: NonnegativeInt
    method: PaymentMethod
    installment_months: StrictInt | None
    schedule: list[StrictInt] | None
    email: EmailStr
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def normalize_utc(cls, value: datetime) -> datetime:
        # SQLite's naive timestamps represent UTC by the storage convention.
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class BankWebhook(BaseModel):
    payment_id: PositiveInt
    status: PaymentStatus
