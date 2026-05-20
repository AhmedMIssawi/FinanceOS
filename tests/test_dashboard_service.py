"""Tests for core/dashboard_service.py."""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core import models  # noqa: F401
from core.dashboard_service import (
    cash_available,
    cash_flow_last_n_months,
    coins_total,
    net_worth,
    recent_transactions,
    savings_total,
    spending_by_category,
    top_subcategories,
    total_debt,
)
from core.db import Base
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
def accounts(session):
    chequing = Account(name="Chequing", type="chequing", balance=to_money("3000"))
    savings = Account(name="Savings", type="savings", balance=to_money("1500"))
    cash = Account(name="Cash", type="cash", balance=to_money("200"))
    visa = Account(name="Visa", type="credit", balance=to_money("-450"))
    financing = Account(
        name="Watch Financing", type="financing", balance=to_money("-300")
    )
    session.add_all([chequing, savings, cash, visa, financing])
    session.commit()
    return {
        "chequing": chequing,
        "savings": savings,
        "cash": cash,
        "visa": visa,
        "financing": financing,
    }


def test_net_worth(session, accounts):
    # 3000 + 1500 + 200 - 450 - 300
    assert net_worth(session) == to_money("3950.00")


def test_total_debt_sums_owed_amounts(session, accounts):
    assert total_debt(session) == to_money("750.00")


def test_total_debt_ignores_chequing_overdraft(session):
    # A chequing in the red doesn't count as "debt" — only proper debt types do.
    od_chequing = Account(name="OD", type="chequing", balance=to_money("-100"))
    session.add(od_chequing)
    session.commit()
    assert total_debt(session) == ZERO


def test_cash_available_liquid_only(session, accounts):
    # chequing 3000 + savings 1500 + cash 200 — credit/financing excluded
    assert cash_available(session) == to_money("4700.00")


def test_savings_total(session, accounts):
    assert savings_total(session) == to_money("1500.00")


def test_coins_total(session):
    coins_account = Account(name="Coins", type="coins", balance=to_money("12.50"))
    session.add(coins_account)
    session.commit()
    assert coins_total(session) == to_money("12.50")


def test_coins_total_excludes_cash_type(session):
    cash_account = Account(name="Cash", type="cash", balance=to_money("50"))
    session.add(cash_account)
    session.commit()
    assert coins_total(session) == ZERO


def test_cash_available_excludes_coins(session):
    coins_account = Account(name="Coins", type="coins", balance=to_money("12.50"))
    cash_account = Account(name="Cash", type="cash", balance=to_money("100"))
    session.add_all([coins_account, cash_account])
    session.commit()
    # Coins must NOT be lumped into the Cash KPI — they have their own bucket.
    assert cash_available(session) == to_money("100.00")


def test_cash_flow_excludes_plain_transfers(session, accounts):
    today = date.today()
    add_transaction(
        session,
        account_id=accounts["chequing"].id,
        date=today,
        magnitude=to_money("2000"),
        category="Income",
        subcategory="Salary",
    )
    add_transaction(
        session,
        account_id=accounts["chequing"].id,
        date=today,
        magnitude=to_money("500"),
        category="Food",
        subcategory="Groceries",
    )
    # Plain transfer between liquid accounts — shouldn't affect cash flow
    add_transfer(
        session,
        from_account_id=accounts["chequing"].id,
        to_account_id=accounts["savings"].id,
        date=today,
        amount=to_money("100"),
    )
    flows = cash_flow_last_n_months(session, n=1)
    assert len(flows) == 1
    assert flows[0].income == to_money("2000.00")
    assert flows[0].expense == to_money("500.00")


def test_cash_flow_includes_debt_payment_as_expense(session, accounts):
    today = date.today()
    add_transaction(
        session,
        account_id=accounts["chequing"].id,
        date=today,
        magnitude=to_money("3000"),
        category="Income",
        subcategory="Salary",
    )
    # Debt payment IS counted as cash outflow even though internally a transfer
    add_transfer(
        session,
        from_account_id=accounts["chequing"].id,
        to_account_id=accounts["visa"].id,
        date=today,
        amount=to_money("400"),
        category="Debt Payments",
        subcategory="Credit Card",
    )
    flows = cash_flow_last_n_months(session, n=1)
    assert flows[0].income == to_money("3000.00")
    assert flows[0].expense == to_money("400.00")


def test_cash_flow_returns_six_months_oldest_first(session, accounts):
    flows = cash_flow_last_n_months(session, n=6)
    assert len(flows) == 6
    # Months should be ordered oldest -> newest.
    for i in range(1, len(flows)):
        prev_key = (flows[i - 1].year, flows[i - 1].month)
        curr_key = (flows[i].year, flows[i].month)
        assert prev_key < curr_key


def test_spending_by_category(session, accounts):
    today = date.today()
    add_transaction(
        session,
        account_id=accounts["chequing"].id,
        date=today,
        magnitude=to_money("80"),
        category="Food",
        subcategory="Groceries",
    )
    add_transaction(
        session,
        account_id=accounts["chequing"].id,
        date=today,
        magnitude=to_money("30"),
        category="Transport",
        subcategory="Gas",
    )
    result = spending_by_category(session, today.year, today.month)
    assert result == {"Food": to_money("80.00"), "Transport": to_money("30.00")}


