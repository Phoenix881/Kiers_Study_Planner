"""Private, consistent SQLite backups and read-only verification."""

import os
import re
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.engine import make_url

PATTERN = re.compile(r"kiers-study-planner-\d{8}T\d{12}Z\.sqlite3")


def database_path(url):
    parsed = make_url(url)
    if (
        parsed.get_backend_name() != "sqlite"
        or not parsed.database
        or parsed.database == ":memory:"
        or parsed.query
    ):
        raise ValueError("Backups require a file-backed SQLite DATABASE_URL without URI options.")
    path = Path(parsed.database).expanduser().resolve()
    if not path.is_file():
        raise ValueError("The source database must already exist.")
    return path


def verify_backup(path):
    path = Path(path).resolve(strict=True)
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("Backup integrity check failed.")
        if db.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Backup foreign-key check failed.")
    return True


def backup_database(url, directory, verify=False, keep=None):
    if keep is not None and keep < 1:
        raise ValueError("Keep at least one backup.")
    source = database_path(url)
    directory = Path(directory).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    name = (
        "kiers-study-planner-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        + ".sqlite3"
    )
    destination = directory / name
    descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    started = time.monotonic()

    def progress(status, remaining, total):
        if time.monotonic() - started > 60:
            raise TimeoutError("Backup did not complete within 60 seconds.")

    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src:
            with closing(sqlite3.connect(destination)) as dst:
                src.backup(dst, pages=256, progress=progress, sleep=0.01)
        checked = verify or keep is not None
        if checked:
            verify_backup(destination)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    removed = 0
    if keep is not None:
        candidates = sorted(
            (
                p
                for p in directory.iterdir()
                if PATTERN.fullmatch(p.name)
                and p.is_file()
                and not p.is_symlink()
                and p.resolve() != source
            ),
            key=lambda p: p.name,
            reverse=True,
        )
        older = [p for p in candidates if p != destination]
        for old in older[keep - 1 :]:
            old.unlink()
            removed += 1
    return {
        "file": str(destination),
        "bytes": destination.stat().st_size,
        "verified": checked,
        "removed": removed,
    }
