"""Debts — list debts and run snowball / avalanche payoff projections.

Debts are auto-derived from accounts whose type is in DEBT_TYPES and
whose balance is negative. Each debt's `min_payment` (stored on the
Account) feeds the simulator alongside the user-entered extra payment.
"""
import calendar
from datetime import date
from decimal import Decimal

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import select

from core.db import SessionLocal, init_db
from core.debt_engine import Debt as DebtIn, simulate
from core.debts_service import payment_history, payments_to_account
from core.models import Account
from core.money import ZERO, format_cad, to_money

init_db()

st.set_page_config(page_title="Debts | FinanceOS", layout="wide")
st.title("Debts")
st.caption(
    "Plan your debt payoff. Debts are detected automatically from any "
    "account with a negative balance — credit cards, financing, "
    "overdraft, and 'Loan from X' accounts."
)

today = date.today()

DEBT_TYPES = ("credit", "financing", "overdraft", "loan")


def load_debts() -> list[Account]:
    with SessionLocal() as session:
        rows = session.scalars(select(Account).where(~Account.archived)).all()
        return [a for a in rows if a.type in DEBT_TYPES and a.balance < ZERO]


def _months_to_date(months: int) -> date:
    today = date.today()
    new_month = today.month + months
    new_year = today.year + (new_month - 1) // 12
    new_month = ((new_month - 1) % 12) + 1
    return date(new_year, new_month, 1)


debts = load_debts()

if not debts:
    st.info(
        "No debts found. Add a credit card, financing, overdraft, or "
        "'Loan from X' account (with a negative balance) on the Accounts "
        "page to use the payoff simulator."
    )
    st.stop()

# --- Top metrics ------------------------------------------------------------
total_owed = sum((-a.balance for a in debts), ZERO)
total_min = sum((a.min_payment or ZERO for a in debts), ZERO)
monthly_interest_cost = sum(
    (
        to_money(-a.balance * a.interest_rate / Decimal("100") / Decimal("12"))
        for a in debts
    ),
    ZERO,
)

m1, m2, m3 = st.columns(3)
m1.metric("Total Debt", format_cad(total_owed))
m2.metric("Total Minimum Payments", format_cad(total_min))
m3.metric("Interest This Month", format_cad(monthly_interest_cost))

st.divider()

# --- Minimum payment editor ------------------------------------------------
st.subheader("Set minimum monthly payments")
st.caption(
    "Enter each debt's required minimum. For credit cards, this is "
    "usually around 2–3% of the owed amount (or a floor like $10)."
)

with st.form("min_payments_form"):
    inputs: dict[int, str] = {}
    for d in debts:
        st.markdown(
            f"**{d.name}** ({d.type}) — Owed: {format_cad(-d.balance)} "
            f"@ {d.interest_rate}%"
        )
        inputs[d.id] = st.text_input(
            "Minimum monthly payment (CAD)",
            value=str(d.min_payment or "0"),
            key=f"minpay_{d.id}",
            label_visibility="collapsed",
        )
        st.write("")
    save = st.form_submit_button("Save minimum payments", type="primary")

if save:
    errors: list[str] = []
    parsed: dict[int, Decimal] = {}
    for debt_id, raw in inputs.items():
        raw = raw.strip() or "0"
        try:
            val = to_money(raw)
            if val < ZERO:
                errors.append(f"Min payment for debt #{debt_id} can't be negative.")
            else:
                parsed[debt_id] = val
        except Exception:
            errors.append(f"Min payment for debt #{debt_id} must be a number.")
    if errors:
        for e in errors:
            st.error(e)
    else:
        with SessionLocal() as session:
            for debt_id, val in parsed.items():
                acc = session.get(Account, debt_id)
                acc.min_payment = val
            session.commit()
        st.success("Minimum payments saved.")
        st.rerun()

st.divider()

# --- Simulator -------------------------------------------------------------
st.subheader("Payoff simulator")

