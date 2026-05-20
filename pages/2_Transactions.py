"""Transactions — record expenses, income, account-to-account transfers,
and debt payments.

UX design notes:
- The existing-transactions table supports single-row selection — click
  any row to open its edit form below (or to delete a transfer/debt-payment).
- Picking Category="Debt Payments" in the Add form auto-converts the
  entry into a transfer to a real debt account (cascade dropdown).
  Otherwise paying $X for a credit card would just make money vanish
  from chequing without reducing the debt.
"""
from datetime import date as date_type

import pandas as pd
import streamlit as st
from sqlalchemy import select

from core.categories import category_names, is_income, subcategories_of
from core.db import SessionLocal, init_db
from core.models import Account, Transaction
from core.money import ZERO, format_cad, to_money
from core.transactions_service import (
    add_transaction,
    add_transfer,
    delete_transaction,
    update_transaction,
)

init_db()

st.set_page_config(page_title="Transactions | FinanceOS", layout="wide")
st.title("Transactions")

# One-shot flash message that survives st.rerun() — used for the
# auto-archive celebration when a debt payment closes out a loan/financing.
if "flash" in st.session_state:
    st.success(st.session_state.pop("flash"))

st.caption(
    "Record each expense or income. Enter a positive number — the app applies "
    "the sign based on category (Income = +, everything else = -). Picking "
    "**Debt Payments** as the category auto-routes the entry to a real debt "
    "account so both sides of the payment are recorded atomically."
)

# Maps "Debt Payments" subcategory -> which account types are valid targets.
# Defines what counts as a "Credit Card" / "Loan" / "Line of Credit" debt
# when the user picks that subcategory in the Add form.
DEBT_PAYMENT_TYPES = {
    "Credit Card": ("credit",),
    "Loan": ("loan", "financing"),
    "Line of Credit": ("overdraft",),
}


def load_all_accounts() -> list[Account]:
    """Every account, including archived. Used for resolving names in the
    transaction-history display so archived accounts still show as e.g.
    'Loan from Vansh' instead of '?'."""
    with SessionLocal() as session:
        return list(
            session.scalars(select(Account).order_by(Account.name)).all()
        )


def load_active_accounts(all_accounts: list[Account]) -> list[Account]:
    """The subset used to populate dropdowns where the user picks an
    account for a NEW transaction or transfer — archived accounts must
    not appear here because they're retired."""
    return [a for a in all_accounts if not a.archived]


def load_transactions() -> list[Transaction]:
    with SessionLocal() as session:
        return list(
            session.scalars(
                select(Transaction).order_by(
                    Transaction.date.desc(), Transaction.id.desc()
                )
            ).all()
        )


all_accounts = load_all_accounts()
accounts = load_active_accounts(all_accounts)  # for new-entry dropdowns

if not accounts:
    st.warning(
        "You need at least one active account before recording transactions. "
        "Open **Accounts** from the sidebar and add one (or un-archive one in Settings)."
    )
    st.stop()

# account_map covers ALL accounts (archived too) so the transaction list
# can still show "Loan from Vansh" instead of "?" for historical entries.
account_map = {a.id: a for a in all_accounts}
# acct_labels only contains active accounts — for picking a destination/source
# on new transactions or transfers.
acct_labels = {a.id: f"{a.name} ({a.type})" for a in accounts}

# --- Add transaction ---------------------------------------------------------
st.subheader("Add a transaction")

# Cascading category dropdowns live OUTSIDE the form (forms freeze widgets
# until submit, so a chained dropdown inside a form can't react).
ccol, scol = st.columns(2)
with ccol:
    add_cat = st.selectbox("Category", category_names(), key="add_cat")
with scol:
    add_sub = st.selectbox("Subcategory", subcategories_of(add_cat), key="add_sub")

# If the user is making a Debt Payment, pick the target debt account too.
is_debt_payment = add_cat == "Debt Payments"
debt_target_id: int | None = None
debt_payment_blocked = False

