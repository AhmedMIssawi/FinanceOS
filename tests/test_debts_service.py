"""Tests for core/debts_service.py — payment detection on debt accounts."""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core import models  # noqa: F401
from core.db import Base
from core.debts_service import payment_history, payments_to_account
from core.models import Account
from core.money import ZERO, to_money
from core.transactions_service import add_transaction, add_transfer


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Local = sessionmaker(bind=engine, future=True)
    with Local() as s:
        yield s


@pytest.fixture
def chequing(session):
    a = Account(name="Chequing", type="chequing", balance=to_money("3000"))
    session.add(a)
    session.commit()
    return a


@pytest.fixture
def visa(session):
    a = Account(name="Visa", type="credit", balance=to_money("-500"))
    session.add(a)
    session.commit()
    return a


def test_payments_sums_incoming_transfers(session, chequing, visa):
    today = date.today()
    add_transfer(
        session,
        from_account_id=chequing.id,
        to_account_id=visa.id,
        date=today,
        amount=to_money("200"),
    )
    assert payments_to_account(session, visa.id, today.year, today.month) == to_money(
        "200.00"
    )


def test_payments_excludes_other_months(session, chequing, visa):
    add_transfer(
        session,
        from_account_id=chequing.id,
        to_account_id=visa.id,
        date=date(2025, 12, 1),
        amount=to_money("100"),
    )
    assert payments_to_account(session, visa.id, 2026, 1) == ZERO


def test_payments_excludes_expenses_on_account(session, visa):
    # Charging the card creates an expense (negative amount), NOT a payment.
    add_transaction(
        session,
        account_id=visa.id,
        date=date(2026, 5, 15),
        magnitude=to_money("50"),
        category="Food",
        subcategory="Groceries",
    )
    assert payments_to_account(session, visa.id, 2026, 5) == ZERO


def test_payments_excludes_outgoing_transfer_legs(session, visa, chequing):
    # If for some reason money flows OUT of the debt account, that's not
    # a payment toward it.
    visa.balance = to_money("100")  # pretend overpaid
    session.commit()
    add_transfer(
        session,
        from_account_id=visa.id,
        to_account_id=chequing.id,
        date=date(2026, 5, 15),
        amount=to_money("50"),
    )
    assert payments_to_account(session, visa.id, 2026, 5) == ZERO


def test_payments_sums_multiple_in_same_month(session, chequing, visa):
    today = date.today()
    add_transfer(
        session,
        from_account_id=chequing.id,
        to_account_id=visa.id,
        date=today,
        amount=to_money("50"),
    )
    add_transfer(
        session,
        from_account_id=chequing.id,
        to_account_id=visa.id,
        date=today,
        amount=to_money("75"),
    )
    assert payments_to_account(session, visa.id, today.year, today.month) == to_money(
        "125.00"
    )


def test_payment_history_returns_n_months_oldest_first(session, chequing, visa):
    history = payment_history(session, visa.id, n_months=6)
    assert len(history) == 6
    for i in range(1, len(history)):
        prev = (history[i - 1][0], history[i - 1][1])
        curr = (history[i][0], history[i][1])
        assert prev < curr


def test_payment_history_default_is_six_months(session, visa):
    assert len(payment_history(session, visa.id)) == 6
