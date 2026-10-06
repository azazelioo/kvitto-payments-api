class UnknownPromoCode(ValueError):
    """The supplied promo code is not supported."""


class InvalidInstallmentMonths(ValueError):
    """Installment duration must be 3, 6 or 12 whole months."""


def calculate_amount(price: int, promo_code: str | None = None) -> tuple[int, int]:
    """Return (amount, discount) in kopecks.

    For other prices, price // 10 rounds the discount down to a whole kopeck.
    """
    if type(price) is not int or price <= 0:
        raise ValueError("Price must be a positive integer in kopecks")
    if promo_code is None:
        discount = 0
    elif isinstance(promo_code, str) and promo_code.upper() == "KVITTO10":
        discount = price // 10
    else:
        raise UnknownPromoCode("Unknown promo code; only KVITTO10 is supported")
    return price - discount, discount


def build_schedule(amount: int, months: int) -> list[int]:
    """Split kopecks evenly, assigning the remainder to the first payments."""
    if type(amount) is not int or amount <= 0:
        raise ValueError("Amount must be a positive integer in kopecks")
    if type(months) is not int or months not in (3, 6, 12):
        raise InvalidInstallmentMonths("Installment months must be 3, 6 or 12")
    base, remainder = divmod(amount, months)
    return [base + 1] * remainder + [base] * (months - remainder)