if is_debt_payment:
    allowed_types = DEBT_PAYMENT_TYPES.get(add_sub, ())
    eligible_debts = [
        a for a in accounts if a.type in allowed_types and a.balance < ZERO
    ]
    if not eligible_debts:
        st.warning(
            f"No '{add_sub}' debt accounts with a balance owing. "
            f"Add one on the **Accounts** page first, or pick a different subcategory."
        )
        debt_payment_blocked = True
    else:
        debt_target_id = st.selectbox(
            "Pay which debt?",
            options=[a.id for a in eligible_debts],
            format_func=lambda i: next(
                f"{a.name} — {format_cad(-a.balance)} owed"
                for a in eligible_debts
                if a.id == i
            ),
            key=f"add_debt_target_{add_sub}",
        )

with st.form("add_tx_form", clear_on_submit=True):
    c1, c2, c3 = st.columns(3)
    with c1:
        add_date = st.date_input("Date", value=date_type.today())
    with c2:
        # When making a debt payment, exclude the target debt account from
        # the source dropdown (can't pay a card from itself).
        source_options = [
            i for i in acct_labels.keys()
            if not is_debt_payment or i != debt_target_id
        ]
        add_account_id = st.selectbox(
            "From account" if is_debt_payment else "Account",
            options=source_options,
            format_func=lambda i: acct_labels[i],
        )
    with c3:
        add_amount = st.text_input("Amount (CAD)", value="0.00")
    add_notes = st.text_area("Notes", height=70)
    add_submit = st.form_submit_button(
        "Pay Debt" if is_debt_payment else "Add Transaction",
        type="primary",
        disabled=debt_payment_blocked,
    )

if add_submit:
    try:
        magnitude = to_money(add_amount)
    except Exception:
        st.error("Amount must be a number like 19.99.")
    else:
        if magnitude == ZERO:
            st.error("Amount can't be zero.")
        elif is_debt_payment:
            if debt_target_id is None:
                st.error("Pick which debt to pay.")
            elif add_account_id == debt_target_id:
                st.error("Source and target debt must be different.")
            else:
                with SessionLocal() as session:
                    add_transfer(
                        session,
                        from_account_id=add_account_id,
                        to_account_id=debt_target_id,
                        date=add_date,
                        amount=magnitude,
                        notes=(add_notes.strip() or None),
                        category="Debt Payments",
                        subcategory=add_sub,
                    )
                source_name = account_map[add_account_id].name
                target_name = account_map[debt_target_id].name
                # Re-check the target account in a fresh session — if it just
                # got auto-archived (balance hit $0 on a loan/financing), surface
                # the celebration via a flash message that survives the rerun.
                with SessionLocal() as session:
                    refreshed = session.get(Account, debt_target_id)
                    just_archived = bool(refreshed and refreshed.archived)
                if just_archived:
                    st.session_state["flash"] = (
                        f"🎉 {target_name} fully paid off and archived! "
                        "View the closing summary in Settings → Archived accounts."
                    )
                else:
                    st.session_state["flash"] = (
                        f"Paid {format_cad(magnitude)} from {source_name} → "
                        f"{target_name}. Debt reduced; source account drops by the same amount."
                    )
                st.rerun()
        else:
            with SessionLocal() as session:
                add_transaction(
                    session,
                    account_id=add_account_id,
                    date=add_date,
                    magnitude=magnitude,
                    category=add_cat,
                    subcategory=add_sub,
                    notes=(add_notes.strip() or None),
                )
            sign = "+" if is_income(add_cat) else "-"
            st.success(
                f"Recorded {sign}{format_cad(magnitude)} — {add_cat} / {add_sub}"
            )
            st.rerun()

st.divider()

# --- Transfer between accounts (for non-debt-payment moves) -----------------
st.subheader("Transfer between accounts")
st.caption(
    "For moves that aren't debt payments — depositing to savings, withdrawing "
    "cash, exchanging coins for bills, lending to a friend, etc. (For paying "
    "a debt, use the **Debt Payments** category in the form above — it does "
    "the same thing but auto-tags the transaction as a debt payment for analytics.)"
)

