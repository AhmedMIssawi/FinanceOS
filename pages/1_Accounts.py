"""Accounts — chequing, savings, credit cards, cash, financing, loans.

Type-specific input behaviour:
- credit: enter credit_limit + available_funds; balance is computed.
- loan:   pick direction + friend's name + outstanding amount; name and
          sign are composed automatically.
- other:  type the balance directly (negative for debts).

UX: each accounts table supports single-row selection — click any row
to open its edit form below.
"""
from decimal import Decimal

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import select

from core.coins_service import (
    COIN_DENOMINATIONS,
    breakdown_summary,
    breakdown_total,
    parse_breakdown,
    serialize_breakdown,
)
from core.dashboard_service import accounts_with_missing_rates
from core.db import SessionLocal, init_db
from core.exchange_service import get_rate
from core.models import ACCOUNT_TYPES, Account
from core.money import (
    CURRENCIES,
    ZERO,
    active_currency_code,
    format_cad,
    format_money,
    to_money,
)

init_db()

st.set_page_config(page_title="Accounts | FinanceOS", layout="wide")
st.title("Accounts")
st.caption(
    "Bank, savings, cash, financing, loans, and credit cards. The form "
    "adapts to the type so you never have to remember which way a "
    "negative number goes."
)


def load_accounts() -> list[Account]:
    with SessionLocal() as session:
        return list(
            session.scalars(
                select(Account)
                .where(~Account.archived)
                .order_by(Account.name)
            ).all()
        )


def _utilization(limit: Decimal, owed: Decimal) -> Decimal:
    if limit <= ZERO:
        return ZERO
    return (owed / limit * Decimal("100")).quantize(Decimal("0.1"))


def _format_converted(
    amount: Decimal, account_currency: str, active: str, session
) -> str:
    """Format `amount` converted from `account_currency` to `active`.

    When currencies match, this just formats in the active currency (and
    the calling table can still show it so each row has a consistent
    "what it contributes to the KPI" cell). When the rate is missing,
    returns "—" instead of a number — caller decides whether to surface
    that as a warning.
    """
    if account_currency == active:
        return format_money(amount, active)
    rate = get_rate(session, account_currency, active)
    if rate is None:
        return "—"
    return format_money(amount * rate, active)


accounts = load_accounts()

# Convert every account's balance into the active display currency so the
# KPI cards show a single coherent number — even when accounts span
# multiple currencies. Accounts missing an exchange rate are surfaced
# below the cards as a warning, NOT silently dropped from the user's
# attention.
active = active_currency_code()
with SessionLocal() as _session:
    converted_balances: list[Decimal] = []
    missing: list[Account] = []
    for a in accounts:
        if a.currency == active:
            converted_balances.append(a.balance)
        else:
            rate = get_rate(_session, a.currency, active)
            if rate is None:
                missing.append(a)
            else:
                converted_balances.append(a.balance * rate)

total_assets = sum((b for b in converted_balances if b > ZERO), ZERO)
total_liab = sum((b for b in converted_balances if b < ZERO), ZERO)
net_worth_total = sum(converted_balances, ZERO)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Accounts", len(accounts))
c2.metric(f"Assets ({active})", format_money(total_assets))
c3.metric(f"Liabilities ({active})", format_money(total_liab))
c4.metric(f"Net Worth ({active})", format_money(net_worth_total))

if missing:
    names = ", ".join(f"{m.name} ({m.currency})" for m in missing)
    st.warning(
        f"Couldn't convert {len(missing)} account(s) to {active}: {names}. "
        "Their balances are missing from the KPIs above. Fix by opening "
        "**Settings → Exchange rates → Refresh rates now**."
    )

st.divider()

# --- Add account form -------------------------------------------------------
st.subheader("Add a new account")

new_type = st.selectbox("Type *", ACCOUNT_TYPES, key="add_acct_type")
is_credit_add = new_type == "credit"
is_loan_add = new_type == "loan"
is_coins_add = new_type == "coins"

# Currency picker for the new account. Locked to CAD for coins accounts
# (the denomination grid is Canadian); free choice for everything else.
if is_coins_add:
    new_currency_add = "CAD"
    st.caption(
        ":grey[Coins accounts are CAD-only — the denomination grid uses Canadian coins.]"
    )
else:
    new_currency_add = st.selectbox(
        "Currency *",
        list(CURRENCIES.keys()),
        index=list(CURRENCIES.keys()).index(active_currency_code()),
        key="add_acct_currency",
        help=(
            "The currency this account is denominated in. Balances are "
            "stored as-is; cross-currency totals use the latest stored "
            "exchange rate."
        ),
    )

