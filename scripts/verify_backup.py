"""Check a SQLite backup's integrity and foreign keys without restoring it."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.backups import verify_backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", type=Path)
    args = parser.parse_args()
    try:
        verify_backup(args.backup)
    except Exception:
        print("Backup verification failed.", file=sys.stderr)
        return 1
    print("Backup integrity and foreign-key checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
