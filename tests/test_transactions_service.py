"""Tests for core/transactions_service.py — balance updates must be exact."""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core import models  # noqa: F401 — registers tables on Base.metadata
from core.db import Base
from core.models import Account, Transaction
from core.money import to_money
from core.transactions_service import (
    add_transaction,
    add_transfer,
    delete_transaction,
    update_transaction,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Local = sessionmaker(bind=engine, future=True)
    with Local() as s:
        yield s


@pytest.fixture
def chequing(session):
    a = Account(name="Chequing", type="chequing", balance=to_money("1000"))
    session.add(a)
    session.commit()
    return a


@pytest.fixture
def credit(session):
    a = Account(name="Visa", type="credit", balance=to_money("0"))
    session.add(a)
    session.commit()
    return a


def test_add_expense_decreases_balance(session, chequing):
    add_transaction(
        session,
        account_id=chequing.id,
        date=date(2026, 5, 17),
        magnitude=to_money("50.00"),
        category="Food",
        subcategory="Groceries",
    )
    session.refresh(chequing)
    assert chequing.balance == to_money("950.00")


def test_add_income_increases_balance(session, chequing):
    add_transaction(
        session,
        account_id=chequing.id,
        date=date(2026, 5, 17),
        magnitude=to_money("1500.00"),
        category="Income",
        subcategory="Salary",
    )
    session.refresh(chequing)
    assert chequing.balance == to_money("2500.00")


def test_negative_magnitude_is_normalised(session, chequing):
    add_transaction(
        session,
        account_id=chequing.id,
        date=date(2026, 5, 17),
        magnitude=Decimal("-50"),
        category="Food",
        subcategory="Groceries",
    )
    session.refresh(chequing)
    assert chequing.balance == to_money("950.00")


def test_update_changes_magnitude(session, chequing):
    tx = add_transaction(
        session,
        account_id=chequing.id,
        date=date(2026, 5, 17),
        magnitude=to_money("50"),
        category="Food",
        subcategory="Groceries",
    )
    update_transaction(
        session,
        tx.id,
        account_id=chequing.id,
        date=date(2026, 5, 17),
        magnitude=to_money("75"),
        category="Food",
        subcategory="Groceries",
    )
    session.refresh(chequing)
    assert chequing.balance == to_money("925.00")


def test_update_moves_between_accounts(session, chequing, credit):
    tx = add_transaction(
        session,
        account_id=chequing.id,
        date=date(2026, 5, 17),
        magnitude=to_money("50"),
        category="Food",
        subcategory="Groceries",
    )
    update_transaction(
        session,
        tx.id,
        account_id=credit.id,
        date=date(2026, 5, 17),
        magnitude=to_money("50"),
        category="Food",
        subcategory="Groceries",
    )
    session.refresh(chequing)
    session.refresh(credit)
    assert chequing.balance == to_money("1000.00")
    assert credit.balance == to_money("-50.00")


def test_delete_restores_balance(session, chequing):
    tx = add_transaction(
        session,
        account_id=chequing.id,
        date=date(2026, 5, 17),
        magnitude=to_money("50"),
        category="Food",
        subcategory="Groceries",
    )
    delete_transaction(session, tx.id)
    session.refresh(chequing)
    assert chequing.balance == to_money("1000.00")
    assert session.get(Transaction, tx.id) is None


def test_update_flips_kind_when_category_changes(session, chequing):
    tx = add_transaction(
        session,
        account_id=chequing.id,
        date=date(2026, 5, 17),
        magnitude=to_money("100"),
        category="Food",
        subcategory="Groceries",
    )
    assert tx.kind == "expense"
    update_transaction(
        session,
        tx.id,
        account_id=chequing.id,
        date=date(2026, 5, 17),
        magnitude=to_money("100"),
        category="Income",
        subcategory="Refund",
    )
    session.refresh(tx)
    session.refresh(chequing)
    assert tx.kind == "income"
    assert tx.amount == to_money("100.00")
    # 1000 - 100 = 900 after add (expense), then reverse +100 and apply +100 -> 1100
    assert chequing.balance == to_money("1100.00")


def test_add_to_missing_account_raises(session):
    with pytest.raises(ValueError):
        add_transaction(
            session,
            account_id=999,
            date=date(2026, 5, 17),
            magnitude=to_money("50"),
            category="Food",
            subcategory="Groceries",
        )


# --- Transfers --------------------------------------------------------------


def test_transfer_moves_money_between_accounts(session, chequing, credit):
    add_transfer(
        session,
        from_account_id=chequing.id,
        to_account_id=credit.id,
        date=date(2026, 5, 17),
        amount=to_money("200"),
    )
    session.refresh(chequing)
    session.refresh(credit)
    assert chequing.balance == to_money("800.00")
    assert credit.balance == to_money("200.00")


def test_transfer_paying_credit_card_reduces_owed(session, chequing):
    cc = Account(name="MC", type="credit", balance=to_money("-1000"))
    session.add(cc)
    session.commit()
    add_transfer(
        session,
        from_account_id=chequing.id,
        to_account_id=cc.id,
        date=date(2026, 5, 17),
        amount=to_money("300"),
    )
    session.refresh(chequing)
    session.refresh(cc)
    assert chequing.balance == to_money("700.00")
    assert cc.balance == to_money("-700.00")


def test_transfer_same_account_raises(session, chequing):
    with pytest.raises(ValueError):
        add_transfer(
            session,
            from_account_id=chequing.id,
            to_account_id=chequing.id,
            date=date(2026, 5, 17),
            amount=to_money("100"),
        )


def test_transfer_zero_amount_raises(session, chequing, credit):
    with pytest.raises(ValueError):
        add_transfer(
            session,
            from_account_id=chequing.id,
            to_account_id=credit.id,
            date=date(2026, 5, 17),
            amount=to_money("0"),
        )


def test_delete_transfer_removes_both_legs(session, chequing, credit):
    out_tx, in_tx = add_transfer(
        session,
        from_account_id=chequing.id,
        to_account_id=credit.id,
        date=date(2026, 5, 17),
        amount=to_money("100"),
    )
    out_id, in_id = out_tx.id, in_tx.id
    delete_transaction(session, out_id)
    session.refresh(chequing)
    session.refresh(credit)
    assert chequing.balance == to_money("1000.00")
    assert credit.balance == to_money("0.00")
    assert session.get(Transaction, out_id) is None
    assert session.get(Transaction, in_id) is None


def test_update_rejects_transfer(session, chequing, credit):
    out_tx, _ = add_transfer(
        session,
        from_account_id=chequing.id,
        to_account_id=credit.id,
        date=date(2026, 5, 17),
        amount=to_money("100"),
    )
    with pytest.raises(ValueError, match="Transfers can't be edited"):
        update_transaction(
            session,
            out_tx.id,
            account_id=chequing.id,
            date=date(2026, 5, 17),
            magnitude=to_money("150"),
            category="Food",
            subcategory="Groceries",
        )


def test_add_transfer_with_debt_category(session, chequing, credit):
    out_tx, in_tx = add_transfer(
        session,
        from_account_id=chequing.id,
        to_account_id=credit.id,
        date=date(2026, 5, 17),
        amount=to_money("200"),
        category="Debt Payments",
        subcategory="Credit Card",
    )
    assert out_tx.kind == "transfer"
    assert in_tx.kind == "transfer"
    assert out_tx.category == "Debt Payments"
    assert in_tx.category == "Debt Payments"
    assert out_tx.subcategory == "Credit Card"
    assert in_tx.subcategory == "Credit Card"
    # Balances still move as a transfer
    session.refresh(chequing)
    session.refresh(credit)
    assert chequing.balance == to_money("800.00")
    assert credit.balance == to_money("200.00")
