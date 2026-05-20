"""Transaction operations with atomic account-balance side effects.

Adds, updates, and deletes of a Transaction also adjust the linked
account's balance. Transfers atomically move money between two accounts
as a pair of linked transactions (matched by transfer_id), so a crash
mid-operation cannot leave the books inconsistent.

Sign rules:
- Regular income:   amount stored positive, kind="income"
- Regular expense:  amount stored negative, kind="expense"
- Transfer source:  amount stored negative, kind="transfer"
- Transfer dest:    amount stored positive, kind="transfer"

The UI always passes a positive magnitude; this module applies signs.
"""
from datetime import date as date_type
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.categories import TRANSFER_CATEGORY, TRANSFER_SUBCATEGORY, is_income
from core.models import Account, Transaction
from core.money import ZERO, to_money


def _signed(category: str, magnitude: Decimal) -> tuple[Decimal, str]:
    """Apply sign by category and return (signed_amount, kind)."""
    magnitude = to_money(abs(magnitude))
    if is_income(category):
        return magnitude, "income"
    return -magnitude, "expense"


def add_transaction(
    session: Session,
    *,
    account_id: int,
    date: date_type,
    magnitude: Decimal,
    category: str,
    subcategory: str,
    notes: Optional[str] = None,
) -> Transaction:
    amount, kind = _signed(category, magnitude)
    account = session.get(Account, account_id)
    if account is None:
        raise ValueError(f"Account {account_id} not found.")
    account.balance = to_money(account.balance + amount)
    tx = Transaction(
        account_id=account_id,
        date=date,
        amount=amount,
        category=category,
        subcategory=subcategory,
        kind=kind,
        notes=notes,
    )
    session.add(tx)
    session.commit()
    return tx


def update_transaction(
    session: Session,
    tx_id: int,
    *,
    account_id: int,
    date: date_type,
    magnitude: Decimal,
    category: str,
    subcategory: str,
    notes: Optional[str] = None,
) -> Transaction:
    tx = session.get(Transaction, tx_id)
    if tx is None:
        raise ValueError(f"Transaction {tx_id} not found.")
    if tx.kind == "transfer":
        raise ValueError("Transfers can't be edited — delete and re-create.")
    new_amount, new_kind = _signed(category, magnitude)

    if tx.account_id == account_id:
        account = session.get(Account, account_id)
        account.balance = to_money(account.balance - tx.amount + new_amount)
    else:
        old_acc = session.get(Account, tx.account_id)
        new_acc = session.get(Account, account_id)
        if new_acc is None:
            raise ValueError(f"Account {account_id} not found.")
        old_acc.balance = to_money(old_acc.balance - tx.amount)
        new_acc.balance = to_money(new_acc.balance + new_amount)

    tx.account_id = account_id
    tx.date = date
    tx.amount = new_amount
    tx.category = category
    tx.subcategory = subcategory
    tx.kind = new_kind
    tx.notes = notes
    session.commit()
    return tx


def delete_transaction(session: Session, tx_id: int) -> None:
    """Delete a transaction and reverse its balance impact.

    For transfer transactions, deletes BOTH legs atomically and reverses
    both linked accounts' balances. Either leg can be passed.
    """
    tx = session.get(Transaction, tx_id)
    if tx is None:
        raise ValueError(f"Transaction {tx_id} not found.")

    affected_accounts: list[Account] = []
    if tx.kind == "transfer" and tx.transfer_id:
        legs = list(
            session.scalars(
                select(Transaction).where(Transaction.transfer_id == tx.transfer_id)
            ).all()
        )
        for leg in legs:
            account = session.get(Account, leg.account_id)
            account.balance = to_money(account.balance - leg.amount)
            affected_accounts.append(account)
            session.delete(leg)
    else:
        account = session.get(Account, tx.account_id)
        account.balance = to_money(account.balance - tx.amount)
        affected_accounts.append(account)
        session.delete(tx)

    session.commit()

    # If deleting this transaction resurrected an archived debt
    # (balance back to non-zero) — un-archive it. Conversely if it
    # just paid one off (rare via delete path), archive it.
    from core.archive_service import reconcile_archive
    for acc in affected_accounts:
        reconcile_archive(session, acc)


def add_transfer(
    session: Session,
    *,
    from_account_id: int,
    to_account_id: int,
    date: date_type,
    amount: Decimal,
    notes: Optional[str] = None,
    category: str = TRANSFER_CATEGORY,
    subcategory: str = TRANSFER_SUBCATEGORY,
) -> tuple[Transaction, Transaction]:
    """Atomically move money from one account to another.

    Creates two linked Transaction rows sharing a transfer_id:
    - source leg: amount stored negative (money leaving)
    - destination leg: amount stored positive (money arriving)

    Both balance updates and both inserts commit together. Deleting
    either leg via delete_transaction() reverses both.

    `category`/`subcategory` default to TRANSFER_* for plain account-to-
    account moves. Pass `category="Debt Payments"` (and a debt subcategory)
    when a transfer represents a payment toward a debt — that way the
    payment surfaces in spending/budget analytics while still being a
    proper atomic transfer.
    """
    if from_account_id == to_account_id:
        raise ValueError("Source and destination accounts must differ.")

    amount = to_money(abs(amount))
    if amount == ZERO:
        raise ValueError("Transfer amount can't be zero.")

    from_acc = session.get(Account, from_account_id)
    if from_acc is None:
        raise ValueError(f"From-account {from_account_id} not found.")
    to_acc = session.get(Account, to_account_id)
    if to_acc is None:
        raise ValueError(f"To-account {to_account_id} not found.")

    transfer_id = uuid4().hex

    from_acc.balance = to_money(from_acc.balance - amount)
    to_acc.balance = to_money(to_acc.balance + amount)

    out_tx = Transaction(
        account_id=from_account_id,
        date=date,
        amount=-amount,
        category=category,
        subcategory=subcategory,
        kind="transfer",
        notes=notes,
        transfer_id=transfer_id,
    )
    in_tx = Transaction(
        account_id=to_account_id,
        date=date,
        amount=amount,
        category=category,
        subcategory=subcategory,
        kind="transfer",
        notes=notes,
        transfer_id=transfer_id,
    )
    session.add(out_tx)
    session.add(in_tx)
    session.commit()

    # After commit: if the destination is a one-and-done debt (loan/financing)
    # that just hit $0, auto-archive it with a closing summary. Imported
    # locally to avoid a circular import at module load.
    from core.archive_service import reconcile_archive
    reconcile_archive(session, to_acc)

    return out_tx, in_tx
