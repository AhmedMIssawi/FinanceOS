"""Budget queries and persistence.

Budgets are scoped per (year, month, category). Income is not budgeted
(you don't limit income — you grow it). Transfers don't count toward
any budget because their kind is "transfer", not "expense".

`copy_budgets` is intentionally non-destructive: it skips categories
already set in the destination month so the user can't accidentally
wipe a budget they've already adjusted.
"""
from decimal import Decimal

from sqlalchemy import and_, extract, or_, select
from sqlalchemy.orm import Session

from core.models import Budget, Transaction
from core.money import ZERO


def get_budgets(session: Session, year: int, month: int) -> dict[str, Decimal]:
    """Map category -> budget limit for the given month."""
    rows = session.scalars(
        select(Budget).where(Budget.year == year, Budget.month == month)
    ).all()
    return {b.category: b.limit_amount for b in rows}


def get_spent_by_category(
    session: Session, year: int, month: int
) -> dict[str, Decimal]:
    """Map category -> total spent (positive magnitude) this month.

    Counts:
    - Regular expenses (kind="expense").
    - Debt-payment OUTFLOWS — i.e. transfer legs with negative amount
      on the source account, category="Debt Payments". Including these
      lets the user budget for debt payments as a normal category.

    Excludes pure income and account-to-account transfers (e.g. moving
    cash to savings) — those don't count as "spending".
    """
    rows = session.execute(
        select(Transaction.category, Transaction.amount).where(
            or_(
                Transaction.kind == "expense",
                and_(
                    Transaction.kind == "transfer",
                    Transaction.category == "Debt Payments",
                    Transaction.amount < ZERO,
                ),
            ),
            extract("year", Transaction.date) == year,
            extract("month", Transaction.date) == month,
        )
    ).all()
    spent: dict[str, Decimal] = {}
    for cat, amt in rows:
        spent[cat] = spent.get(cat, ZERO) + abs(amt)
    return spent


def upsert_budget(
    session: Session,
    *,
    year: int,
    month: int,
    category: str,
    limit_amount: Decimal,
) -> None:
    """Set a budget. Setting to zero deletes any existing record."""
    existing = session.scalar(
        select(Budget).where(
            Budget.year == year,
            Budget.month == month,
            Budget.category == category,
        )
    )
    if existing:
        if limit_amount == ZERO:
            session.delete(existing)
        else:
            existing.limit_amount = limit_amount
    elif limit_amount > ZERO:
        session.add(
            Budget(
                year=year,
                month=month,
                category=category,
                limit_amount=limit_amount,
            )
        )
    session.commit()


def copy_budgets(
    session: Session,
    *,
    from_year: int,
    from_month: int,
    to_year: int,
    to_month: int,
) -> int:
    """Copy budgets between months. Skips categories already set in the
    destination so the user can't accidentally overwrite their work.

    Returns the number of NEW budgets created.
    """
    source_rows = session.scalars(
        select(Budget).where(Budget.year == from_year, Budget.month == from_month)
    ).all()
    existing_cats = {
        b.category
        for b in session.scalars(
            select(Budget).where(Budget.year == to_year, Budget.month == to_month)
        ).all()
    }
    count = 0
    for b in source_rows:
        if b.category in existing_cats:
            continue
        session.add(
            Budget(
                year=to_year,
                month=to_month,
                category=b.category,
                limit_amount=b.limit_amount,
            )
        )
        count += 1
    session.commit()
    return count