extra_str = st.text_input(
    "Extra money toward debt per month (CAD)",
    value="0.00",
    help=(
        "On top of the minimums. The higher this is, the faster you "
        "become debt-free."
    ),
)

try:
    extra = to_money(extra_str)
except Exception:
    st.error("Extra amount must be a number.")
    st.stop()

if extra < ZERO:
    st.error("Extra can't be negative.")
    st.stop()

sim_inputs = [
    DebtIn(
        name=d.name,
        balance=-d.balance,
        annual_rate=d.interest_rate,
        min_payment=d.min_payment or ZERO,
    )
    for d in debts
]

if total_min == ZERO and extra == ZERO:
    st.warning(
        "All minimums are 0 and you've allocated no extra. Nothing will "
        "be paid down. Set minimums above OR enter an extra amount."
    )
    st.stop()

snowball = simulate(sim_inputs, extra, "snowball")
avalanche = simulate(sim_inputs, extra, "avalanche")

col1, col2 = st.columns(2)
with col1:
    st.markdown("### Snowball")
    st.caption("Smallest balance first — momentum strategy.")
    if snowball.months >= 600:
        st.error("Debts don't pay off within 50 years at this rate.")
    else:
        st.metric("Months to debt-free", snowball.months)
        st.metric(
            "Debt-free date",
            _months_to_date(snowball.months).strftime("%b %Y"),
        )
        st.metric("Total interest paid", format_cad(snowball.total_interest_paid))

with col2:
    st.markdown("### Avalanche")
    st.caption("Highest interest rate first — math-optimal strategy.")
    if avalanche.months >= 600:
        st.error("Debts don't pay off within 50 years at this rate.")
    else:
        st.metric("Months to debt-free", avalanche.months)
        st.metric(
            "Debt-free date",
            _months_to_date(avalanche.months).strftime("%b %Y"),
        )
        st.metric("Total interest paid", format_cad(avalanche.total_interest_paid))

# Recommendation
if snowball.months < 600 and avalanche.months < 600:
    diff = snowball.total_interest_paid - avalanche.total_interest_paid
    if diff > ZERO:
        st.success(
            f"**Avalanche saves {format_cad(diff)} in interest.** "
            "Snowball pays off the smallest debt first, which some people "
            "find more motivating — pick whichever you'll actually stick with."
        )
    elif diff < ZERO:
        st.info(
            f"Snowball saves {format_cad(-diff)} in interest in this scenario "
            "(unusual but possible when balances and rates line up). "
            "Either strategy works."
        )
    else:
        st.info("Both strategies cost the same in interest — pick based on motivation.")

# --- Chart -----------------------------------------------------------------
if snowball.months < 600 and avalanche.months < 600:
    st.divider()
    st.subheader("Debt over time")
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=list(range(1, len(snowball.monthly_total) + 1)),
            y=[float(v) for v in snowball.monthly_total],
            name="Snowball",
            line=dict(color="#ff7f0e"),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=list(range(1, len(avalanche.monthly_total) + 1)),
            y=[float(v) for v in avalanche.monthly_total],
            name="Avalanche",
            line=dict(color="#1f77b4"),
        )
    )
    fig.update_layout(
        xaxis_title="Months from now",
        yaxis_title="Total debt remaining (CAD)",
        hovermode="x unified",
    )
    st.plotly_chart(fig, width="stretch")

# --- Per-debt status & payment history ------------------------------------
st.divider()
st.subheader("Per-debt status")
st.caption(
    "What you owe on each debt, what you've actually paid this month, and "
    "how long until each is gone (avalanche strategy). 'Paid' counts incoming "
    "transfers to the debt account — make a Transfer in **Transactions** "
    "from chequing to the debt to record a payment."
)

