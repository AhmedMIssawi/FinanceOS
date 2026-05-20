"""Budgets — monthly category limits with spent/remaining progress."""
import calendar
from datetime import date
from decimal import Decimal

import streamlit as st

from core.budgets_service import (
    copy_budgets,
    get_budgets,
    get_spent_by_category,
    upsert_budget,
)
from core.categories import CATEGORIES, INCOME_CATEGORY
from core.db import SessionLocal, init_db
from core.money import ZERO, format_cad, to_money

init_db()

st.set_page_config(page_title="Budgets | FinanceOS", layout="wide")
st.title("Budgets")
st.caption(
    "Monthly spending limits per category. Setting a budget to 0 removes it. "
    "Watch the progress bars to catch overspending before it gets out of hand."
)

# --- Month picker -----------------------------------------------------------
today = date.today()
pcol1, pcol2 = st.columns(2)
with pcol1:
    year = int(
        st.number_input(
            "Year", value=today.year, min_value=2020, max_value=2100, step=1
        )
    )
with pcol2:
    month = st.selectbox(
        "Month",
        options=list(range(1, 13)),
        format_func=lambda m: calendar.month_name[m],
        index=today.month - 1,
    )

prev_y, prev_m = (year - 1, 12) if month == 1 else (year, month - 1)
copy_clicked = st.button(
    f"Fill empty budgets from {calendar.month_name[prev_m]} {prev_y}",
    help="Copies budgets from the previous month — only for categories you haven't already set this month.",
)

# --- Load current state -----------------------------------------------------
with SessionLocal() as session:
    budgets = get_budgets(session, year, month)
    spent = get_spent_by_category(session, year, month)

# --- Copy action ------------------------------------------------------------
if copy_clicked:
    with SessionLocal() as session:
        count = copy_budgets(
            session,
            from_year=prev_y,
            from_month=prev_m,
            to_year=year,
            to_month=month,
        )
    if count == 0:
        st.info(
            f"Nothing to copy from {calendar.month_name[prev_m]} {prev_y} "
            "(either no budgets there, or this month already has them all set)."
        )
    else:
        st.success(
            f"Copied {count} budget(s) from {calendar.month_name[prev_m]} {prev_y}."
        )
        st.rerun()

# --- Top summary ------------------------------------------------------------
total_budget = sum(budgets.values(), ZERO)
total_spent = sum(spent.values(), ZERO)
remaining = total_budget - total_spent
if total_budget > ZERO:
    used_pct = (total_spent / total_budget * Decimal("100")).quantize(Decimal("0.1"))
else:
    used_pct = ZERO

sc1, sc2, sc3, sc4 = st.columns(4)
sc1.metric("Total Budget", format_cad(total_budget))
sc2.metric("Total Spent", format_cad(total_spent))
sc3.metric("Remaining", format_cad(remaining))
sc4.metric("Used", f"{used_pct}%" if total_budget > ZERO else "—")

st.divider()

# --- Per-category editor + progress -----------------------------------------
st.subheader(f"{calendar.month_name[month]} {year} — by category")

# Income isn't a budget category (you don't cap income).
budget_cats = [c for c in CATEGORIES.keys() if c != INCOME_CATEGORY]


def _safe_key(name: str) -> str:
    return name.replace(" ", "_").lower()


with st.form("budgets_form"):
    inputs: dict[str, str] = {}

    for cat in budget_cats:
        current = budgets.get(cat, ZERO)
        spent_amt = spent.get(cat, ZERO)

        st.markdown(f"**{cat}**")
        ccol1, ccol2 = st.columns([1, 3])

        with ccol1:
            inputs[cat] = st.text_input(
                "Budget (CAD)",
                value=str(current),
                key=f"budget_input_{_safe_key(cat)}",
                label_visibility="collapsed",
                placeholder="0.00",
            )

        with ccol2:
            if current > ZERO:
                pct_dec = (spent_amt / current * Decimal("100")).quantize(
                    Decimal("0.1")
                )
                pct_for_bar = min(float(pct_dec) / 100, 1.0)
                label = (
                    f"{format_cad(spent_amt)} / {format_cad(current)} "
                    f"({pct_dec}%)"
                )
                st.progress(pct_for_bar, text=label)
                if spent_amt > current:
                    st.error(f"Over budget by {format_cad(spent_amt - current)}")
                elif pct_dec >= Decimal("80"):
                    st.warning(f"{pct_dec}% used — watch out.")
            else:
                if spent_amt > ZERO:
                    st.warning(
                        f"Spent {format_cad(spent_amt)} with no budget set."
                    )
                else:
                    st.caption("No budget set, no spending this month.")

        st.write("")  # vertical spacer

    save = st.form_submit_button("Save Budgets", type="primary")

# --- Save action ------------------------------------------------------------
if save:
    parsed: dict[str, Decimal] = {}
    errors: list[str] = []

    for cat, raw in inputs.items():
        raw = raw.strip() or "0"
        try:
            val = to_money(raw)
            if val < ZERO:
                errors.append(f"{cat}: budget can't be negative.")
            else:
                parsed[cat] = val
        except Exception:
            errors.append(f"{cat}: '{raw}' isn't a valid amount.")

    if errors:
        for e in errors:
            st.error(e)
    else:
        with SessionLocal() as session:
            for cat, limit in parsed.items():
                upsert_budget(
                    session,
                    year=year,
                    month=month,
                    category=cat,
                    limit_amount=limit,
                )
        st.success(f"Budgets saved for {calendar.month_name[month]} {year}.")
        st.rerun()
