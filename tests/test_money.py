import pytest

from app.money import (
    InvalidInstallmentMonths,
    UnknownPromoCode,
    build_schedule,
    calculate_amount,
)

TARIFF_CASES = [
    (990000, 891000, 99000),
    (1990000, 1791000, 199000),
    (2990000, 2691000, 299000),
]


@pytest.mark.parametrize("price", [990000, 1990000, 2990000])
def test_without_promo(price: int) -> None:
    assert calculate_amount(price) == (price, 0)


@pytest.mark.parametrize("price,amount,discount", TARIFF_CASES)
@pytest.mark.parametrize("code", ["KVITTO10", "kvitto10", "KvItTo10"])
def test_promo(price: int, amount: int, discount: int, code: str) -> None:
    assert calculate_amount(price, code) == (amount, discount)


@pytest.mark.parametrize("code", ["UNKNOWN", "", " KVITTO10 "])
def test_invalid_promo(code: str) -> None:
    with pytest.raises(UnknownPromoCode, match="Unknown promo code"):
        calculate_amount(1990000, code)


@pytest.mark.parametrize("price", [990000, 1990000, 2990000])
@pytest.mark.parametrize("code", [None, "KVITTO10"])
@pytest.mark.parametrize("months", [3, 6, 12])
def test_schedule(price: int, code: str | None, months: int) -> None:
    amount, _ = calculate_amount(price, code)
    schedule = build_schedule(amount, months)
    assert len(schedule) == months
    assert sum(schedule) == amount
    assert all(type(value) is int for value in schedule)
    assert max(schedule) - min(schedule) <= 1
    assert schedule == sorted(schedule, reverse=True)


def test_standard_example() -> None:
    assert build_schedule(1990000, 3) == [663334, 663333, 663333]


def test_discount_rounds_down_for_other_prices() -> None:
    assert calculate_amount(101, "KVITTO10") == (91, 10)


@pytest.mark.parametrize("months", [0, -1, 1, 2, 4, 5, 7, 24, None, 3.0, True])
def test_invalid_months(months) -> None:
    with pytest.raises(InvalidInstallmentMonths):
        build_schedule(1990000, months)


@pytest.mark.parametrize("value", [0, -1, 100.0, True, "100"])
def test_invalid_money(value) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        calculate_amount(value)
    with pytest.raises(ValueError, match="positive integer"):
        build_schedule(value, 3)