def test_spending_by_category_includes_debt_payments(session, accounts):
    today = date.today()
    add_transaction(
        session,
        account_id=accounts["chequing"].id,
        date=today,
        magnitude=to_money("80"),
        category="Food",
        subcategory="Groceries",
    )
    add_transfer(
        session,
        from_account_id=accounts["chequing"].id,
        to_account_id=accounts["visa"].id,
        date=today,
        amount=to_money("250"),
        category="Debt Payments",
        subcategory="Credit Card",
    )
    result = spending_by_category(session, today.year, today.month)
    assert result == {
        "Food": to_money("80.00"),
        "Debt Payments": to_money("250.00"),
    }


def test_top_subcategories_ranks_by_amount(session, accounts):
    today = date.today()
    add_transaction(
        session,
        account_id=accounts["chequing"].id,
        date=today,
        magnitude=to_money("80"),
        category="Food",
        subcategory="Groceries",
    )
    add_transaction(
        session,
        account_id=accounts["chequing"].id,
        date=today,
        magnitude=to_money("30"),
        category="Transport",
        subcategory="Gas",
    )
    add_transaction(
        session,
        account_id=accounts["chequing"].id,
        date=today,
        magnitude=to_money("10"),
        category="Food",
        subcategory="Coffee",
    )
    top = top_subcategories(session, today.year, today.month, limit=2)
    assert top[0] == ("Groceries", to_money("80.00"))
    assert top[1] == ("Gas", to_money("30.00"))


# --- Per-account currency conversion in KPI aggregations ---------------


def test_net_worth_converts_foreign_currency(session):
    from core.dashboard_service import net_worth
    from core.exchange_service import set_rate
    set_rate(session, "USD", "CAD", Decimal("1.40"))
    session.add(Account(name="C", type="chequing", currency="CAD", balance=to_money("100")))
    session.add(Account(name="U", type="chequing", currency="USD", balance=to_money("100")))
    session.commit()
    # 100 CAD + 100 USD * 1.40 = 100 + 140 = 240
    assert net_worth(session) == to_money("240.00")


def test_total_debt_converts_foreign_currency(session):
    from core.dashboard_service import total_debt
    from core.exchange_service import set_rate
    set_rate(session, "USD", "CAD", Decimal("1.40"))
    session.add(Account(name="V", type="credit", currency="CAD", balance=to_money("-500")))
    session.add(Account(name="UV", type="credit", currency="USD", balance=to_money("-100")))
    session.commit()
    # 500 CAD + 100 USD * 1.40 = 500 + 140 = 640
    assert total_debt(session) == to_money("640.00")


def test_cash_available_converts_foreign_currency(session):
    from core.dashboard_service import cash_available
    from core.exchange_service import set_rate
    set_rate(session, "USD", "CAD", Decimal("1.40"))
    session.add(Account(name="C", type="chequing", currency="CAD", balance=to_money("200")))
    session.add(Account(name="U", type="chequing", currency="USD", balance=to_money("100")))
    session.commit()
    assert cash_available(session) == to_money("340.00")


def test_account_with_no_rate_is_silently_skipped(session):
    """When no rate is stored for a foreign account, it's excluded from
    KPI totals (the page surfaces it via accounts_with_missing_rates)."""
    from core.dashboard_service import net_worth
    session.add(Account(name="C", type="chequing", currency="CAD", balance=to_money("100")))
    # USD account with no USD->CAD rate stored
    session.add(Account(name="U", type="chequing", currency="USD", balance=to_money("999")))
    session.commit()
    # Only CAD account counts; USD silently skipped
    assert net_worth(session) == to_money("100.00")


def test_accounts_with_missing_rates_lists_them(session):
    from core.dashboard_service import accounts_with_missing_rates
    session.add(Account(name="C", type="chequing", currency="CAD", balance=to_money("100")))
    session.add(Account(name="U", type="chequing", currency="USD", balance=to_money("100")))
    session.commit()
    missing = accounts_with_missing_rates(session)
    assert len(missing) == 1
    assert missing[0].name == "U"


def test_no_missing_rates_when_all_active_currency(session):
    from core.dashboard_service import accounts_with_missing_rates
    session.add(Account(name="C1", type="chequing", currency="CAD", balance=to_money("100")))
    session.add(Account(name="C2", type="savings", currency="CAD", balance=to_money("200")))
    session.commit()
    assert accounts_with_missing_rates(session) == []


def test_recent_transactions_limit(session, accounts):
    today = date.today()
    for i in range(15):
        add_transaction(
            session,
            account_id=accounts["chequing"].id,
            date=date(today.year, today.month, max(1, min(i + 1, 28))),
            magnitude=to_money("10"),
            category="Food",
            subcategory="Groceries",
        )
    recent = recent_transactions(session, limit=5)
    assert len(recent) == 5