if len(accounts) < 2:
    st.info("Add at least two accounts to enable transfers.")
else:
    with st.form("transfer_form", clear_on_submit=True):
        tcol1, tcol2 = st.columns(2)
        with tcol1:
            transfer_from_id = st.selectbox(
                "From",
                options=list(acct_labels.keys()),
                format_func=lambda i: acct_labels[i],
                key="transfer_from",
            )
        with tcol2:
            transfer_to_id = st.selectbox(
                "To",
                options=list(acct_labels.keys()),
                format_func=lambda i: acct_labels[i],
                key="transfer_to",
                index=1 if len(acct_labels) > 1 else 0,
            )
        tcol3, tcol4 = st.columns(2)
        with tcol3:
            transfer_date = st.date_input(
                "Date", value=date_type.today(), key="transfer_date"
            )
        with tcol4:
            transfer_amount_str = st.text_input(
                "Amount (CAD)", value="0.00", key="transfer_amount"
            )
        transfer_notes = st.text_area("Notes", height=70, key="transfer_notes")
        transfer_submit = st.form_submit_button("Make Transfer", type="primary")

    if transfer_submit:
        if transfer_from_id == transfer_to_id:
            st.error("From and To must be different accounts.")
        else:
            try:
                amt = to_money(transfer_amount_str)
            except Exception:
                st.error("Amount must be a number like 100.00.")
            else:
                if amt == ZERO:
                    st.error("Amount can't be zero.")
                else:
                    try:
                        with SessionLocal() as session:
                            add_transfer(
                                session,
                                from_account_id=transfer_from_id,
                                to_account_id=transfer_to_id,
                                date=transfer_date,
                                amount=amt,
                                notes=(transfer_notes.strip() or None),
                            )
                        st.success(
                            f"Transferred {format_cad(amt)}: "
                            f"{acct_labels[transfer_from_id]} → {acct_labels[transfer_to_id]}"
                        )
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))

st.divider()

# --- Filter + clickable list ------------------------------------------------
transactions = load_transactions()
st.subheader(f"All transactions ({len(transactions)})")
st.caption("Click any row to edit or delete that transaction.")

# Filter dropdown includes ARCHIVED accounts (with a flag) so the user can
# review history on a retired loan, financing item, etc.
filter_labels = {
    a.id: f"{a.name} ({a.type})" + (" [archived]" if a.archived else "")
    for a in all_accounts
}

fc1, fc2 = st.columns(2)
with fc1:
    filter_account = st.selectbox(
        "Filter by account",
        options=["All"] + list(filter_labels.keys()),
        format_func=lambda x: "All" if x == "All" else filter_labels[x],
    )
with fc2:
    filter_cat = st.selectbox(
        "Filter by category", options=["All"] + category_names() + ["Transfer"]
    )

filtered = [
    t
    for t in transactions
    if (filter_account == "All" or t.account_id == filter_account)
    and (filter_cat == "All" or t.category == filter_cat)
]

if not filtered:
    st.info("No transactions match your filters.")
