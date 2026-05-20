"""FinanceOS — Dashboard (home page).

Top-line view of your finances. Pulls live from Accounts, Transactions,
and Budgets. Data aggregation lives in core/dashboard_service.py — this
file is presentation only.
"""
import calendar
from datetime import date
from decimal import Decimal

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import select

from core.budgets_service import get_budgets, get_spent_by_category
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
from core.db import SessionLocal, init_db
from core.models import Account
from core.money import ZERO, format_cad
from core.settings_service import get_savings_target

init_db()

st.set_page_config(
    page_title="FinanceOS",
    page_icon=":bar_chart:",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("Dashboard")
today = date.today()
st.caption(
    f"Live snapshot for {today.strftime('%B %Y')}. Updates automatically as "
    "you add accounts and record transactions."
)

with SessionLocal() as session:
    accounts_list = list(session.scalars(select(Account)).all())
    if not accounts_list:
        st.info(
            "Welcome! Start by adding an account on the **Accounts** page "
            "(sidebar). Then record some transactions and your dashboard "
            "fills in automatically."
        )
        st.stop()

    nw = net_worth(session)
    td = total_debt(session)
    ca = cash_available(session)
    coins = coins_total(session)
    sav = savings_total(session)
    savings_target = get_savings_target(session)
    flow = cash_flow_last_n_months(session, n=6)
    spend_by_cat = spending_by_category(session, today.year, today.month)
    budgets = get_budgets(session, today.year, today.month)
    spent_for_budget = get_spent_by_category(session, today.year, today.month)
    top_subs = top_subcategories(session, today.year, today.month, limit=5)
    recent = recent_transactions(session, limit=10)
    account_map = {a.id: a for a in accounts_list}

# --- KPI row (Cash and Coins are intentionally side-by-side) --------------
k1, k2, k3, k4 = st.columns(4)
k1.metric("Net Worth", format_cad(nw))
k2.metric("Total Debt", format_cad(td))
k3.metric(
    "Cash",
    format_cad(ca),
    delta="chequing + savings + cash",
    delta_color="off",
)
k4.metric(
    "Coins",
    format_cad(coins),
    delta="physical coins",
    delta_color="off",
)

# --- Savings goal section (replaces old KPI slot, now its own labeled block)
st.divider()
sg1, sg2 = st.columns([1, 3])
with sg1:
    st.metric(
        "Savings Progress",
        format_cad(sav),
        delta=f"of {format_cad(savings_target)} target",
        delta_color="off",
    )
with sg2:
    if savings_target > ZERO:
        progress_pct_dec = (sav / savings_target * Decimal("100")).quantize(
            Decimal("0.1")
        )
        progress_pct_capped = min(float(progress_pct_dec) / 100, 1.0)
        st.write("")  # vertical alignment
        st.progress(
            progress_pct_capped,
            text=f"{format_cad(sav)} / {format_cad(savings_target)} "
            f"({progress_pct_dec}%)",
        )

st.divider()

# --- Cash flow chart ------------------------------------------------------
st.subheader("Cash flow — last 6 months")

flow_has_data = any(f.income > ZERO or f.expense > ZERO for f in flow)
if not flow_has_data:
    st.info("No income or expenses recorded in the last 6 months yet.")
else:
    months_labels = [f"{calendar.month_abbr[f.month]} {f.year}" for f in flow]
    fig_flow = go.Figure()
    fig_flow.add_trace(
        go.Bar(
            name="Income",
            x=months_labels,
            y=[float(f.income) for f in flow],
            marker_color="#2ecc71",
            hovertemplate="%{x}<br>Income: $%{y:,.2f}<extra></extra>",
        )
    )
    fig_flow.add_trace(
        go.Bar(
            name="Expenses",
            x=months_labels,
            y=[float(f.expense) for f in flow],
            marker_color="#e74c3c",
            hovertemplate="%{x}<br>Expenses: $%{y:,.2f}<extra></extra>",
        )
    )
    fig_flow.update_layout(
        barmode="group",
        height=350,
        margin=dict(l=20, r=20, t=20, b=20),
        yaxis=dict(tickprefix="$", separatethousands=True),
    )
    st.plotly_chart(fig_flow, width="stretch")

st.divider()

# --- Spending by category (pie) + Budget burn-rate ------------------------
sc1, sc2 = st.columns(2)

with sc1:
    st.subheader("Spending by category — this month")
    if not spend_by_cat:
        st.info("No expenses recorded this month yet.")
    else:
        fig_pie = go.Figure(
            data=[
                go.Pie(
                    labels=list(spend_by_cat.keys()),
                    values=[float(v) for v in spend_by_cat.values()],
                    hole=0.4,
                    hovertemplate="%{label}<br>$%{value:,.2f} (%{percent})<extra></extra>",
                )
            ]
        )
        fig_pie.update_layout(
            height=350, margin=dict(l=20, r=20, t=20, b=20), showlegend=True
        )
        st.plotly_chart(fig_pie, width="stretch")

with sc2:
    st.subheader("Budget burn-rate — this month")
    if not budgets:
        st.info(
            "No budgets set for this month. Add some on the **Budgets** page."
        )
    else:
        for cat, limit in budgets.items():
            spent = spent_for_budget.get(cat, ZERO)
            if limit > ZERO:
                pct_dec = (spent / limit * Decimal("100")).quantize(Decimal("0.1"))
                pct_for_bar = min(float(pct_dec) / 100, 1.0)
                st.write(
                    f"**{cat}** — {format_cad(spent)} / {format_cad(limit)} "
                    f"({pct_dec}%)"
                )
                st.progress(pct_for_bar)
                if spent > limit:
                    st.caption(f":red[Over by {format_cad(spent - limit)}]")
                elif pct_dec >= Decimal("80"):
                    st.caption(f":orange[{pct_dec}% used — watch out]")

st.divider()

# --- Top subcategories + Recent transactions -----------------------------
ts1, ts2 = st.columns(2)

with ts1:
    st.subheader("Top 5 spending — this month")
    if not top_subs:
        st.info("No spending this month yet.")
    else:
        fig_top = go.Figure(
            go.Bar(
                x=[float(amt) for _, amt in top_subs],
                y=[name for name, _ in top_subs],
                orientation="h",
                marker_color="#3498db",
                hovertemplate="%{y}<br>$%{x:,.2f}<extra></extra>",
            )
        )
        fig_top.update_layout(
            height=350,
            margin=dict(l=20, r=20, t=20, b=20),
            yaxis=dict(autorange="reversed"),
            xaxis=dict(tickprefix="$", separatethousands=True),
        )
        st.plotly_chart(fig_top, width="stretch")

with ts2:
    st.subheader("Recent transactions")
    if not recent:
        st.info("No transactions yet.")
    else:
        df = pd.DataFrame(
            [
                {
                    "Date": t.date,
                    "Account": account_map[t.account_id].name
                    if t.account_id in account_map
                    else "?",
                    "Category": t.category,
                    "Subcategory": t.subcategory,
                    "Amount": format_cad(t.amount),
                }
                for t in recent
            ]
        )
        st.dataframe(df, hide_index=True, width="stretch", height=350)
