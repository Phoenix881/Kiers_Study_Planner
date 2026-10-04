from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session

from app.config import DATABASE_URL


class Base(DeclarativeBase):
    pass


def make_engine(url: str):
    engine = create_engine(
        url,
        connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
        hide_parameters=True,
    )
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def sqlite_settings(connection, _):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

    return engine


engine = make_engine(DATABASE_URL)


def get_session():
    with Session(engine) as session:
        yield session