with st.form("add_account_form", clear_on_submit=True):
    if is_loan_add:
        loan_friend_name = st.text_input(
            "Friend's name *",
            placeholder="e.g. John",
            help=(
                "One loan account per person. The account name is composed "
                "automatically as 'Loan to <name>' or 'Loan from <name>'."
            ),
        )
        loan_to_me = st.checkbox(
            "This loan is TO ME — I borrowed from them and will pay them back",
            help="Leave unchecked if you lent money to them.",
        )
        new_name = ""
    else:
        new_name = st.text_input(
            "Name *", placeholder="e.g. TD Chequing or Visa - TD"
        )

    add_coin_inputs: dict[str, int] = {}

    if is_credit_add:
        cc1, cc2 = st.columns(2)
        with cc1:
            new_limit_str = st.text_input(
                "Credit limit (CAD) *",
                value="0.00",
                help="The maximum the card lets you charge.",
            )
        with cc2:
            new_avail_str = st.text_input(
                "Available funds now (CAD) *",
                value="0.00",
                help="How much room you still have. Owed = limit − available.",
            )
        new_balance_str = ""
        new_amount_str = ""
    elif is_loan_add:
        new_amount_str = st.text_input(
            "Amount outstanding (CAD) *",
            value="0.00",
            help="How much is still owed right now. Enter a positive number — the app applies the sign.",
        )
        new_balance_str = ""
        new_limit_str = ""
        new_avail_str = ""
    elif is_coins_add:
        st.markdown(
            "**Coin breakdown** — these counts set the account balance. "
            "Update them whenever you recount."
        )
        cb1, cb2 = st.columns(2)
        for i, (short, sym, value) in enumerate(COIN_DENOMINATIONS):
            target_col = cb1 if i % 2 == 0 else cb2
            with target_col:
                add_coin_inputs[str(value)] = st.number_input(
                    f"{short} ({sym})",
                    min_value=0,
                    value=0,
                    step=1,
                    key=f"add_coin_{value}",
                )
        live_total = breakdown_total(add_coin_inputs)
        st.info(f"Balance from counts: **{format_cad(live_total)}**")
        new_balance_str = ""
        new_limit_str = ""
        new_avail_str = ""
        new_amount_str = ""
    else:
        new_balance_str = st.text_input(
            "Balance (CAD) *",
            value="0.00",
            help="Use a negative number for debt accounts (overdraft, financing).",
        )
        new_limit_str = ""
        new_avail_str = ""
        new_amount_str = ""

    rc1, rc2 = st.columns(2)
    with rc1:
        new_inst = st.text_input("Institution", placeholder="e.g. TD Bank")
    with rc2:
        new_rate_str = st.text_input(
            "Interest rate %",
            value="0.00",
            help="Annual rate. Leave at 0 for interest-free loans between friends.",
        )
    new_notes = st.text_area("Notes", height=70)
    submitted = st.form_submit_button("Add Account", type="primary")

if submitted:
    error_msg: str | None = None
    bal: Decimal | None = None
    credit_limit_value: Decimal | None = None
    actual_name: str = ""
    rate: Decimal | None = None

    try:
        if is_loan_add:
            friend = loan_friend_name.strip()
            if not friend:
                raise ValueError("Friend's name is required.")
            amt = to_money(new_amount_str)
            if amt <= ZERO:
                raise ValueError("Loan amount must be positive.")
            if loan_to_me:
                actual_name = f"Loan from {friend}"
                bal = -amt
            else:
                actual_name = f"Loan to {friend}"
                bal = amt
        elif is_credit_add:
            limit = to_money(new_limit_str)
            avail = to_money(new_avail_str)
            if limit <= ZERO:
                raise ValueError("Credit limit must be positive.")
            if avail < ZERO:
                raise ValueError("Available funds can't be negative.")
            if avail > limit:
                raise ValueError("Available funds can't exceed the credit limit.")
            bal = to_money(avail - limit)
            credit_limit_value = limit
            actual_name = new_name.strip()
        elif is_coins_add:
            # Balance is derived from the denomination grid — there is no
            # separate Balance input for coins.
            bal = to_money(breakdown_total(add_coin_inputs))
            actual_name = new_name.strip()
        else:
            bal = to_money(new_balance_str)
            actual_name = new_name.strip()

        rate = to_money(new_rate_str.strip() or "0")
    except ValueError as e:
        error_msg = str(e)
    except Exception:
        error_msg = "Numeric fields must be plain numbers (e.g. 1234.56 or -50.00)."

    if error_msg:
        st.error(error_msg)
    elif not actual_name:
        st.error("Name is required.")
    else:
        with SessionLocal() as session:
            if session.scalar(select(Account).where(Account.name == actual_name)):
                st.error(f"'{actual_name}' already exists.")
            else:
                session.add(
                    Account(
                        name=actual_name,
                        type=new_type,
                        currency=new_currency_add,
                        balance=bal,
                        credit_limit=credit_limit_value,
                        interest_rate=rate,
                        institution=(new_inst.strip() or None),
                        notes=(new_notes.strip() or None),
                        coin_breakdown=(
                            serialize_breakdown(add_coin_inputs)
                            if is_coins_add
                            else None
                        ),
                    )
                )
                session.commit()
                st.success(f"Added: {actual_name}")
                st.rerun()

