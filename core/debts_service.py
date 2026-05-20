"""Debt-specific queries: payment history per account.

A "payment toward a debt" is detected as an incoming transfer leg —
i.e. a Transaction row on the debt account with `kind == "transfer"`
and a positive amount. Expenses recorded on the debt account (e.g.
charging a credit card) are NOT payments; they're new debt.
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import extract, select
from sqlalchemy.orm import Session

from core.models import Transaction
from core.money import ZERO, to_money


def payments_to_account(
    session: Session, account_id: int, year: int, month: int
) -> Decimal:
    """Sum of positive transfer legs on this account during the given month.

    Used to total payments toward a debt — paying a credit card from
    chequing creates a positive transfer leg on the credit card.
    """
    rows = session.execute(
        select(Transaction.amount).where(
            Transaction.account_id == account_id,
            Transaction.kind == "transfer",
            Transaction.amount > 0,
            extract("year", Transaction.date) == year,
            extract("month", Transaction.date) == month,
        )
    ).all()
    return to_money(sum((r[0] for r in rows), ZERO))


def payment_summary(session: Session, account_id: int) -> tuple[Decimal, int]:
    """Lifetime total paid to this account + count of payment events.

    Returns (total_amount_paid, payment_count). Used by the auto-archive
    summary so retired loans/financing carry a record of how they ended.
    """
    rows = session.execute(
        select(Transaction.amount).where(
            Transaction.account_id == account_id,
            Transaction.kind == "transfer",
            Transaction.amount > 0,
        )
    ).all()
    amounts = [r[0] for r in rows]
    return to_money(sum(amounts, ZERO)), len(amounts)


def payment_history(
    session: Session, account_id: int, n_months: int = 6
) -> list[tuple[int, int, Decimal]]:
    """Last n_months of (year, month, paid) totals for the account, oldest first."""
    today = date.today()
    months: list[tuple[int, int]] = []
    for offset in range(n_months - 1, -1, -1):
        m = today.month - offset
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        months.append((y, m))

    return [(y, m, payments_to_account(session, account_id, y, m)) for y, m in months]
