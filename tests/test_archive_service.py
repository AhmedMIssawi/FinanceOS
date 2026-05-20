"""Tests for core/archive_service.py — auto-archive of paid-off debts."""
from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core import models  # noqa: F401
from core.archive_service import (
    ARCHIVE_MARKER,
    reconcile_all_archives,
    reconcile_archive,
    unarchive,
)
from core.db import Base
from core.models import Account
from core.money import ZERO, to_money
from core.transactions_service import add_transfer, delete_transaction


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Local = sessionmaker(bind=engine, future=True)
    with Local() as s:
        yield s


@pytest.fixture
def chequing(session):
    a = Account(name="Chequing", type="chequing", balance=to_money("5000"))
    session.add(a)
    session.commit()
    return a


def test_loan_archives_when_paid_off(session, chequing):
    loan = Account(name="Loan from John", type="loan", balance=to_money("-100"))
    session.add(loan)
    session.commit()
    add_transfer(
        session,
        from_account_id=chequing.id,
        to_account_id=loan.id,
        date=date.today(),
        amount=to_money("100"),
    )
    session.refresh(loan)
    assert loan.archived is True
    assert loan.archived_at is not None


def test_summary_appended_to_notes(session, chequing):
    loan = Account(name="Loan from John", type="loan", balance=to_money("-100"))
    session.add(loan)
    session.commit()
    add_transfer(
        session,
        from_account_id=chequing.id,
        to_account_id=loan.id,
        date=date.today(),
        amount=to_money("100"),
    )
    session.refresh(loan)
    assert "Archived" in (loan.notes or "")
    assert "Total paid: $100.00" in loan.notes
    assert "1 payment" in loan.notes


def test_financing_archives_when_paid_off(session, chequing):
    fin = Account(name="Watch", type="financing", balance=to_money("-50"))
    session.add(fin)
    session.commit()
    add_transfer(
        session,
        from_account_id=chequing.id,
        to_account_id=fin.id,
        date=date.today(),
        amount=to_money("50"),
    )
    session.refresh(fin)
    assert fin.archived is True


def test_credit_card_does_not_auto_archive(session, chequing):
    visa = Account(name="Visa", type="credit", balance=to_money("-100"))
    session.add(visa)
    session.commit()
    add_transfer(
        session,
        from_account_id=chequing.id,
        to_account_id=visa.id,
        date=date.today(),
        amount=to_money("100"),
    )
    session.refresh(visa)
    assert visa.archived is False  # credit cards stay active


def test_partial_payment_does_not_archive(session, chequing):
    loan = Account(name="Loan", type="loan", balance=to_money("-200"))
    session.add(loan)
    session.commit()
    add_transfer(
        session,
        from_account_id=chequing.id,
        to_account_id=loan.id,
        date=date.today(),
        amount=to_money("50"),
    )
    session.refresh(loan)
    assert loan.archived is False
    assert loan.balance == to_money("-150.00")


def test_undoing_final_payment_unarchives(session, chequing):
    loan = Account(name="Loan", type="loan", balance=to_money("-100"))
    session.add(loan)
    session.commit()
    out_tx, _ = add_transfer(
        session,
        from_account_id=chequing.id,
        to_account_id=loan.id,
        date=date.today(),
        amount=to_money("100"),
    )
    session.refresh(loan)
    assert loan.archived is True
    # Delete the final payment — debt resurrected.
    delete_transaction(session, out_tx.id)
    session.refresh(loan)
    assert loan.archived is False
    assert loan.balance == to_money("-100.00")


def test_multiple_payments_summary_counts_correctly(session, chequing):
    loan = Account(name="Loan", type="loan", balance=to_money("-300"))
    session.add(loan)
    session.commit()
    add_transfer(
        session,
        from_account_id=chequing.id,
        to_account_id=loan.id,
        date=date.today(),
        amount=to_money("100"),
    )
    add_transfer(
        session,
        from_account_id=chequing.id,
        to_account_id=loan.id,
        date=date.today(),
        amount=to_money("150"),
    )
    add_transfer(
        session,
        from_account_id=chequing.id,
        to_account_id=loan.id,
        date=date.today(),
        amount=to_money("50"),
    )
    session.refresh(loan)
    assert loan.archived is True
    assert "Total paid: $300.00" in loan.notes
    assert "3 payments" in loan.notes


def test_manual_unarchive(session, chequing):
    loan = Account(name="Loan", type="loan", balance=to_money("-50"))
    session.add(loan)
    session.commit()
    add_transfer(
        session,
        from_account_id=chequing.id,
        to_account_id=loan.id,
        date=date.today(),
        amount=to_money("50"),
    )
    session.refresh(loan)
    assert loan.archived is True
    unarchive(session, loan.id)
    session.refresh(loan)
    assert loan.archived is False
    assert loan.archived_at is None


def test_reconcile_idempotent_when_already_archived(session, chequing):
    loan = Account(name="Loan", type="loan", balance=to_money("0"))
    loan.archived = True
    loan.archived_at = datetime.now()
    original_notes = "Already archived once."
    loan.notes = original_notes
    session.add(loan)
    session.commit()
    changed = reconcile_archive(session, loan)
    assert changed is False
    assert loan.notes == original_notes  # no double-summary


def test_reconcile_all_archives_catches_pre_existing_paid_loan(session):
    """Simulates a loan that was paid off BEFORE the archive feature existed."""
    vansh = Account(name="Loan from Vansh", type="loan", balance=to_money("0"))
    session.add(vansh)
    session.commit()
    assert vansh.archived is False  # not archived yet
    changed = reconcile_all_archives(session)
    assert len(changed) == 1
    assert changed[0].id == vansh.id
    session.refresh(vansh)
    assert vansh.archived is True
    assert ARCHIVE_MARKER in (vansh.notes or "")


def test_reconcile_all_does_not_touch_active_accounts(session):
    active_loan = Account(name="Active loan", type="loan", balance=to_money("-100"))
    chequing = Account(name="Chequing", type="chequing", balance=to_money("0"))
    session.add_all([active_loan, chequing])
    session.commit()
    changed = reconcile_all_archives(session)
    assert changed == []
    session.refresh(active_loan)
    assert active_loan.archived is False


def test_summary_handles_zero_recorded_payments(session):
    """When the balance was cleared externally (not via app transfers),
    the summary should say so honestly rather than '$0.00 across 0 payments'."""
    vansh = Account(name="Loan from Vansh", type="loan", balance=to_money("0"))
    session.add(vansh)
    session.commit()
    reconcile_archive(session, vansh)
    session.refresh(vansh)
    assert "Balance cleared without recorded transfers" in vansh.notes


def test_manually_unarchived_loan_does_not_re_archive(session, chequing):
    """If the user explicitly un-archives a settled loan, the app must not
    silently re-archive it on the next reconcile pass (no flip-flop)."""
    loan = Account(name="Loan", type="loan", balance=to_money("-100"))
    session.add(loan)
    session.commit()
    from core.transactions_service import add_transfer
    add_transfer(
        session,
        from_account_id=chequing.id,
        to_account_id=loan.id,
        date=date.today(),
        amount=to_money("100"),
    )
    session.refresh(loan)
    assert loan.archived is True
    # User manually unarchives
    unarchive(session, loan.id)
    session.refresh(loan)
    assert loan.archived is False
    # Reconcile again — should NOT re-archive (marker in notes preserves intent)
    changed = reconcile_archive(session, loan)
    assert changed is False
    session.refresh(loan)
    assert loan.archived is False