st.divider()

# --- Display: credit cards / loans / coins / other (each row-selectable) ---
credit_accounts = [a for a in accounts if a.type == "credit"]
loan_accounts = [a for a in accounts if a.type == "loan"]
coins_accounts = [a for a in accounts if a.type == "coins"]
other_accounts = [
    a for a in accounts if a.type not in ("credit", "loan", "coins")
]

selected_account: Account | None = None

if credit_accounts:
    st.subheader("Credit cards")
    st.caption(
        "Click a row to edit or delete it. 'Owed in <active>' is the "
        "converted contribution to the Liabilities KPI above."
    )
    needs_conv_credit = any(a.currency != active for a in credit_accounts)
    with SessionLocal() as _s:
        rows = []
        for a in credit_accounts:
            limit = a.credit_limit or ZERO
            owed = -a.balance if a.balance < ZERO else ZERO
            available = limit + a.balance
            row = {
                "Name": a.name,
                "Currency": a.currency,
                "Limit": format_money(limit, a.currency),
                "Available": format_money(available, a.currency),
                "Owed": format_money(owed, a.currency),
            }
            if needs_conv_credit:
                row[f"Owed in {active}"] = _format_converted(
                    owed, a.currency, active, _s
                )
            row.update(
                {
                    "Utilization %": f"{_utilization(limit, owed)}%",
                    "Interest %": str(a.interest_rate),
                    "Institution": a.institution or "",
                }
            )
            rows.append(row)
    credit_event = st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        key="credit_tbl",
    )
    if credit_event.selection.rows:
        idx = credit_event.selection.rows[0]
        if idx < len(credit_accounts):
            selected_account = credit_accounts[idx]

if loan_accounts:
    st.subheader("Loans")
    st.caption(
        "Click a row to edit or delete it. 'In <active>' is the "
        "converted contribution to the Net Worth KPI above."
    )
    needs_conv_loan = any(a.currency != active for a in loan_accounts)
    with SessionLocal() as _s:
        rows = []
        for a in loan_accounts:
            if a.balance > ZERO:
                direction = "Owed to you"
            elif a.balance < ZERO:
                direction = "You owe"
            else:
                direction = "Paid off"
            row = {
                "Name": a.name,
                "Currency": a.currency,
                "Direction": direction,
                "Amount": format_money(abs(a.balance), a.currency),
            }
            if needs_conv_loan:
                row[f"In {active}"] = _format_converted(
                    abs(a.balance), a.currency, active, _s
                )
            row.update(
                {
                    "Interest %": str(a.interest_rate),
                    "Notes": a.notes or "",
                }
            )
            rows.append(row)
    loan_event = st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        key="loan_tbl",
    )
    if loan_event.selection.rows:
        idx = loan_event.selection.rows[0]
        if idx < len(loan_accounts):
            selected_account = loan_accounts[idx]

