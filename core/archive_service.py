"""Auto-archive for one-and-done debt accounts.

Loans (friend loans) and financing (watches, flights) are paid off once
and don't get reused. When their balance reaches $0, the account is
archived — hidden from active views — with a summary appended to its
notes capturing when it opened, when it closed, and what was paid.

Credit cards and overdraft are NOT auto-archived: those are revolving
facilities the user keeps using. If the user wants to retire one of
those, they can delete the account manually.

`reconcile_archive` is called on the hot path (after each balance-changing
operation). `reconcile_all_archives` runs once at app startup to catch up
accounts that were paid off before this feature existed.
"""
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.debts_service import payment_summary
from core.models import Account
from core.money import ZERO, format_cad

AUTO_ARCHIVE_TYPES = ("loan", "financing")

# Marker inserted into the notes block at archive time. Used to detect
# accounts that were previously archived — if the user un-archives one,
# we shouldn't silently re-archive it just because the balance is still 0.
ARCHIVE_MARKER = "=== Archived "


def _build_summary(session: Session, account: Account) -> str:
    """Generate the closing-summary text appended to notes at archive time."""
    today = date.today()
    started = account.created_at.date() if account.created_at else today
    days = max((today - started).days, 0)
    total_paid, count = payment_summary(session, account.id)

    day_word = "day" if days == 1 else "days"
    if count == 0:
        payment_line = (
            "Balance cleared without recorded transfers "
            "— settled externally (cash, in-person, or pre-app)."
        )
    else:
        payment_word = "payment" if count == 1 else "payments"
        payment_line = (
            f"Total paid: {format_cad(total_paid)} "
            f"across {count} {payment_word}"
        )

    return (
        f"\n\n{ARCHIVE_MARKER}{today.isoformat()} ===\n"
        f"Account opened: {started.isoformat()} ({days} {day_word})\n"
        f"{payment_line}"
    )


def reconcile_archive(session: Session, account: Account) -> bool:
    """Sync archive status with the current balance.

    - If the account is auto-archive-eligible, balance == 0, has NEVER
      been archived before, and isn't currently archived → archive with
      a fresh summary appended to notes.
    - If currently archived AND balance != 0 (e.g. user deleted the
      final payment) → un-archive so it shows up again.
    - If the account was previously archived (`ARCHIVE_MARKER` in notes)
      and the user manually un-archived it → DO NOT auto-archive again
      even if balance returns to 0; respect the user's explicit choice.

    Returns True if a state change was applied.
    """
    if account.type not in AUTO_ARCHIVE_TYPES:
        return False

    if account.balance == ZERO and not account.archived:
        if ARCHIVE_MARKER in (account.notes or ""):
            return False  # previously archived + manually un-archived — leave alone
        account.notes = (account.notes or "") + _build_summary(session, account)
        account.archived = True
        account.archived_at = datetime.now()
        session.commit()
        return True

    if account.balance != ZERO and account.archived:
        account.archived = False
        account.archived_at = None
        session.commit()
        return True

    return False


def reconcile_all_archives(session: Session) -> list[Account]:
    """Scan every auto-archive-eligible account and reconcile its status.

    Used as a startup catch-up so loans/financing that were paid off
    BEFORE the archive feature existed (or via direct balance edits
    that bypass transactions_service) still get retired properly.

    Returns the list of accounts whose state changed this run.
    """
    candidates = list(
        session.scalars(
            select(Account).where(Account.type.in_(AUTO_ARCHIVE_TYPES))
        ).all()
    )
    return [a for a in candidates if reconcile_archive(session, a)]


def unarchive(session: Session, account_id: int) -> None:
    """Manually un-archive an account (e.g. from Settings page)."""
    account = session.get(Account, account_id)
    if account and account.archived:
        account.archived = False
        account.archived_at = None
        session.commit()