with SessionLocal() as session:
    summary_rows = []
    for d in debts:
        paid_this_month = payments_to_account(
            session, d.id, today.year, today.month
        )
        months_to_payoff = avalanche.payoff_month_by_debt.get(d.name)
        if months_to_payoff and months_to_payoff < 600:
            payoff_str = f"{months_to_payoff} mo"
            payoff_date_str = _months_to_date(months_to_payoff).strftime("%b %Y")
        else:
            payoff_str = "—"
            payoff_date_str = "—"
        min_pay = d.min_payment or ZERO
        diff = paid_this_month - min_pay
        if min_pay > ZERO and paid_this_month >= min_pay:
            status = f"✓ +{format_cad(diff)}"
        elif min_pay > ZERO and paid_this_month > ZERO:
            status = f"⚠ short by {format_cad(-diff)}"
        elif min_pay > ZERO and paid_this_month == ZERO:
            status = "✗ not paid yet"
        else:
            status = "—"
        summary_rows.append(
            {
                "Debt": d.name,
                "Type": d.type,
                "Owed": format_cad(-d.balance),
                "Rate %": str(d.interest_rate),
                "Min/month": format_cad(min_pay),
                "Paid this month": format_cad(paid_this_month),
                "Status vs min": status,
                "Months to payoff": payoff_str,
                "Est. payoff date": payoff_date_str,
            }
        )

st.dataframe(pd.DataFrame(summary_rows), hide_index=True, width="stretch")

# 6-month payment history per debt
st.subheader("Payment history (last 6 months)")
debt_pick = st.selectbox(
    "Show history for:",
    options=debts,
    format_func=lambda d: d.name,
    key="debt_history_pick",
)

if debt_pick is not None:
    with SessionLocal() as session:
        history = payment_history(session, debt_pick.id, n_months=6)

    months_labels = [f"{calendar.month_abbr[m]} {y}" for y, m, _ in history]
    paid_values = [float(p) for _, _, p in history]
    min_val = float(debt_pick.min_payment or 0)

    if min_val > 0:
        bar_colors = [
            "#2ecc71" if p >= min_val else "#f39c12" for p in paid_values
        ]
    else:
        bar_colors = ["#3498db"] * len(paid_values)

    fig_hist = go.Figure()
    fig_hist.add_trace(
        go.Bar(
            name="Paid",
            x=months_labels,
            y=paid_values,
            marker_color=bar_colors,
            hovertemplate="%{x}<br>Paid: $%{y:,.2f}<extra></extra>",
        )
    )
    if min_val > 0:
        fig_hist.add_trace(
            go.Scatter(
                name="Minimum",
                x=months_labels,
                y=[min_val] * len(months_labels),
                mode="lines",
                line=dict(color="#e74c3c", dash="dash", width=2),
                hovertemplate="Min: $%{y:,.2f}<extra></extra>",
            )
        )
    fig_hist.update_layout(
        height=320,
        margin=dict(l=20, r=20, t=40, b=20),
        title=(
            f"{debt_pick.name} — green bars met the minimum, "
            "orange bars fell short"
            if min_val > 0
            else f"{debt_pick.name} — no minimum set"
        ),
        yaxis=dict(tickprefix="$", separatethousands=True),
        showlegend=True,
    )
    st.plotly_chart(fig_hist, width="stretch")

# --- Payoff order ----------------------------------------------------------
st.divider()
strategy_pick = st.radio(
    "Payoff order for:",
    options=["Avalanche", "Snowball"],
    horizontal=True,
)
chosen = avalanche if strategy_pick == "Avalanche" else snowball

if chosen.payoff_month_by_debt:
    order = sorted(chosen.payoff_month_by_debt.items(), key=lambda x: x[1])
    rows = []
    for i, (name, m) in enumerate(order, start=1):
        rows.append(
            {
                "#": i,
                "Debt": name,
                "Paid off in": f"{m} months",
                "Estimated date": _months_to_date(m).strftime("%b %Y"),
            }
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
