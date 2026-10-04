"""Create a private SQLite backup; optionally verify and retain recent script-owned backups."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import DATA_DIR, DATABASE_URL
from app.services.backups import backup_database


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DATA_DIR / "backups")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--keep", type=int)
    args = parser.parse_args()
    if args.keep is not None and args.keep < 1:
        parser.error("--keep must be at least 1")
    try:
        result = backup_database(DATABASE_URL, args.output_dir, args.verify, args.keep)
    except Exception:
        print(
            "Backup failed. Check the SQLite database and destination permissions/configuration.",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
