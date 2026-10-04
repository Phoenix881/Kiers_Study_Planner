"""Apply versioned migrations: python scripts/init_db.py."""

from alembic.config import Config

from alembic import command
from app.config import ROOT


def main():
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    print("Database is up to date.")


if __name__ == "__main__":
    main()
