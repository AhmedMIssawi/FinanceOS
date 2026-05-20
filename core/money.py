"""Decimal-based money helpers with multi-currency display.

Financial calculations must never use float. Every monetary value flows
through `to_money()`, which constructs Decimal from strings (never from
floats) and quantizes to 2 decimal places using banker's rounding
(ROUND_HALF_EVEN).

`format_money()` renders Decimals with the active currency's symbol.
The active currency is a module-level variable synced from the user's
setting at app startup (see core/db.py init_db).

NOTE: switching currency does NOT convert amounts via exchange rates —
the stored Decimal is unchanged, only the displayed symbol/code changes.
For real multi-currency tracking the user should run separate FinanceOS
instances per currency (copy the folder, reset the second one's data).
"""
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Union

_QUANTUM = Decimal("0.01")

MoneyInput = Union[str, int, Decimal]

# Supported currencies. Add new ones here — symbol is what appears before
# the amount in `format_money()`; name is the display label in Settings.
CURRENCIES: dict[str, dict[str, str]] = {
    "CAD": {"symbol": "$",  "name": "Canadian Dollar"},
    "USD": {"symbol": "$",  "name": "US Dollar"},
    "EUR": {"symbol": "€",  "name": "Euro"},
    "EGP": {"symbol": "E£", "name": "Egyptian Pound"},
}

# Active currency code; mutated by `set_active_currency()` which is called
# from init_db (and from the Settings page when the user changes it).
_active_currency_code: str = "CAD"


def set_active_currency(code: str) -> None:
    global _active_currency_code
    if code in CURRENCIES:
        _active_currency_code = code


def active_currency_code() -> str:
    return _active_currency_code


def active_currency_symbol() -> str:
    return CURRENCIES[_active_currency_code]["symbol"]


def to_money(value: MoneyInput) -> Decimal:
    """Convert input to a 2-dp Decimal using banker's rounding."""
    if isinstance(value, float):
        raise TypeError(
            "Refusing to convert float to money. Pass a string instead "
            "(e.g. to_money('19.99'), not to_money(19.99))."
        )
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return d.quantize(_QUANTUM, rounding=ROUND_HALF_EVEN)


ZERO: Decimal = to_money("0")


def format_money(amount: Decimal, currency_code: str | None = None) -> str:
    """Format a Decimal with the given currency's symbol.

    If `currency_code` is None, uses the currently active currency
    (set via Settings). Locale-independent thousands grouping with
    commas so output is stable regardless of Windows regional settings.
    """
    code = currency_code or _active_currency_code
    spec = CURRENCIES.get(code, CURRENCIES["CAD"])
    amount = to_money(amount)
    sign = "-" if amount < ZERO else ""
    whole, _, frac = f"{abs(amount):.2f}".partition(".")
    grouped = f"{int(whole):,}"
    return f"{sign}{spec['symbol']}{grouped}.{frac}"


# Backwards-compatible alias — older code that hasn't been migrated still works.
def format_cad(amount: Decimal) -> str:
    return format_money(amount)
