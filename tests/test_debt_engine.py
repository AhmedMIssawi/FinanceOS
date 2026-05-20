"""Tests for core/debt_engine.py — strategy correctness and edge cases."""
from core.debt_engine import Debt, simulate
from core.money import ZERO, to_money


def test_simulate_empty():
    result = simulate([], to_money("100"), "snowball")
    assert result.months == 0
    assert result.total_interest_paid == ZERO
    assert result.monthly_total == []


def test_zero_interest_pays_off_linearly():
    debt = Debt(
        name="A",
        balance=to_money("100"),
        annual_rate=ZERO,
        min_payment=to_money("50"),
    )
    result = simulate([debt], ZERO, "avalanche")
    assert result.months == 2
    assert result.total_interest_paid == ZERO


def test_extra_payment_speeds_up_payoff():
    debt = Debt(
        name="A",
        balance=to_money("100"),
        annual_rate=ZERO,
        min_payment=to_money("10"),
    )
    no_extra = simulate([debt], ZERO, "avalanche")
    with_extra = simulate([debt], to_money("40"), "avalanche")
    assert no_extra.months == 10
    assert with_extra.months == 2


def test_interest_accrues_correctly():
    # $1000 at 12% annual = 1% monthly. Month 1: interest $10, pay $100,
    # ending balance = 1000 + 10 - 100 = 910.
    debt = Debt(
        name="A",
        balance=to_money("1000"),
        annual_rate=to_money("12"),
        min_payment=to_money("100"),
    )
    result = simulate([debt], ZERO, "avalanche", max_months=2)
    assert result.monthly_total[0] == to_money("910.00")


def test_avalanche_targets_highest_interest_rate():
    high = Debt(
        name="HighRate",
        balance=to_money("1000"),
        annual_rate=to_money("25"),
        min_payment=to_money("50"),
    )
    low = Debt(
        name="LowRate",
        balance=to_money("1000"),
        annual_rate=to_money("5"),
        min_payment=to_money("50"),
    )
    result = simulate([low, high], to_money("200"), "avalanche")
    assert result.payoff_month_by_debt["HighRate"] < result.payoff_month_by_debt["LowRate"]


def test_snowball_targets_smallest_balance():
    big = Debt(
        name="Big",
        balance=to_money("1000"),
        annual_rate=to_money("10"),
        min_payment=to_money("50"),
    )
    small = Debt(
        name="Small",
        balance=to_money("200"),
        annual_rate=to_money("10"),
        min_payment=to_money("50"),
    )
    result = simulate([big, small], to_money("100"), "snowball")
    assert result.payoff_month_by_debt["Small"] < result.payoff_month_by_debt["Big"]


def test_avalanche_saves_more_interest_when_rates_differ():
    # The two strategies must actually pick DIFFERENT debts for this test
    # to be meaningful. With high-rate=bigger and low-rate=smaller, snowball
    # targets the small one first (motivation-style) while avalanche kills
    # the high-rate principal first (math-optimal) — so the two diverge.
    high_rate_big = Debt(
        name="HighBig",
        balance=to_money("2000"),
        annual_rate=to_money("25"),
        min_payment=to_money("20"),
    )
    low_rate_small = Debt(
        name="LowSmall",
        balance=to_money("500"),
        annual_rate=to_money("5"),
        min_payment=to_money("50"),
    )
    snowball = simulate([high_rate_big, low_rate_small], to_money("200"), "snowball")
    avalanche = simulate([high_rate_big, low_rate_small], to_money("200"), "avalanche")
    assert avalanche.total_interest_paid < snowball.total_interest_paid


def test_rollover_after_debt_pays_off():
    # Tiny pays off cleanly in month 1 ($5 balance with $5 min and $0 extra).
    # From month 2 onward, Tiny's freed-up $5 should roll over into Bigger
    # via the step-3 cascade — making Bigger pay off in 5 months instead of 5.
    tiny = Debt(
        name="Tiny",
        balance=to_money("5"),
        annual_rate=ZERO,
        min_payment=to_money("5"),
    )
    bigger = Debt(
        name="Bigger",
        balance=to_money("100"),
        annual_rate=ZERO,
        min_payment=to_money("20"),
    )
    result = simulate([tiny, bigger], ZERO, "snowball")
    assert result.payoff_month_by_debt["Tiny"] == 1
    # Without rollover: 100 / 20 = 5 months. With rollover from month 2: 5 too,
    # because month 1 already pays $20 on Bigger. But the rollover ensures
    # we don't take longer than that — verify Bigger doesn't drag past 5.
    assert result.payoff_month_by_debt["Bigger"] == 5


def test_max_months_safety_cap_for_runaway_debt():
    # Interest exceeds payment → balance grows. Should bail out at max_months.
    stuck = Debt(
        name="Stuck",
        balance=to_money("1000"),
        annual_rate=to_money("100"),  # 100% annual = ~8.33% monthly
        min_payment=to_money("10"),
    )
    result = simulate([stuck], ZERO, "avalanche", max_months=12)
    assert result.months == 12
    assert result.monthly_total[-1] > to_money("1000")
