"""Dashboard data aggregation functions.

Pure read-only queries for the KPIs and charts on Dashboard.py.
Separated from the page so they're testable without Streamlit.

Conventions:
- Money returns are always Decimal (quantized to 2dp).
- Spending sums use abs(amount) — the stored sign is for ledger math,
  but humans want positive dollars in their charts.
- Transfers are excluded everywhere (they don't change net cash flow
  or category-level spending).
"""
from datetime import date
from decimal import Decimal
from typing import NamedTuple, Optional

from sqlalchemy import and_, extract, or_, select
from sqlalchemy.orm import Session

from core.categories import parent_subcategory
from core.models import Account, Transaction
from core.money import ZERO, active_currency_code, to_money


def _outflow_filter():
    """SQLAlchemy WHERE clause matching every transaction that represents
    money leaving the user's accounts: regular expenses AND debt-payment
    source legs. Used by spending/cash-flow aggregations so debt payments
    don't silently fall out of the picture."""
    return or_(
        Transaction.kind == "expense",
        and_(
            Transaction.kind == "transfer",
            Transaction.category == "Debt Payments",
            Transaction.amount < ZERO,
        ),
    )

# Liquid asset types — counted in "Cash Available".
LIQUID_TYPES = ("chequing", "savings", "cash")

# Debt-eligible types — mirrored from pages/4_Debts.py.
DEBT_TYPES = ("credit", "financing", "overdraft", "loan")


def _to_active(amount: Decimal, from_currency: str, session: Session) -> Optional[Decimal]:
    """Convert `amount` from its native currency to the active display
    currency. Returns the amount unchanged when currencies match, or
    None if no exchange rate is stored for the pair (caller decides
    whether to skip the account or surface a warning)."""
    target = active_currency_code()
    if from_currency == target:
        return amount
    # Lazy import to avoid a circular dependency at module-load time.
    from core.exchange_service import get_rate
    rate = get_rate(session, from_currency, target)
    if rate is None:
        return None
    return amount * rate


def accounts_with_missing_rates(session: Session) -> list[Account]:
    """Return active accounts whose currency != active currency AND no
    exchange rate is stored — those won't appear in KPI aggregates and
    the UI should warn the user to fetch rates."""
    target = active_currency_code()
    rows = session.scalars(select(Account)).all()
    missing: list[Account] = []
    for a in rows:
        if a.currency == target:
            continue
        if _to_active(a.balance, a.currency, session) is None:
            missing.append(a)
    return missing


def net_worth(session: Session) -> Decimal:
    """Sum of all account balances, converted to the active currency.
    Accounts whose rate isn't stored are silently skipped — use
    `accounts_with_missing_rates` to surface them in the UI."""
    rows = session.scalars(select(Account)).all()
    total = ZERO
    for a in rows:
        c = _to_active(a.balance, a.currency, session)
        if c is not None:
            total += c
    return to_money(total)


def total_debt(session: Session) -> Decimal:
    """Sum of owed amounts (positive), converted to the active currency."""
    rows = session.scalars(select(Account)).all()
    total = ZERO
    for a in rows:
        if a.type not in DEBT_TYPES or a.balance >= ZERO:
            continue
        c = _to_active(-a.balance, a.currency, session)
        if c is not None:
            total += c
    return to_money(total)


def cash_available(session: Session) -> Decimal:
    """Total liquid balances, converted to the active currency."""
    rows = session.scalars(select(Account)).all()
    total = ZERO
    for a in rows:
        if a.type not in LIQUID_TYPES or a.balance <= ZERO:
            continue
        c = _to_active(a.balance, a.currency, session)
        if c is not None:
            total += c
    return to_money(total)


def savings_total(session: Session) -> Decimal:
    """Total in savings accounts, converted to the active currency."""
    rows = session.scalars(select(Account).where(Account.type == "savings")).all()
    total = ZERO
    for a in rows:
        c = _to_active(a.balance, a.currency, session)
        if c is not None:
            total += c
    return to_money(total)


