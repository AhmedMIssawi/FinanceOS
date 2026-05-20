"""Tests for core/settings_service.py."""
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core import models  # noqa: F401
from core.db import Base
from core.settings_service import (
    DEFAULT_SAVINGS_TARGET,
    get_savings_target,
    get_setting,
    set_savings_target,
    set_setting,
)
from core.money import to_money


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Local = sessionmaker(bind=engine, future=True)
    with Local() as s:
        yield s


def test_get_setting_returns_default_when_missing(session):
    assert get_setting(session, "missing_key", "fallback") == "fallback"


def test_get_setting_returns_value_when_present(session):
    set_setting(session, "theme", "dark")
    assert get_setting(session, "theme") == "dark"


def test_set_setting_updates_existing(session):
    set_setting(session, "theme", "dark")
    set_setting(session, "theme", "light")
    assert get_setting(session, "theme") == "light"


def test_savings_target_default(session):
    assert get_savings_target(session) == DEFAULT_SAVINGS_TARGET


def test_savings_target_persists(session):
    set_savings_target(session, to_money("25000"))
    assert get_savings_target(session) == to_money("25000")


def test_savings_target_update(session):
    set_savings_target(session, to_money("15000"))
    set_savings_target(session, to_money("30000"))
    assert get_savings_target(session) == to_money("30000")


# --- Currency settings -----------------------------------------------------


def test_currency_default_is_cad(session):
    from core.settings_service import get_currency_code
    assert get_currency_code(session) == "CAD"


def test_currency_persists(session):
    from core.settings_service import get_currency_code, set_currency_code
    set_currency_code(session, "EGP")
    assert get_currency_code(session) == "EGP"


def test_currency_can_change(session):
    from core.settings_service import get_currency_code, set_currency_code
    set_currency_code(session, "EUR")
    set_currency_code(session, "USD")
    assert get_currency_code(session) == "USD"


def test_currency_invalid_raises(session):
    import pytest as _pytest
    from core.settings_service import set_currency_code
    with _pytest.raises(ValueError):
        set_currency_code(session, "XYZ")


def test_currency_invalid_in_db_falls_back_to_default(session):
    from core.settings_service import get_currency_code, set_setting
    # Simulate corruption: a value that's not a valid currency code.
    set_setting(session, "currency_code", "JPY")
    assert get_currency_code(session) == "CAD"


# --- Developer password ----------------------------------------------------


def test_dev_password_default(session):
    from core.settings_service import get_dev_password
    assert get_dev_password(session) == "0000"


def test_dev_password_persists(session):
    from core.settings_service import get_dev_password, set_dev_password
    set_dev_password(session, "9876")
    assert get_dev_password(session) == "9876"


def test_dev_password_empty_raises(session):
    import pytest as _pytest
    from core.settings_service import set_dev_password
    with _pytest.raises(ValueError):
        set_dev_password(session, "")