if coins_accounts:
    st.subheader("Coins accounts")
    st.caption(
        "Click a row to edit, update the denomination breakdown, and see a "
        "chart of what's inside. The breakdown is informational only — it "
        "never affects the Balance number on its own."
    )
    needs_conv_coins = any(a.currency != active for a in coins_accounts)
    with SessionLocal() as _s:
        rows = []
        for a in coins_accounts:
            bd = parse_breakdown(a.coin_breakdown)
            row = {
                "Name": a.name,
                "Currency": a.currency,
                "Balance": format_money(a.balance, a.currency),
            }
            if needs_conv_coins:
                row[f"In {active}"] = _format_converted(
                    a.balance, a.currency, active, _s
                )
            row.update(
                {
                    "Breakdown": breakdown_summary(bd),
                    "Breakdown sum": format_money(
                        breakdown_total(bd), a.currency
                    ),
                }
            )
            rows.append(row)
    coins_event = st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        key="coins_tbl",
    )
    if coins_event.selection.rows:
        idx = coins_event.selection.rows[0]
        if idx < len(coins_accounts):
            selected_account = coins_accounts[idx]

if other_accounts:
    st.subheader("Other accounts")
    st.caption(
        "Click a row to edit or delete it. 'In <active>' is the "
        "converted contribution to the Net Worth KPI above."
    )
    needs_conv_other = any(a.currency != active for a in other_accounts)
    with SessionLocal() as _s:
        rows = []
        for a in other_accounts:
            row = {
                "Name": a.name,
                "Type": a.type,
                "Currency": a.currency,
                "Balance": format_money(a.balance, a.currency),
            }
            if needs_conv_other:
                row[f"In {active}"] = _format_converted(
                    a.balance, a.currency, active, _s
                )
            row.update(
                {
                    "Interest %": str(a.interest_rate),
                    "Institution": a.institution or "",
                    "Notes": a.notes or "",
                }
            )
            rows.append(row)
    other_event = st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        key="other_tbl",
    )
    if other_event.selection.rows:
        idx = other_event.selection.rows[0]
        if idx < len(other_accounts):
            selected_account = other_accounts[idx]

if not accounts:
    st.info("No accounts yet — add your first one above.")

