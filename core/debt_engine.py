"""Debt payoff simulator — Snowball and Avalanche strategies.

Monthly model:
1. Accrue one month of interest on every active debt.
2. Pay each active debt its minimum (capped at current balance).
3. Direct any remaining monthly budget to the target debt picked by
   strategy. Cascade leftover to the next target if it's already paid.
4. Stop when all balances reach zero, or hit max_months as a safety net.

The "snowball" of the snowball method comes from the constant monthly
budget: as debts disappear, their freed-up minimums roll into the
budget that's still being applied to the remaining debts.

All math is Decimal. Interest is simple monthly compounding from the
annual rate (annual_rate / 100 / 12). It's an approximation — real
credit card APR with fees, daily compounding, and changing minimums
will differ slightly. Good enough for planning.
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from core.money import ZERO, to_money

Strategy = Literal["snowball", "avalanche"]


@dataclass(frozen=True)
class Debt:
    """Input row for the simulator."""

    name: str
    balance: Decimal       # positive: amount owed today
    annual_rate: Decimal   # e.g. Decimal("19.99") for 19.99%
    min_payment: Decimal


@dataclass
class SimulationResult:
    strategy: Strategy
    months: int
    total_interest_paid: Decimal
    payoff_month_by_debt: dict[str, int]
    monthly_total: list[Decimal]  # total debt at end of each month


def _monthly_rate(annual_rate: Decimal) -> Decimal:
    return annual_rate / Decimal("100") / Decimal("12")


def _pick_target(
    active: list[Debt], balances: dict[str, Decimal], strategy: Strategy
) -> Debt:
    if strategy == "snowball":
        return min(active, key=lambda d: balances[d.name])
    return max(active, key=lambda d: d.annual_rate)


def simulate(
    debts: list[Debt],
    extra_payment: Decimal,
    strategy: Strategy,
    max_months: int = 600,
) -> SimulationResult:
    """Run a payoff simulation. Returns months=max_months if not paid off."""
    if not debts:
        return SimulationResult(
            strategy=strategy,
            months=0,
            total_interest_paid=ZERO,
            payoff_month_by_debt={},
            monthly_total=[],
        )

    balances: dict[str, Decimal] = {d.name: to_money(d.balance) for d in debts}
    monthly_budget = to_money(
        sum((d.min_payment for d in debts), ZERO) + extra_payment
    )
    payoff_month: dict[str, int] = {}
    monthly_total: list[Decimal] = []
    total_interest = ZERO

    for month in range(1, max_months + 1):
        # 1) Accrue interest
        for d in debts:
            if balances[d.name] > ZERO:
                interest = to_money(balances[d.name] * _monthly_rate(d.annual_rate))
                balances[d.name] = to_money(balances[d.name] + interest)
                total_interest = to_money(total_interest + interest)

        # 2) Pay minimums (capped at remaining balance)
        available = monthly_budget
        for d in debts:
            if balances[d.name] <= ZERO:
                continue
            pay = to_money(min(d.min_payment, balances[d.name], available))
            balances[d.name] = to_money(balances[d.name] - pay)
            available = to_money(available - pay)

        # 3) Apply remaining budget to target(s), cascading as targets pay off
        while available > ZERO:
            active = [d for d in debts if balances[d.name] > ZERO]
            if not active:
                break
            target = _pick_target(active, balances, strategy)
            pay = to_money(min(available, balances[target.name]))
            balances[target.name] = to_money(balances[target.name] - pay)
            available = to_money(available - pay)

        # 4) Record payoff months & running totals
        for d in debts:
            if balances[d.name] <= ZERO and d.name not in payoff_month:
                payoff_month[d.name] = month
        monthly_total.append(to_money(sum(balances.values(), ZERO)))

        if all(balances[d.name] <= ZERO for d in debts):
            return SimulationResult(
                strategy=strategy,
                months=month,
                total_interest_paid=total_interest,
                payoff_month_by_debt=payoff_month,
                monthly_total=monthly_total,
            )

    return SimulationResult(
        strategy=strategy,
        months=max_months,
        total_interest_paid=total_interest,
        payoff_month_by_debt=payoff_month,
        monthly_total=monthly_total,
    )
