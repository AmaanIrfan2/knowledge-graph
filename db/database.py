from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
from typing import Generator

from alembic.config import Config
from alembic import command

from config.settings import DATABASE_URL

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _ensure_database_exists() -> None:
    url = make_url(DATABASE_URL)
    db_name = url.database
    maintenance_url = url.set(database="postgres")
    maint_engine = create_engine(maintenance_url, isolation_level="AUTOCOMMIT")
    with maint_engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :db"), {"db": db_name}
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    maint_engine.dispose()


def init_db() -> None:
    _ensure_database_exists()
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
