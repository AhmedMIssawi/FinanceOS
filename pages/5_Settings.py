"""Settings — currency, savings target, backups, archive, reset, developer area."""
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
import streamlit as st
from sqlalchemy import select

from core.archive_service import unarchive
from core.backup_service import (
    BACKUP_DIR,
    create_backup,
    delete_all_backups,
    list_backups,
    reset_database,
    restore_backup,
)
from core.db import DB_PATH, SessionLocal, init_db
from core.exchange_service import (
    SCHEDULED_HOURS,
    all_rates,
    convert,
    set_rate,
    update_rates_from_api,
)
from core.models import Account
from core.money import (
    CURRENCIES,
    ZERO,
    active_currency_code,
    format_money,
    set_active_currency,
    to_money,
)
from core.settings_service import (
    DEFAULT_SAVINGS_TARGET,
    get_currency_code,
    get_dev_password,
    get_savings_target,
    set_currency_code,
    set_dev_password,
    set_savings_target,
)

init_db()

st.set_page_config(page_title="Settings | FinanceOS", layout="wide")
st.title("Settings")
st.caption("Currency, savings target, backups, archive, reset, and developer info.")

# --- Currency --------------------------------------------------------------
st.subheader("Display currency")
st.caption(
    "Currency the app uses when showing amounts. **Switching currency "
    "re-labels existing amounts but does NOT convert them via exchange "
    "rates.** Changing currency also resets the yearly savings target "
    "below (the old number was denominated in the old currency)."
)

with SessionLocal() as session:
    current_currency = get_currency_code(session)

currency_options = list(CURRENCIES.keys())
with st.form("currency_form"):
    new_currency = st.selectbox(
        "Currency",
        options=currency_options,
        format_func=lambda c: (
            f"{c} — {CURRENCIES[c]['name']} ({CURRENCIES[c]['symbol']})"
        ),
        index=currency_options.index(current_currency),
    )
    save_currency = st.form_submit_button("Save currency", type="primary")

if save_currency:
    if new_currency == current_currency:
        st.info("No change — already set to this currency.")
    else:
        try:
            with SessionLocal() as session:
                set_currency_code(session, new_currency)
                # Reset the savings target since the previous value was
                # denominated in the old currency.
                set_savings_target(session, DEFAULT_SAVINGS_TARGET)
            set_active_currency(new_currency)
            st.warning(
                f"Currency switched to {new_currency} ({CURRENCIES[new_currency]['name']}). "
                f"The yearly savings target was reset to "
                f"{format_money(DEFAULT_SAVINGS_TARGET)} — adjust below to "
                "reflect your goal in the new currency."
            )
            st.rerun()
        except ValueError as e:
            st.error(str(e))

st.divider()

# --- Exchange rates (auto-updated) ----------------------------------------
st.subheader("Exchange rates")
schedule_str = ", ".join(f"{h:02d}:00" for h in SCHEDULED_HOURS)
st.caption(
    f"Rates auto-fetch from **open.er-api.com** (free, no API key) on "
    f"app start AND at **{schedule_str}** daily, using your active "
    f"currency as the base. The app stays offline-first — once fetched, "
    "rates are cached locally and used by the **Calculator → Currency "
    "converter** tab. If the API or your internet is down, you can still "
    "override rates manually via the expander at the bottom."
)

active_code = active_currency_code()

with SessionLocal() as session:
    stored_rates = all_rates(session)

# Status banner
if stored_rates:
    most_recent = max(r.updated_at for r in stored_rates)
    age = datetime.now() - most_recent
    if age.total_seconds() < 60 * 60:
        freshness = f"{int(age.total_seconds() / 60)} min ago"
    elif age.total_seconds() < 24 * 60 * 60:
        freshness = f"{int(age.total_seconds() / 3600)} h ago"
    else:
        freshness = f"{age.days} day(s) ago"
    st.markdown(
        f"**Last updated:** {most_recent.strftime('%Y-%m-%d %H:%M')} "
        f"({freshness}) • **Base:** {active_code}"
    )
else:
    st.warning(
        "No rates stored yet. Click 'Refresh now' below (requires internet) "
        "or set one manually via the override at the bottom."
    )

if st.button(
    f"Refresh rates now (base: {active_code})",
    type="primary",
    help="Forces an immediate fetch. Useful when you can't wait for the next scheduled slot.",
):
    try:
        with SessionLocal() as session:
            count = update_rates_from_api(session, base_code=active_code)
        st.success(f"Updated {count} rate(s) from open.er-api.com.")
        st.rerun()
    except Exception as e:
        st.error(
            f"Couldn't fetch: {e}. Check your internet connection, or set "
            "rates manually via the override below."
        )

# Stored rates table
if stored_rates:
    st.markdown("**Stored rates**")
    rate_rows = sorted(stored_rates, key=lambda r: r.updated_at, reverse=True)
    df_rates = pd.DataFrame(
        [
            {
                "From": r.from_currency,
                "To": r.to_currency,
                "Rate": str(r.rate),
                "Updated": r.updated_at.strftime("%Y-%m-%d %H:%M"),
            }
            for r in rate_rows
        ]
    )
    st.dataframe(df_rates, hide_index=True, width="stretch")

