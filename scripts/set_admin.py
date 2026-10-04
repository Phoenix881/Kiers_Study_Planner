"""Explicitly grant/revoke an existing account's admin role; never create accounts."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import engine
from app.models import User
from app.services.account_security import invalidate_tokens
from app.services.accounts import audit_action


def set_admin(session, identifier, grant, force=False):
    connection = session.connection()
    if (
        connection.dialect.name == "sqlite"
        and not connection.connection.driver_connection.in_transaction
    ):
        connection.exec_driver_sql("BEGIN IMMEDIATE")
    normalized = identifier.strip().lower()
    user = session.scalar(
        select(User).where((User.username == normalized) | (User.email == normalized))
    )
    if user is None:
        raise ValueError("Account not found. No account was created.")
    if user.is_admin == grant:
        return user.username, False
    if (
        not grant
        and not force
        and session.scalar(select(func.count(User.id)).where(User.is_admin.is_(True))) <= 1
    ):
        raise ValueError("Refusing to revoke the last admin. Use --force explicitly if intended.")
    user.is_admin = grant
    user.auth_version += 1
    invalidate_tokens(session, user.id, "reset_password")
    audit_action(session, None, user, "grant_admin" if grant else "revoke_admin")
    return user.username, True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("identifier", help="Exact username or email")
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--grant", action="store_true")
    operation.add_argument("--revoke", action="store_true")
    parser.add_argument("--force", action="store_true", help="Allow revoking the last admin")
    args = parser.parse_args()
    try:
        with Session(engine) as session:
            username, changed = set_admin(session, args.identifier, args.grant, args.force)
            session.commit()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception:
        print("Admin update failed. Check database configuration and schema.", file=sys.stderr)
        return 1
    print(
        f"{username}: admin {'granted' if args.grant else 'revoked'}{' (unchanged)' if not changed else '; existing sessions revoked'}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
