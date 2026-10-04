from sqlalchemy import engine_from_config, pool

from alembic import context
from app import models  # noqa: F401
from app.config import DATA_DIR, DATABASE_URL
from app.db import Base

config = context.config
config.set_main_option("sqlalchemy.url", DATABASE_URL.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    DATA_DIR.mkdir(exist_ok=True)
    engine = engine_from_config(
        config.get_section(config.config_ini_section), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with engine.connect() as connection:
        if connection.dialect.name == "sqlite":
            # Batch copies preserve IDs. Disabling FKs outside the transaction prevents
            # DROP TABLE from cascading into the old table's dependent records.
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=True,
            transactional_ddl=True,
        )
        try:
            with context.begin_transaction():
                context.run_migrations()
            if (
                connection.dialect.name == "sqlite"
                and connection.exec_driver_sql("PRAGMA foreign_key_check").all()
            ):
                raise RuntimeError("Database foreign-key validation failed")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