else:
    df = pd.DataFrame(
        [
            {
                "ID": t.id,
                "Date": t.date,
                "Account": account_map[t.account_id].name
                if t.account_id in account_map
                else "?",
                "Category": t.category,
                "Subcategory": t.subcategory,
                "Amount": format_cad(t.amount),
                "Notes": t.notes or "",
            }
            for t in filtered
        ]
    )
    event = st.dataframe(
        df,
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        key="tx_table",
    )

    # --- Inline edit / delete for the selected row ---------------------------
    if event.selection.rows:
        idx = event.selection.rows[0]
        if idx < len(filtered):
            target = filtered[idx]
            st.divider()

            if target.kind == "transfer":
                counterpart = next(
                    (
                        t
                        for t in transactions
                        if t.transfer_id == target.transfer_id and t.id != target.id
                    ),
                    None,
                )
                if counterpart is not None and target.amount < ZERO:
                    from_acc = account_map.get(target.account_id)
                    to_acc = account_map.get(counterpart.account_id)
                elif counterpart is not None:
                    from_acc = account_map.get(counterpart.account_id)
                    to_acc = account_map.get(target.account_id)
                else:
                    from_acc = account_map.get(target.account_id)
                    to_acc = None

                is_debt_payment_tx = target.category == "Debt Payments"
                tx_kind_label = "debt payment" if is_debt_payment_tx else "transfer"

                st.markdown(f"**Selected {tx_kind_label} #{target.id}**")
                st.info(
                    f"{target.date} — {from_acc.name if from_acc else '?'} → "
                    f"{to_acc.name if to_acc else '?'} — "
                    f"{format_cad(abs(target.amount))}. "
                    f"{tx_kind_label.capitalize()}s can't be edited — delete "
                    "and re-create if you need to change something."
                )
                confirm_xfer = st.checkbox(
                    f"Yes, delete this {tx_kind_label} (both sides removed; balances restored)",
                    key=f"confirm_xfer_{target.id}",
                )
                if st.button(
                    f"Delete {tx_kind_label}", key=f"del_xfer_btn_{target.id}"
                ):
                    if not confirm_xfer:
                        st.warning("Tick the confirmation box first.")
                    else:
                        with SessionLocal() as session:
                            delete_transaction(session, target.id)
                        st.success(f"{tx_kind_label.capitalize()} deleted.")
                        st.rerun()
            else:
                st.markdown(f"**Editing transaction #{target.id}**")

                # Cascading category dropdowns OUTSIDE the form
                ecol1, ecol2 = st.columns(2)
                with ecol1:
                    cat_names = category_names()
                    edit_cat = st.selectbox(
                        "Category",
                        cat_names,
                        index=cat_names.index(target.category)
                        if target.category in cat_names
                        else 0,
                        key=f"edit_cat_{target.id}",
                    )
                with ecol2:
                    subs = subcategories_of(edit_cat)
                    edit_sub = st.selectbox(
                        "Subcategory",
                        subs,
                        index=subs.index(target.subcategory)
                        if target.subcategory in subs
                        else 0,
                        key=f"edit_sub_{target.id}",
                    )

                with st.form(f"edit_tx_form_{target.id}"):
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        edit_date = st.date_input("Date", value=target.date)
                    with c2:
                        acct_keys = list(acct_labels.keys())
                        edit_account_id = st.selectbox(
                            "Account",
                            options=acct_keys,
                            index=acct_keys.index(target.account_id)
                            if target.account_id in acct_keys
                            else 0,
                            format_func=lambda i: acct_labels[i],
                        )
                    with c3:
                        edit_amount = st.text_input(
                            "Amount (magnitude)", value=str(abs(target.amount))
                        )
                    edit_notes = st.text_area(
                        "Notes", value=target.notes or "", height=70
                    )
                    confirm_delete = st.checkbox("Yes, delete this transaction")
                    sc, dc = st.columns(2)
                    with sc:
                        save = st.form_submit_button("Save changes", type="primary")
                    with dc:
                        delete = st.form_submit_button("Delete")

                if save:
                    try:
                        magnitude = to_money(edit_amount)
                    except Exception:
                        st.error("Amount must be a number like 19.99.")
                    else:
                        with SessionLocal() as session:
                            update_transaction(
                                session,
                                target.id,
                                account_id=edit_account_id,
                                date=edit_date,
                                magnitude=magnitude,
                                category=edit_cat,
                                subcategory=edit_sub,
                                notes=(edit_notes.strip() or None),
                            )
                        st.success("Saved.")
                        st.rerun()

                if delete:
                    if not confirm_delete:
                        st.warning("Tick the confirmation box first.")
                    else:
                        with SessionLocal() as session:
                            delete_transaction(session, target.id)
                        st.success("Deleted.")
                        st.rerun()
