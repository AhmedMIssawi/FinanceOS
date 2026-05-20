"""Tests for core/money.py — the most critical correctness code in the app."""
from decimal import Decimal

import pytest

from core.money import ZERO, format_cad, to_money


def test_to_money_from_string():
    assert to_money("19.99") == Decimal("19.99")


def test_to_money_from_int():
    assert to_money(5) == Decimal("5.00")


def test_to_money_from_decimal():
    assert to_money(Decimal("3.14159")) == Decimal("3.14")


def test_to_money_rejects_float():
    with pytest.raises(TypeError):
        to_money(19.99)


def test_to_money_bankers_rounding_down():
    # 0.125 rounds to 0.12 (round-half-to-even, 2 is even)
    assert to_money("0.125") == Decimal("0.12")


def test_to_money_bankers_rounding_up():
    # 0.135 rounds to 0.14 (round-half-to-even, 4 is even)
    assert to_money("0.135") == Decimal("0.14")


def test_decimal_addition_is_exact():
    # The classic float trap: 0.1 + 0.2 != 0.3 in IEEE-754.
    # Decimal does it right.
    total = to_money("0.10") + to_money("0.20")
    assert total == Decimal("0.30")


def test_zero_constant():
    assert ZERO == Decimal("0.00")


def test_format_cad_positive():
    assert format_cad(to_money("1234.5")) == "$1,234.50"


def test_format_cad_negative():
    assert format_cad(to_money("-1234.56")) == "-$1,234.56"


def test_format_cad_zero():
    assert format_cad(ZERO) == "$0.00"


def test_format_cad_large():
    assert format_cad(to_money("1234567.89")) == "$1,234,567.89"


def test_format_cad_under_one_dollar():
    assert format_cad(to_money("0.05")) == "$0.05"


# --- Multi-currency formatting --------------------------------------------


def test_format_money_with_cad():
    from core.money import format_money
    assert format_money(to_money("1234.56"), "CAD") == "$1,234.56"


def test_format_money_with_usd():
    from core.money import format_money
    assert format_money(to_money("1234.56"), "USD") == "$1,234.56"


def test_format_money_with_eur():
    from core.money import format_money
    assert format_money(to_money("1234.56"), "EUR") == "€1,234.56"


def test_format_money_with_egp():
    from core.money import format_money
    assert format_money(to_money("1234.56"), "EGP") == "E£1,234.56"


def test_format_money_negative_with_egp():
    from core.money import format_money
    assert format_money(to_money("-50.25"), "EGP") == "-E£50.25"


def test_format_money_uses_active_currency_when_no_code_passed():
    from core.money import format_money, set_active_currency
    set_active_currency("EUR")
    assert format_money(to_money("100")) == "€100.00"
    # Restore default to not pollute other tests
    set_active_currency("CAD")


def test_set_active_currency_ignores_unknown():
    from core.money import active_currency_code, set_active_currency
    set_active_currency("CAD")
    set_active_currency("XYZ")  # unsupported — should silently skip
    assert active_currency_code() == "CAD"


def test_format_cad_alias_uses_active_currency():
    # format_cad is a backwards-compatible alias for format_money — it
    # should reflect whatever currency is currently active, not literal CAD.
    from core.money import set_active_currency
    set_active_currency("EUR")
    assert format_cad(to_money("100")) == "€100.00"
    set_active_currency("CAD")
    assert format_cad(to_money("100")) == "$100.00"
