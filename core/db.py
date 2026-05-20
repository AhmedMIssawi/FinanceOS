"""SQLAlchemy engine + session factory.

The DB file lives at <project_root>/data/finance.db. Moving to
%APPDATA%\\FinanceOS\\ and adding daily backups is a Phase 7 concern.
"""
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "finance.db"


class Base(DeclarativeBase):
    pass


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "backups").mkdir(exist_ok=True)


_ensure_data_dir()

# check_same_thread=False because Streamlit reruns the script in a fresh
# thread on every interaction; the engine is shared across reruns.
engine = create_engine(
    f"sqlite:///{DB_PATH}",
    echo=False,
    future=True,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def _migrate() -> None:
    """Lightweight additive migrations.

    SQLAlchemy's create_all() handles new tables but ignores schema drift
    in existing ones, so we use plain ALTER TABLE for new columns. For
    destructive changes (renames, drops) introduce Alembic.
    """
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    accounts_cols = (
        {c["name"] for c in inspector.get_columns("accounts")}
        if "accounts" in tables
        else set()
    )
    transactions_cols = (
        {c["name"] for c in inspector.get_columns("transactions")}
        if "transactions" in tables
        else set()
    )
    with engine.begin() as conn:
        if "accounts" in tables and "credit_limit" not in accounts_cols:
            conn.execute(text("ALTER TABLE accounts ADD COLUMN credit_limit TEXT"))
        if "accounts" in tables and "min_payment" not in accounts_cols:
            conn.execute(text("ALTER TABLE accounts ADD COLUMN min_payment TEXT"))
        if "accounts" in tables and "archived" not in accounts_cols:
            conn.execute(
                text("ALTER TABLE accounts ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
            )
        if "accounts" in tables and "archived_at" not in accounts_cols:
            conn.execute(text("ALTER TABLE accounts ADD COLUMN archived_at TIMESTAMP"))
        if "accounts" in tables and "coin_breakdown" not in accounts_cols:
            conn.execute(text("ALTER TABLE accounts ADD COLUMN coin_breakdown TEXT"))
        if "accounts" in tables and "currency" not in accounts_cols:
            conn.execute(
                text("ALTER TABLE accounts ADD COLUMN currency TEXT NOT NULL DEFAULT 'CAD'")
            )
        if "transactions" in tables and "transfer_id" not in transactions_cols:
            conn.execute(text("ALTER TABLE transactions ADD COLUMN transfer_id TEXT"))


# Flag so daily backup / prune only runs once per Python process even though
# init_db() is called from every Streamlit page on every rerun.
_app_started = False


def init_db() -> None:
    """Create tables, apply additive migrations, and run startup backup.

    Idempotent — safe to call on every app start. Backup work happens at
    most once per process.
    """
    global _app_started
    # Importing models registers them with Base.metadata.
    from core import models  # noqa: F401

    Base.metadata.create_all(engine)
    _migrate()

    # Sync active currency from settings every init — cheap, ensures every
    # page sees the user's currency choice even on first navigation.
    try:
        from core.money import set_active_currency
        from core.settings_service import get_currency_code
        with SessionLocal() as s:
            set_active_currency(get_currency_code(s))
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Currency sync failed: {e}")

    if not _app_started:
        _app_started = True
        try:
            from core.backup_service import daily_backup_if_needed, prune_old_backups
            daily_backup_if_needed()
            prune_old_backups()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Startup backup tasks failed: {e}")

        # Catch up archives for any loans/financing that were paid off
        # before the archive feature existed (or via direct balance edits).
        try:
            from core.archive_service import reconcile_all_archives
            with SessionLocal() as s:
                reconcile_all_archives(s)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                f"Startup archive reconcile failed: {e}"
            )

        # Bootstrap exchange rates if missing, then kick off the background
        # auto-updater thread which fires at scheduled slots (9am/1pm/5pm/9pm).
        try:
            from core.exchange_service import (
                all_rates,
                auto_update_if_needed,
                start_auto_updater_thread,
            )
            from core.money import active_currency_code
            with SessionLocal() as s:
                # First-time install: do a synchronous fetch so the UI has
                # data to show immediately. After that, the thread handles it.
                if not all_rates(s):
                    auto_update_if_needed(s, active_currency_code())
            start_auto_updater_thread()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                f"Exchange-rate auto-update setup failed: {e}"
            )
