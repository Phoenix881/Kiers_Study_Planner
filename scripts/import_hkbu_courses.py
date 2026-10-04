"""Import an academic-year Handbook catalogue; ordinary pages never fetch HKBU."""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.orm import Session  # noqa: E402

from app.db import engine  # noqa: E402
from app.sources.handbook import import_handbook  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("academic_year", help="e.g. 2026-2027")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    with Session(engine) as session:
        report = import_handbook(session, args.academic_year, dry_run=args.dry_run)
    result = asdict(report)
    result["committed"] = not args.dry_run and not report.errors
    print(json.dumps(result, indent=2))
    return 1 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
