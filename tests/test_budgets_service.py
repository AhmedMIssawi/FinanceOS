"""Tests for core/budgets_service.py."""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core import models  # noqa: F401 — registers tables on Base.metadata
from core.budgets_service import (
    copy_budgets,
    get_budgets,
    get_spent_by_category,
    upsert_budget,
)
from core.db import Base
from core.models import Account
from core.money import to_money
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
    a = Account(name="Chequing", type="chequing", balance=to_money("10000"))
    session.add(a)
    session.commit()
    return a


@pytest.fixture
def credit(session):
    a = Account(name="Visa", type="credit", balance=to_money("0"))
    session.add(a)
    session.commit()
    return a


def test_get_budgets_empty(session):
    assert get_budgets(session, 2026, 5) == {}


def test_upsert_budget_creates(session):
    upsert_budget(
        session, year=2026, month=5, category="Food", limit_amount=to_money("500")
    )
    assert get_budgets(session, 2026, 5) == {"Food": to_money("500.00")}


def test_upsert_budget_updates_existing(session):
    upsert_budget(
        session, year=2026, month=5, category="Food", limit_amount=to_money("500")
    )
    upsert_budget(
        session, year=2026, month=5, category="Food", limit_amount=to_money("600")
    )
    assert get_budgets(session, 2026, 5) == {"Food": to_money("600.00")}


def test_upsert_budget_zero_deletes(session):
    upsert_budget(
        session, year=2026, month=5, category="Food", limit_amount=to_money("500")
    )
    upsert_budget(
        session, year=2026, month=5, category="Food", limit_amount=to_money("0")
    )
    assert get_budgets(session, 2026, 5) == {}


def test_get_spent_sums_expenses_per_category(session, chequing):
    add_transaction(
        session,
        account_id=chequing.id,
        date=date(2026, 5, 15),
        magnitude=to_money("50"),
        category="Food",
        subcategory="Groceries",
    )
    add_transaction(
        session,
        account_id=chequing.id,
        date=date(2026, 5, 20),
        magnitude=to_money("30"),
        category="Food",
        subcategory="Coffee",
    )
    add_transaction(
        session,
        account_id=chequing.id,
        date=date(2026, 5, 25),
        magnitude=to_money("20"),
        category="Transport",
        subcategory="Gas",
    )
    spent = get_spent_by_category(session, 2026, 5)
    assert spent == {"Food": to_money("80.00"), "Transport": to_money("20.00")}


def test_get_spent_excludes_other_months(session, chequing):
    add_transaction(
        session,
        account_id=chequing.id,
        date=date(2026, 4, 30),
        magnitude=to_money("50"),
        category="Food",
        subcategory="Groceries",
    )
    add_transaction(
        session,
        account_id=chequing.id,
        date=date(2026, 5, 1),
        magnitude=to_money("30"),
        category="Food",
        subcategory="Groceries",
    )
    spent = get_spent_by_category(session, 2026, 5)
    assert spent == {"Food": to_money("30.00")}


def test_get_spent_excludes_income(session, chequing):
    add_transaction(
        session,
        account_id=chequing.id,
        date=date(2026, 5, 15),
        magnitude=to_money("2000"),
        category="Income",
        subcategory="Salary",
    )
    spent = get_spent_by_category(session, 2026, 5)
    assert spent == {}


def test_get_spent_excludes_plain_transfers(session, chequing, credit):
    # Account-to-account transfer with no special category — should NOT
    # count as spending in any category.
    add_transfer(
        session,
        from_account_id=chequing.id,
        to_account_id=credit.id,
        date=date(2026, 5, 15),
        amount=to_money("500"),
    )
    spent = get_spent_by_category(session, 2026, 5)
    assert spent == {}


def test_get_spent_includes_debt_payment_transfers(session, chequing, credit):
    # Debt-payment transfers DO count as spending in the Debt Payments
    # category — that's how the budget tracker knows you paid down debt.
    add_transfer(
        session,
        from_account_id=chequing.id,
        to_account_id=credit.id,
        date=date(2026, 5, 15),
        amount=to_money("200"),
        category="Debt Payments",
        subcategory="Credit Card",
    )
    spent = get_spent_by_category(session, 2026, 5)
    assert spent == {"Debt Payments": to_money("200.00")}


def test_copy_budgets_to_empty_month(session):
    upsert_budget(
        session, year=2026, month=4, category="Food", limit_amount=to_money("500")
    )
    upsert_budget(
        session,
        year=2026,
        month=4,
        category="Transport",
        limit_amount=to_money("200"),
    )
    count = copy_budgets(
        session, from_year=2026, from_month=4, to_year=2026, to_month=5
    )
    assert count == 2
    assert get_budgets(session, 2026, 5) == {
        "Food": to_money("500.00"),
        "Transport": to_money("200.00"),
    }


def test_copy_budgets_skips_already_set(session):
    upsert_budget(
        session, year=2026, month=4, category="Food", limit_amount=to_money("500")
    )
    upsert_budget(
        session,
        year=2026,
        month=4,
        category="Transport",
        limit_amount=to_money("200"),
    )
    # Destination already has Food set to a different value
    upsert_budget(
        session, year=2026, month=5, category="Food", limit_amount=to_money("999")
    )
    count = copy_budgets(
        session, from_year=2026, from_month=4, to_year=2026, to_month=5
    )
    assert count == 1  # only Transport copied; Food preserved
    assert get_budgets(session, 2026, 5) == {
        "Food": to_money("999.00"),
        "Transport": to_money("200.00"),
    }