# Manual override (hidden by default — auto-update is the recommended path)
with st.expander("Manual override (for offline use or to correct a stale rate)"):
    st.caption(
        "Set a specific rate manually. Useful when there's no internet, "
        "the API is down, or you want to lock in a particular rate. The "
        "inverse is auto-derived (save CAD→EGP and the app knows EGP→CAD)."
    )
    with st.form("manual_rate_form", clear_on_submit=True):
        cur_options = list(CURRENCIES.keys())
        mr_c1, mr_c2, mr_c3 = st.columns([1, 1, 2])
        with mr_c1:
            manual_from = st.selectbox(
                "From", cur_options, index=cur_options.index(active_code)
            )
        with mr_c2:
            default_to_idx = 0 if cur_options[0] != active_code else 1
            manual_to = st.selectbox("To", cur_options, index=default_to_idx)
        with mr_c3:
            manual_rate_str = st.text_input(
                "Rate (1 From = X To)",
                value="1.0",
                help="Example: if 1 CAD = 22.5 EGP, enter 22.5",
            )
        save_rate_clicked = st.form_submit_button("Save rate", type="primary")

    if save_rate_clicked:
        if manual_from == manual_to:
            st.error("From and To must be different currencies.")
        else:
            try:
                rate_decimal = Decimal(manual_rate_str.strip())
            except Exception:
                st.error("Rate must be a positive number like 22.5 or 0.73.")
            else:
                try:
                    with SessionLocal() as session:
                        set_rate(session, manual_from, manual_to, rate_decimal)
                    st.success(f"Saved: 1 {manual_from} = {rate_decimal} {manual_to}")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))

st.caption(
    "💡 Use the **Calculator** page (sidebar) for live currency conversion."
)

st.divider()

# --- Yearly savings target -------------------------------------------------
st.subheader("Yearly savings target")
st.caption(
    "How much you want to save in a calendar year. The Dashboard's "
    "'Savings Progress' bar measures against this number."
)

with SessionLocal() as session:
    current_target = get_savings_target(session)

with st.form("savings_target_form"):
    new_target_str = st.text_input(
        f"Yearly target ({active_currency_code()})",
        value=str(current_target),
    )
    save_target = st.form_submit_button("Save target", type="primary")

if save_target:
    try:
        new_target = to_money(new_target_str)
    except Exception:
        st.error("Target must be a number like 20000.00.")
    else:
        if new_target <= ZERO:
            st.error("Target must be positive.")
        else:
            with SessionLocal() as session:
                set_savings_target(session, new_target)
            st.success(f"Savings target set to {format_money(new_target)}.")
            st.rerun()

st.divider()

# --- Backups ---------------------------------------------------------------
st.subheader("Backups")
st.caption(
    "Your data lives in a single SQLite file. FinanceOS auto-creates one "
    "backup per day and keeps the last 14. You can also create extra "
    "backups manually or restore from any saved one."
)

bcol1, bcol2 = st.columns([3, 1])
with bcol1:
    label = st.text_input(
        "Optional label for manual backup",
        placeholder="e.g. before-experiment",
        key="backup_label",
    )
with bcol2:
    st.write("")
    st.write("")
    if st.button("Create backup now", type="primary"):
        try:
            path = create_backup(label=label.strip() or None)
            st.success(f"Backed up to: `{path.name}`")
            st.rerun()
        except FileNotFoundError as e:
            st.error(str(e))

# Confirmation banner for restore action
restore_target = st.session_state.get("confirming_restore")
if restore_target:
    st.warning(
        f"Restoring will REPLACE current data with `{Path(restore_target).name}`. "
        "A 'pre-restore' backup is created first so you can undo this."
    )
    rc1, rc2 = st.columns(2)
    if rc1.button("Yes, restore this backup", type="primary"):
        try:
            create_backup(label="pre-restore")
            restore_backup(Path(restore_target))
            del st.session_state["confirming_restore"]
            st.success(
                "Restored. Refresh the browser to see the loaded data on all pages."
            )
            st.rerun()
        except Exception as e:
            st.error(f"Restore failed: {e}")
    if rc2.button("Cancel"):
        del st.session_state["confirming_restore"]
        st.rerun()

backups = list_backups()
if not backups:
    st.info("No backups yet. Use the app for a day or create one manually above.")
else:
    st.markdown("**Available backups** (newest first)")
    for path, when, size in backups:
        bc1, bc2 = st.columns([4, 1])
        bc1.write(
            f"`{path.name}` — {when.strftime('%Y-%m-%d %H:%M')} "
            f"({size / 1024:.1f} KB)"
        )
        if bc2.button("Restore", key=f"restore_{path.name}"):
            st.session_state["confirming_restore"] = str(path)
            st.rerun()

st.divider()

# --- Archived accounts -----------------------------------------------------
st.subheader("Archived accounts")
st.caption(
    "Loans and financing items auto-archive when their balance hits $0. "
    "The closing summary (open date, paid-off date, total paid, number of "
    "payments) is appended to the account's notes. Click 'Unarchive' to "
    "restore one to active use."
)

