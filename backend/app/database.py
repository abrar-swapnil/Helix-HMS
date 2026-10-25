"""database.py - SQLAlchemy engine + session factory (works with MySQL; SQLite is only a dev/test fallback)."""
from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

_connect_args: dict = {}
_engine_kwargs: dict = {"pool_pre_ping": True}          # transparently re-open connections MySQL has closed
if settings.is_sqlite:
    _connect_args = {"check_same_thread": False}
else:
    _engine_kwargs.update(pool_recycle=280, pool_size=10, max_overflow=10)   # MySQL drops idle connections (~300s)
    if settings.DB_SSL_CA:
        _connect_args["ssl"] = {"ca": settings.DB_SSL_CA}
    elif settings.DB_SSL:
        import ssl as _ssl
        _connect_args["ssl"] = _ssl.create_default_context()

engine = create_engine(settings.DATABASE_URL, connect_args=_connect_args, **_engine_kwargs)

if settings.is_sqlite:
    @event.listens_for(engine, "connect")
    def _sqlite_fk(dbapi_conn, _):                       # enforce foreign keys on SQLite like MySQL does
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency: one DB session per request, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
