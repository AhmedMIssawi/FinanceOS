"""Backup management for the SQLite database.

Capabilities:
- `create_backup(label=None)` — copy the live DB to backups/ with a timestamp.
- `list_backups()` — sorted list (newest first) of available backups.
- `restore_backup(path)` — replace the live DB with a saved snapshot.
- `daily_backup_if_needed()` — idempotent once-per-day backup on app start.
- `prune_old_backups(keep_days=14)` — delete backups older than N days.
- `reset_database()` — drop and recreate all tables (auto-backs up first).

Files are named `finance_<YYYY-MM-DD>_<HH-MM-SS>[_<label>].db` so the
filename itself encodes when the snapshot was taken.
"""
import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from core.db import DATA_DIR, DB_PATH

BACKUP_DIR = DATA_DIR / "backups"
LOGGER = logging.getLogger(__name__)


def _safe_label(label: str) -> str:
    return "".join(c for c in label if c.isalnum() or c in "-_")[:40]


def create_backup(label: Optional[str] = None) -> Path:
    """Copy the current DB to backups/ with a timestamped filename."""
    if not DB_PATH.exists():
        raise FileNotFoundError(f"No database to back up at {DB_PATH}")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    name = f"finance_{ts}.db"
    if label:
        safe = _safe_label(label)
        if safe:
            name = f"finance_{ts}_{safe}.db"
    dest = BACKUP_DIR / name
    shutil.copy2(DB_PATH, dest)
    return dest


def list_backups() -> list[tuple[Path, datetime, int]]:
    """Return (path, mtime, size_bytes) per backup, newest first."""
    if not BACKUP_DIR.exists():
        return []
    items: list[tuple[Path, datetime, int]] = []
    for p in BACKUP_DIR.glob("finance_*.db"):
        stat = p.stat()
        items.append((p, datetime.fromtimestamp(stat.st_mtime), stat.st_size))
    # Sort by mtime desc, fall back to filename so ties (sub-second
    # creations on Windows) have a deterministic order.
    items.sort(key=lambda t: (t[1], t[0].name), reverse=True)
    return items


def restore_backup(backup_path: Path) -> None:
    """Replace the live DB with a snapshot. Caller should close sessions first."""
    if not backup_path.exists():
        raise FileNotFoundError(f"Backup not found: {backup_path}")
    shutil.copy2(backup_path, DB_PATH)


def daily_backup_if_needed() -> Optional[Path]:
    """Create one backup per calendar day. Returns new path if created."""
    if not DB_PATH.exists():
        return None
    today_str = datetime.now().strftime("%Y-%m-%d")
    if BACKUP_DIR.exists():
        for p in BACKUP_DIR.glob(f"finance_{today_str}*.db"):
            return None  # already have today's
    return create_backup(label="daily")


def prune_old_backups(keep_days: int = 14) -> int:
    """Delete backups whose mtime is older than keep_days. Returns count deleted."""
    if not BACKUP_DIR.exists():
        return 0
    cutoff = datetime.now() - timedelta(days=keep_days)
    count = 0
    for p in BACKUP_DIR.glob("finance_*.db"):
        if datetime.fromtimestamp(p.stat().st_mtime) < cutoff:
            try:
                p.unlink()
                count += 1
            except OSError as e:
                LOGGER.warning(f"Couldn't delete {p}: {e}")
    return count


def reset_database() -> Path:
    """Drop and recreate ALL tables — wipes every row of user data.

    A 'pre-reset' backup is created first so the user can recover.
    Returns the path to that pre-reset backup.
    """
    backup_path = create_backup(label="pre-reset")
    from core import models  # noqa: F401
    from core.db import Base, engine
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    return backup_path


def delete_all_backups() -> int:
    """Delete every backup file. Returns the count deleted.

    Pair this with `reset_database()` to perform a true privacy wipe —
    no traces left for a tester to recover."""
    if not BACKUP_DIR.exists():
        return 0
    count = 0
    for p in BACKUP_DIR.glob("finance_*.db"):
        try:
            p.unlink()
            count += 1
        except OSError as e:
            LOGGER.warning(f"Couldn't delete {p}: {e}")
    return count