with SessionLocal() as session:
    archived_accounts = list(
        session.scalars(
            select(Account)
            .where(Account.archived)
            .order_by(Account.archived_at.desc())
        ).all()
    )

if not archived_accounts:
    st.info("No archived accounts yet.")
else:
    for acc in archived_accounts:
        archived_when = (
            acc.archived_at.strftime("%Y-%m-%d %H:%M")
            if acc.archived_at
            else "?"
        )
        with st.expander(
            f"{acc.name} ({acc.type}) — archived {archived_when}"
        ):
            st.markdown(f"**Type:** {acc.type}")
            st.markdown(f"**Final balance:** {format_money(acc.balance)}")
            st.markdown(f"**Institution:** {acc.institution or '—'}")
            st.markdown("**Notes:**")
            st.code(acc.notes or "(no notes)", language="text")
            if st.button(f"Unarchive '{acc.name}'", key=f"unarchive_{acc.id}"):
                with SessionLocal() as s:
                    unarchive(s, acc.id)
                st.success(f"Unarchived: {acc.name}")
                st.rerun()

st.divider()

# --- Reset all data --------------------------------------------------------
st.subheader("Reset all data")
st.caption(
    "Deletes ALL accounts, transactions, budgets, debts, and settings. "
    "Useful for handing the app to a tester or starting fresh. A "
    "'pre-reset' backup is created automatically — tick the box below if "
    "you want a TRUE wipe with no recovery (also deletes every backup)."
)

confirm_text = st.text_input(
    "Type **RESET** (uppercase) to confirm:",
    key="reset_confirm",
)
nuke_backups = st.checkbox(
    "Also delete ALL backups (true privacy wipe — NO recovery possible)",
    key="nuke_backups",
)
if st.button("⚠ Wipe all data", type="secondary"):
    if confirm_text != "RESET":
        st.error("Please type RESET (uppercase) exactly to confirm.")
    else:
        try:
            backup = reset_database()
            if nuke_backups:
                count = delete_all_backups()
                st.success(
                    f"All data wiped and {count} backup file(s) deleted. "
                    "Nothing remains to recover — settings, accounts, "
                    "transactions, debts, archived items, and backups are all gone."
                )
            else:
                st.success(
                    f"All data wiped. Pre-reset backup saved to `{backup.name}` — "
                    "restore it above if you change your mind. Refresh "
                    "the browser to see the empty state."
                )
        except Exception as e:
            st.error(f"Reset failed: {e}")

st.divider()

# --- Public app info (always visible) -------------------------------------
st.subheader("About")
st.markdown("**Version:** v1.2 — multi-currency + privacy lock")
st.markdown(
    "**Privacy:** the app binds to `127.0.0.1` only — your data is never "
    "accessible from the network, only from this PC's localhost."
)

# --- Developer settings (password-gated) ----------------------------------
st.divider()
st.subheader("Developer settings 🔒")
st.caption(
    "Sensitive paths and configuration — locked by default so testers "
    "don't see filesystem details. Default password is **0000** "
    "(change it once unlocked)."
)

if "dev_unlocked" not in st.session_state:
    st.session_state["dev_unlocked"] = False

if not st.session_state["dev_unlocked"]:
    with st.form("dev_unlock_form"):
        unlock_password = st.text_input(
            "Password", type="password", key="dev_unlock_pw"
        )
        unlock_clicked = st.form_submit_button("Unlock", type="primary")
    if unlock_clicked:
        with SessionLocal() as session:
            stored = get_dev_password(session)
        if unlock_password == stored:
            st.session_state["dev_unlocked"] = True
            st.rerun()
        else:
            st.error("Incorrect password.")
else:
    st.success("Unlocked.")
    st.markdown(f"**Database file:** `{DB_PATH}`")
    if DB_PATH.exists():
        st.markdown(f"**Database size:** {DB_PATH.stat().st_size / 1024:.1f} KB")
    st.markdown(f"**Backup directory:** `{BACKUP_DIR}`")
    st.markdown(
        "**Data portability:** copy the entire `data/` folder to migrate "
        "to another computer. Delete it to start completely from scratch."
    )

    st.divider()
    st.markdown("**Change developer password**")
    with st.form("dev_password_change"):
        old_pw = st.text_input("Current password", type="password", key="old_pw")
        new_pw = st.text_input("New password", type="password", key="new_pw")
        confirm_pw = st.text_input(
            "Confirm new password", type="password", key="confirm_pw"
        )
        change_clicked = st.form_submit_button("Update password", type="primary")
    if change_clicked:
        with SessionLocal() as session:
            stored = get_dev_password(session)
        if old_pw != stored:
            st.error("Current password is incorrect.")
        elif not new_pw:
            st.error("New password can't be empty.")
        elif new_pw != confirm_pw:
            st.error("New passwords don't match.")
        else:
            try:
                with SessionLocal() as session:
                    set_dev_password(session, new_pw)
                st.success("Password updated.")
            except ValueError as e:
                st.error(str(e))

    if st.button("Lock developer settings"):
        st.session_state["dev_unlocked"] = False
        st.rerun()
