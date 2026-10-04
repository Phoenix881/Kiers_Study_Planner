"""Preview old expired/consumed token counts; --apply deletes eligible rows."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.orm import Session

from app.db import engine
from app.services.token_cleanup import cleanup_tokens


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--older-than-days", type=int, default=30)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not 0 <= args.older_than_days <= 36500:
        parser.error("--older-than-days must be between 0 and 36500")
    try:
        with Session(engine) as session:
            result = cleanup_tokens(session, args.older_than_days, args.apply)
            if args.apply:
                session.commit()
    except Exception:
        print("Token cleanup failed. Check database configuration and schema.", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