# --- Inline edit / delete for the selected account --------------------------
if selected_account is not None:
    target = selected_account
    st.divider()
    st.markdown(f"**Editing account: {target.name}** (#{target.id})")

    edit_type = st.selectbox(
        "Type",
        ACCOUNT_TYPES,
        index=ACCOUNT_TYPES.index(target.type),
        key=f"edit_acct_type_{target.id}",
    )
    is_credit_edit = edit_type == "credit"
    is_coins_edit = edit_type == "coins"

    # Currency picker for edits. Coins accounts are forced back to CAD
    # (changing type to coins always means CAD, no exceptions).
    if is_coins_edit:
        edit_currency = "CAD"
        st.caption(":grey[Coins accounts are CAD-only.]")
    else:
        edit_currency = st.selectbox(
            "Currency",
            list(CURRENCIES.keys()),
            index=list(CURRENCIES.keys()).index(
                target.currency if target.currency in CURRENCIES else "CAD"
            ),
            key=f"edit_currency_{target.id}",
        )

    # When editing a coins account, render the breakdown CHART above the
    # form using the SAVED data (form changes haven't been committed yet).
    # Donut chart sized by VALUE — slice size reflects each denomination's
    # dollar contribution, not just count, so a few toonies dominate over
    # many nickels (which is the financially meaningful view).
    if is_coins_edit:
        saved_bd = parse_breakdown(target.coin_breakdown)
        if any(saved_bd.values()):
            labels: list[str] = []
            slice_values: list[float] = []
            for short, _, value in COIN_DENOMINATIONS:
                count = int(saved_bd.get(str(value), 0))
                if count > 0:
                    labels.append(f"{short} × {count}")
                    slice_values.append(float(value * Decimal(count)))

            fig_bd = go.Figure(
                go.Pie(
                    labels=labels,
                    values=slice_values,
                    hole=0.4,
                    textinfo="label+percent",
                    hovertemplate=(
                        "<b>%{label}</b>"
                        "<br>Value: $%{value:.2f}"
                        "<br>%{percent} of total"
                        "<extra></extra>"
                    ),
                )
            )
            fig_bd.update_layout(
                title=f"Coin breakdown — {target.name}",
                height=380,
                margin=dict(l=20, r=20, t=50, b=20),
                showlegend=True,
            )
            st.plotly_chart(fig_bd, width="stretch")
        else:
            st.info(
                "No coin breakdown saved yet. Fill in the counts below and save."
            )

    with st.form(f"edit_account_form_{target.id}"):
        edit_name = st.text_input("Name", value=target.name)

        if is_credit_edit:
            target_limit = target.credit_limit or ZERO
            target_avail = (
                target_limit + target.balance if target_limit > ZERO else ZERO
            )
            ec1, ec2 = st.columns(2)
            with ec1:
                edit_limit_str = st.text_input(
                    "Credit limit (CAD)", value=str(target_limit)
                )
            with ec2:
                edit_avail_str = st.text_input(
                    "Available funds now (CAD)", value=str(target_avail)
                )
            edit_balance_str = ""
        elif is_coins_edit:
            # No Balance input — balance is derived from the denomination
            # grid further down. Show the current value as info.
            st.info(
                f"Balance derives from the denomination counts below. "
                f"Current saved balance: **{format_cad(target.balance)}**"
            )
            edit_balance_str = ""
            edit_limit_str = ""
            edit_avail_str = ""
        else:
            edit_balance_str = st.text_input("Balance", value=str(target.balance))
            edit_limit_str = ""
            edit_avail_str = ""

        # Coin denomination breakdown editor (only for type=coins).
        # For coins, this IS the balance — saving recomputes balance from these counts.
        coin_breakdown_inputs: dict[str, int] = {}
        if is_coins_edit:
            st.markdown(
                "**Coin breakdown** — the balance is set from these counts on Save."
            )
            saved_bd = parse_breakdown(target.coin_breakdown)
            cb_col_a, cb_col_b = st.columns(2)
            for i, (short, sym, value) in enumerate(COIN_DENOMINATIONS):
                target_col = cb_col_a if i % 2 == 0 else cb_col_b
                with target_col:
                    coin_breakdown_inputs[str(value)] = st.number_input(
                        f"{short} ({sym})",
                        min_value=0,
                        value=int(saved_bd.get(str(value), 0)),
                        step=1,
                        key=f"edit_coin_{value}_{target.id}",
                    )
            wip_total = breakdown_total(coin_breakdown_inputs)
            st.success(
                f"**New balance on save: {format_cad(wip_total)}**"
            )

        ec3, ec4 = st.columns(2)
        with ec3:
            edit_inst = st.text_input("Institution", value=target.institution or "")
        with ec4:
            edit_rate = st.text_input("Interest %", value=str(target.interest_rate))
        edit_notes = st.text_area("Notes", value=target.notes or "", height=70)
        confirm_delete = st.checkbox(
            "Yes, delete this account (also deletes all its transactions)"
        )
        sc, dc = st.columns(2)
        with sc:
            save = st.form_submit_button("Save changes", type="primary")
        with dc:
            delete = st.form_submit_button("Delete account")

    if save:
        try:
            if is_credit_edit:
                limit = to_money(edit_limit_str)
                avail = to_money(edit_avail_str)
                if limit <= ZERO:
                    raise ValueError("Credit limit must be positive.")
                if avail < ZERO:
                    raise ValueError("Available funds can't be negative.")
                if avail > limit:
                    raise ValueError("Available funds can't exceed the credit limit.")
                new_balance = to_money(avail - limit)
                new_credit_limit = limit
            elif is_coins_edit:
                # Coins balance is fully derived from the denomination grid.
                new_balance = to_money(breakdown_total(coin_breakdown_inputs))
                new_credit_limit = None
            else:
                new_balance = to_money(edit_balance_str)
                new_credit_limit = None
            new_rate = to_money(edit_rate)
        except ValueError as e:
            st.error(str(e))
        except Exception:
            st.error("Numeric fields must be plain numbers.")
        else:
            with SessionLocal() as session:
                acc = session.get(Account, target.id)
                acc.name = edit_name.strip()
                acc.type = edit_type
                acc.currency = edit_currency
                acc.balance = new_balance
                acc.credit_limit = new_credit_limit
                acc.interest_rate = new_rate
                acc.institution = edit_inst.strip() or None
                acc.notes = edit_notes.strip() or None
                # Persist coin breakdown only for coins-type accounts.
                if is_coins_edit:
                    acc.coin_breakdown = serialize_breakdown(coin_breakdown_inputs)
                else:
                    acc.coin_breakdown = None
                session.commit()
                # If the balance crossed zero on a loan/financing edit, trigger
                # auto-archive (handles users who clear a debt via direct edit
                # rather than via Debt Payments).
                from core.archive_service import reconcile_archive
                reconcile_archive(session, acc)
            st.success("Saved.")
            st.rerun()

    if delete:
        if not confirm_delete:
            st.warning("Tick the confirmation box first.")
        else:
            with SessionLocal() as session:
                session.delete(session.get(Account, target.id))
                session.commit()
            st.success(f"Deleted: {target.name}")
            st.rerun()