def coins_total(session: Session) -> Decimal:
    """Total in coins accounts, converted to the active currency."""
    rows = session.scalars(select(Account).where(Account.type == "coins")).all()
    total = ZERO
    for a in rows:
        c = _to_active(a.balance, a.currency, session)
        if c is not None:
            total += c
    return to_money(total)


class MonthlyFlow(NamedTuple):
    year: int
    month: int
    income: Decimal
    expense: Decimal  # positive magnitude


def cash_flow_last_n_months(session: Session, n: int = 6) -> list[MonthlyFlow]:
    """Last n calendar months (oldest first) of income vs expense totals.

    Account-to-account transfers are excluded (they don't change overall
    cash flow). Debt-payment outflows ARE counted as expense since they
    do reduce your spendable cash even though they're internally modeled
    as transfers.
    """
    today = date.today()
    months: list[tuple[int, int]] = []
    for offset in range(n - 1, -1, -1):
        m = today.month - offset
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        months.append((y, m))

    months_set = set(months)
    income_by_month: dict[tuple[int, int], Decimal] = {}
    expense_by_month: dict[tuple[int, int], Decimal] = {}

    rows = session.execute(
        select(
            Transaction.date,
            Transaction.amount,
            Transaction.kind,
            Transaction.category,
        )
    ).all()

    for tx_date, amount, kind, category in rows:
        key = (tx_date.year, tx_date.month)
        if key not in months_set:
            continue
        if kind == "income":
            income_by_month[key] = income_by_month.get(key, ZERO) + amount
        elif kind == "expense":
            expense_by_month[key] = expense_by_month.get(key, ZERO) + abs(amount)
        elif (
            kind == "transfer"
            and category == "Debt Payments"
            and amount < ZERO
        ):
            # Debt payment outflow — counts as expense for cash-flow purposes.
            expense_by_month[key] = expense_by_month.get(key, ZERO) + abs(amount)

    return [
        MonthlyFlow(
            year=y,
            month=m,
            income=to_money(income_by_month.get((y, m), ZERO)),
            expense=to_money(expense_by_month.get((y, m), ZERO)),
        )
        for y, m in months
    ]


def spending_by_category(
    session: Session, year: int, month: int
) -> dict[str, Decimal]:
    """Total spending magnitude per category for the given month.

    Includes regular expenses AND debt-payment outflows (see `_outflow_filter`).
    """
    rows = session.execute(
        select(Transaction.category, Transaction.amount).where(
            _outflow_filter(),
            extract("year", Transaction.date) == year,
            extract("month", Transaction.date) == month,
        )
    ).all()
    out: dict[str, Decimal] = {}
    for cat, amount in rows:
        out[cat] = out.get(cat, ZERO) + abs(amount)
    return {k: to_money(v) for k, v in out.items()}


def top_subcategories(
    session: Session, year: int, month: int, limit: int = 5
) -> list[tuple[str, Decimal]]:
    """Top N spending subcategories by total amount in the given month.

    Includes debt payments. Applies SUBCATEGORY_PARENTS rollup.
    """
    rows = session.execute(
        select(Transaction.subcategory, Transaction.amount).where(
            _outflow_filter(),
            extract("year", Transaction.date) == year,
            extract("month", Transaction.date) == month,
        )
    ).all()
    out: dict[str, Decimal] = {}
    for sub, amount in rows:
        rollup = parent_subcategory(sub)
        out[rollup] = out.get(rollup, ZERO) + abs(amount)
    ranked = sorted(out.items(), key=lambda x: x[1], reverse=True)
    return [(name, to_money(amt)) for name, amt in ranked[:limit]]


def recent_transactions(session: Session, limit: int = 10) -> list[Transaction]:
    """Most recent N transactions, newest first."""
    return list(
        session.scalars(
            select(Transaction)
            .order_by(Transaction.date.desc(), Transaction.id.desc())
            .limit(limit)
        ).all()
    )
