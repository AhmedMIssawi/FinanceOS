"""Tests for core/backup_service.py.

Filesystem operations are isolated to a tmp_path via monkeypatching of
DB_PATH and BACKUP_DIR so tests never touch the real data directory.
"""
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import core.backup_service as bs


@pytest.fixture
def fake_paths(monkeypatch, tmp_path):
    fake_db = tmp_path / "test.db"
    fake_db.write_bytes(b"fake-db-content-v1")
    fake_backups = tmp_path / "backups"
    monkeypatch.setattr(bs, "DB_PATH", fake_db)
    monkeypatch.setattr(bs, "BACKUP_DIR", fake_backups)
    return {"db": fake_db, "backups": fake_backups}


def test_create_backup_copies_file(fake_paths):
    result = bs.create_backup()
    assert result.exists()
    assert result.read_bytes() == b"fake-db-content-v1"
    assert result.parent == fake_paths["backups"]


def test_create_backup_with_label_includes_label(fake_paths):
    result = bs.create_backup(label="manual-test")
    assert "manual-test" in result.name


def test_create_backup_sanitises_unsafe_label_chars(fake_paths):
    result = bs.create_backup(label="bad/../name with spaces!")
    # Slashes, dots, spaces, and ! should be stripped.
    assert "/" not in result.name
    assert " " not in result.name
    assert "!" not in result.name


def test_create_backup_raises_when_no_db(monkeypatch, tmp_path):
    missing = tmp_path / "nope.db"
    monkeypatch.setattr(bs, "DB_PATH", missing)
    monkeypatch.setattr(bs, "BACKUP_DIR", tmp_path / "backups")
    with pytest.raises(FileNotFoundError):
        bs.create_backup()


def test_list_backups_newest_first(fake_paths):
    first = bs.create_backup(label="first")
    time.sleep(0.05)  # ensure different mtime
    second = bs.create_backup(label="second")
    listed = bs.list_backups()
    assert listed[0][0] == second
    assert listed[1][0] == first


def test_restore_backup_replaces_db(fake_paths):
    backup = bs.create_backup()
    # Now corrupt the live DB
    fake_paths["db"].write_bytes(b"corrupted")
    bs.restore_backup(backup)
    assert fake_paths["db"].read_bytes() == b"fake-db-content-v1"


def test_daily_backup_creates_once(fake_paths):
    a = bs.daily_backup_if_needed()
    b = bs.daily_backup_if_needed()
    assert a is not None
    assert b is None  # second call same day = no-op


def test_prune_removes_old_backups(fake_paths):
    fresh = bs.create_backup(label="fresh")
    old = bs.create_backup(label="old")
    # Backdate `old` to 30 days ago.
    old_time = (datetime.now() - timedelta(days=30)).timestamp()
    os.utime(old, (old_time, old_time))

    deleted = bs.prune_old_backups(keep_days=14)
    assert deleted == 1
    assert fresh.exists()
    assert not old.exists()


def test_prune_with_no_backup_dir_returns_zero(monkeypatch, tmp_path):
    monkeypatch.setattr(bs, "BACKUP_DIR", tmp_path / "nonexistent")
    assert bs.prune_old_backups() == 0


def test_delete_all_backups_removes_every_file(fake_paths):
    bs.create_backup(label="a")
    bs.create_backup(label="b")
    bs.create_backup(label="c")
    assert len(bs.list_backups()) == 3
    deleted = bs.delete_all_backups()
    assert deleted == 3
    assert bs.list_backups() == []


def test_delete_all_backups_with_no_dir_returns_zero(monkeypatch, tmp_path):
    monkeypatch.setattr(bs, "BACKUP_DIR", tmp_path / "nonexistent")
    assert bs.delete_all_backups() == 0
