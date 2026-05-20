"""ORM models. Money columns store Decimal as TEXT via the MoneyType decorator."""
from datetime import date as date_type, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    TypeDecorator,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db import Base
from core.money import ZERO, to_money


class MoneyType(TypeDecorator):
    """SQLAlchemy column type: store Decimal as TEXT (never float).

    Write path runs `to_money()` so any value that sneaks in as a float
    raises TypeError loudly rather than silently corrupting precision.
    Read path returns a quantized Decimal.
    """
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return str(to_money(value))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return to_money(value)


class RateType(TypeDecorator):
    """Like MoneyType but without 2dp quantization — exchange rates need
    more precision (e.g. CAD->EGP can be 22.4567)."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, float):
            raise TypeError("Refusing to convert float to rate. Pass a string.")
        d = value if isinstance(value, Decimal) else Decimal(str(value))
        return str(d)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return Decimal(value)


ACCOUNT_TYPES = (
    "chequing",
    "savings",
    "credit",       # Mastercard / Visa
    "cash",
    "coins",        # physical coins; tracked separately from bills so the user can move them around
    "overdraft",
    "financing",
    "investment",
    "loan",         # money lent to or borrowed from a friend; sign of balance = direction
)

TRANSACTION_KINDS = ("income", "expense", "transfer")


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    # 3-letter ISO code (CAD/USD/EUR/EGP). The currency `balance` is
    # denominated in. Cross-currency totals (Net Worth, Total Debt, etc.)
    # convert via stored exchange rates at display time — stored balances
    # are NEVER auto-converted.
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="CAD")
    balance: Mapped[Decimal] = mapped_column(MoneyType, nullable=False, default=ZERO)
    # Only set for credit accounts. balance is stored negative (= -owed),
    # so available = credit_limit + balance, owed = -balance.
    credit_limit: Mapped[Optional[Decimal]] = mapped_column(MoneyType, nullable=True)
    # Monthly minimum payment, for debt-eligible accounts. Used by the
    # Debt page's payoff simulator. NULL means "not set".
    min_payment: Mapped[Optional[Decimal]] = mapped_column(MoneyType, nullable=True)
    # JSON breakdown of coin denomination counts (only meaningful for
    # type='coins' accounts). Informational only — NEVER feeds into balance
    # calculations. Format: {"2.00": 4, "1.00": 5, "0.25": 3, ...}
    coin_breakdown: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    interest_rate: Mapped[Decimal] = mapped_column(MoneyType, nullable=False, default=ZERO)
    institution: Mapped[Optional[str]] = mapped_column(String(80))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    # When True, the account is hidden from active views. Auto-set when a
    # one-and-done debt (loan/financing) hits $0; can also be un-set in Settings.
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    date: Mapped[date_type] = mapped_column(Date, nullable=False)
    # Signed: income is positive, expense is negative.
    amount: Mapped[Decimal] = mapped_column(MoneyType, nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    subcategory: Mapped[str] = mapped_column(String(40), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    # Both legs of an account-to-account transfer share this UUID hex.
    # NULL for regular income/expense transactions.
    transfer_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    account: Mapped[Account] = relationship(back_populates="transactions")


class Budget(Base):
    __tablename__ = "budgets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    limit_amount: Mapped[Decimal] = mapped_column(MoneyType, nullable=False)


class Debt(Base):
    __tablename__ = "debts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    principal: Mapped[Decimal] = mapped_column(MoneyType, nullable=False)
    # Annual percentage (e.g. 19.99 for 19.99%).
    interest_rate: Mapped[Decimal] = mapped_column(MoneyType, nullable=False)
    min_payment: Mapped[Decimal] = mapped_column(MoneyType, nullable=False)
    linked_account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("accounts.id"))
    notes: Mapped[Optional[str]] = mapped_column(Text)


class SavingsGoal(Base):
    __tablename__ = "savings_goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    target_amount: Mapped[Decimal] = mapped_column(MoneyType, nullable=False)
    current_amount: Mapped[Decimal] = mapped_column(MoneyType, nullable=False, default=ZERO)
    target_date: Mapped[Optional[date_type]] = mapped_column(Date)


class Setting(Base):
    """Key-value store for user preferences (savings target, theme, etc.)."""
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)


class ExchangeRate(Base):
    """One stored conversion rate: 1 unit of from_currency = `rate` units of to_currency.

    Rates can come from manual entry or the optional "fetch from internet"
    button (open.er-api.com). The app uses these for the in-Settings
    currency converter; it does NOT auto-convert stored transaction
    amounts when the display currency changes.
    """
    __tablename__ = "exchange_rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    to_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    rate: Mapped[Decimal] = mapped_column(RateType, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
