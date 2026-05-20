"""Tests for core/exchange_service.py.

Network-dependent API tests are intentionally NOT included — they'd flake
in CI and add no value for verifying the local storage/conversion logic.
The `fetch_rates_from_api` function is exercised manually via the
Settings page's 'Fetch latest from internet' button.
"""
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core import models  # noqa: F401
from core.db import Base
from core.exchange_service import (
    all_rates,
    convert,
    get_rate,
    set_rate,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Local = sessionmaker(bind=engine, future=True)
    with Local() as s:
        yield s


def test_get_rate_same_currency_returns_one(session):
    assert get_rate(session, "CAD", "CAD") == Decimal("1")


def test_get_rate_returns_none_when_unset(session):
    assert get_rate(session, "CAD", "EGP") is None


def test_set_and_get_rate_roundtrip(session):
    set_rate(session, "CAD", "EGP", Decimal("22.5"))
    assert get_rate(session, "CAD", "EGP") == Decimal("22.5")


def test_set_rate_overwrites_existing(session):
    set_rate(session, "CAD", "EGP", Decimal("22.5"))
    set_rate(session, "CAD", "EGP", Decimal("23.1"))
    assert get_rate(session, "CAD", "EGP") == Decimal("23.1")


def test_get_rate_derives_inverse(session):
    set_rate(session, "CAD", "EGP", Decimal("25"))
    inverse = get_rate(session, "EGP", "CAD")
    assert inverse == Decimal("1") / Decimal("25")


def test_set_rate_rejects_negative(session):
    with pytest.raises(ValueError, match="positive"):
        set_rate(session, "CAD", "EGP", Decimal("-1"))


def test_set_rate_rejects_zero(session):
    with pytest.raises(ValueError, match="positive"):
        set_rate(session, "CAD", "EGP", Decimal("0"))


def test_set_rate_rejects_same_currency(session):
    with pytest.raises(ValueError, match="differ"):
        set_rate(session, "CAD", "CAD", Decimal("1"))


def test_set_rate_rejects_unsupported_currency(session):
    with pytest.raises(ValueError, match="Unsupported"):
        set_rate(session, "JPY", "CAD", Decimal("0.01"))


def test_convert_uses_direct_rate(session):
    set_rate(session, "CAD", "EGP", Decimal("22.5"))
    result = convert(Decimal("100"), "CAD", "EGP", session)
    assert result == Decimal("100") * Decimal("22.5")


def test_convert_returns_none_when_no_rate(session):
    assert convert(Decimal("100"), "CAD", "USD", session) is None


def test_convert_same_currency_returns_amount(session):
    assert convert(Decimal("100"), "CAD", "CAD", session) == Decimal("100")


def test_all_rates_returns_stored_rows(session):
    set_rate(session, "CAD", "EGP", Decimal("22.5"))
    set_rate(session, "CAD", "USD", Decimal("0.73"))
    rates = all_rates(session)
    assert len(rates) == 2
    pairs = {(r.from_currency, r.to_currency) for r in rates}
    assert pairs == {("CAD", "EGP"), ("CAD", "USD")}


# --- Schedule / auto-update logic ----------------------------------------


def test_last_scheduled_slot_during_day():
    from datetime import datetime as _dt
    from core.exchange_service import SCHEDULED_HOURS, last_scheduled_slot
    # SCHEDULED_HOURS = (9, 13, 17, 21). At 14:30, the most recent past slot is 13:00.
    now = _dt(2026, 5, 18, 14, 30)
    expected = _dt(2026, 5, 18, 13, 0)
    assert last_scheduled_slot(now) == expected


def test_last_scheduled_slot_just_after_slot():
    from datetime import datetime as _dt
    from core.exchange_service import last_scheduled_slot
    # At 13:00 sharp, the 13:00 slot has "passed" (>= comparison).
    now = _dt(2026, 5, 18, 13, 0)
    expected = _dt(2026, 5, 18, 13, 0)
    assert last_scheduled_slot(now) == expected


def test_last_scheduled_slot_before_first_slot_today():
    from datetime import datetime as _dt
    from core.exchange_service import last_scheduled_slot
    # At 06:00, no slot has passed today — go to yesterday's last slot (21:00).
    now = _dt(2026, 5, 18, 6, 0)
    expected = _dt(2026, 5, 17, 21, 0)
    assert last_scheduled_slot(now) == expected


def test_last_scheduled_slot_late_evening():
    from datetime import datetime as _dt
    from core.exchange_service import last_scheduled_slot
    now = _dt(2026, 5, 18, 23, 45)
    expected = _dt(2026, 5, 18, 21, 0)
    assert last_scheduled_slot(now) == expected


def test_needs_update_when_no_rates_stored(session):
    from core.exchange_service import needs_update
    assert needs_update(session, "CAD") is True


def test_needs_update_when_rate_set_just_now_is_false(session):
    from core.exchange_service import needs_update
    set_rate(session, "CAD", "USD", Decimal("0.73"))
    # Fresh rate set right now — there's no scheduled slot between "now"
    # and "the rate's updated_at" since updated_at == now (approximately).
    assert needs_update(session, "CAD") is False


def test_needs_update_when_rate_is_old(session):
    from datetime import datetime as _dt, timedelta as _td
    from core.exchange_service import needs_update
    set_rate(session, "CAD", "USD", Decimal("0.73"))
    # Backdate the rate to 2 days ago.
    rates = all_rates(session)
    rates[0].updated_at = _dt.now() - _td(days=2)
    session.commit()
    assert needs_update(session, "CAD") is True
