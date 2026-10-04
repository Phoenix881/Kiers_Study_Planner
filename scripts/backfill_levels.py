"""Preview or apply the idempotent local catalogue-level repair."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.orm import Session

from app.db import engine
from app.services.levels import backfill_levels


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="Persist missing levels; otherwise preview only"
    )
    args = parser.parse_args()
    with Session(engine) as session:
        report = backfill_levels(session, apply=args.apply)
        if args.apply:
            session.commit()
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
