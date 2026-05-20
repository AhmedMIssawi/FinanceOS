"""Key-value settings store backed by the settings table.

Generic get/set, plus typed convenience helpers (e.g. savings_target as Decimal).
"""
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from core.models import Setting
from core.money import CURRENCIES, to_money

# Keys are namespaced strings. Add new keys here as constants so callers
# don't typo them.
KEY_SAVINGS_TARGET = "savings_target"
KEY_CURRENCY = "currency_code"
KEY_DEV_PASSWORD = "dev_password"

DEFAULT_SAVINGS_TARGET = Decimal("20000")
DEFAULT_CURRENCY = "CAD"
DEFAULT_DEV_PASSWORD = "0000"


def get_setting(
    session: Session, key: str, default: Optional[str] = None
) -> Optional[str]:
    row = session.get(Setting, key)
    return row.value if row else default


def set_setting(session: Session, key: str, value: str) -> None:
    row = session.get(Setting, key)
    if row:
        row.value = value
    else:
        session.add(Setting(key=key, value=value))
    session.commit()


def get_savings_target(session: Session) -> Decimal:
    """Yearly savings target. Defaults to $20,000 if never set."""
    raw = get_setting(session, KEY_SAVINGS_TARGET)
    if raw is None:
        return DEFAULT_SAVINGS_TARGET
    return to_money(raw)


def set_savings_target(session: Session, amount: Decimal) -> None:
    set_setting(session, KEY_SAVINGS_TARGET, str(to_money(amount)))


def get_currency_code(session: Session) -> str:
    """Active display currency code (USD/CAD/EUR/EGP). Defaults to CAD."""
    raw = get_setting(session, KEY_CURRENCY, DEFAULT_CURRENCY)
    if raw not in CURRENCIES:
        return DEFAULT_CURRENCY
    return raw


def set_currency_code(session: Session, code: str) -> None:
    """Persist the display currency. Raises ValueError if unsupported."""
    if code not in CURRENCIES:
        raise ValueError(
            f"Unsupported currency '{code}'. Supported: {list(CURRENCIES.keys())}"
        )
    set_setting(session, KEY_CURRENCY, code)


def get_dev_password(session: Session) -> str:
    """Developer-area password (gates DB-path display in Settings)."""
    return get_setting(session, KEY_DEV_PASSWORD, DEFAULT_DEV_PASSWORD) or DEFAULT_DEV_PASSWORD


def set_dev_password(session: Session, password: str) -> None:
    """Persist a new developer password. Raises ValueError if empty."""
    if not password:
        raise ValueError("Password can't be empty.")
    set_setting(session, KEY_DEV_PASSWORD, password)
