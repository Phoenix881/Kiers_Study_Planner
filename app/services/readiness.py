from functools import lru_cache

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.config import ROOT


@lru_cache(maxsize=1)
def expected_revision():
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("path_separator", "os")
    config.set_main_option("script_location", str(ROOT / "alembic"))
    return ScriptDirectory.from_config(config).get_current_head()


def database_readiness(session):
    try:
        session.execute(text("SELECT 1"))
        revisions = list(session.scalars(text("SELECT version_num FROM alembic_version")))
        return len(revisions) == 1 and revisions[0] == expected_revision()
    except Exception:
        try:
            session.rollback()
        except Exception:
            pass
        return False
