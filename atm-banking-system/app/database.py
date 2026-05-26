
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()

# engine setup
_connect_args: dict = {}
if settings.database_url.startswith("sqlite"):
    # SQLite requires check_same_thread=False for multi-threaded use
    _connect_args = {"check_same_thread": False}

engine = create_engine(
    settings.database_url,
    connect_args=_connect_args,
    # Connection pool tuning (ignored by SQLite)
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    echo=settings.debug,
)

# Enable WAL mode and foreign-key enforcement for SQLite
if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

# session factory
SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)



class Base(DeclarativeBase):
    """All ORM models inherit from this base."""
    pass



def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that yields a database session and guarantees
    the session is closed after the request, even on exceptions.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_context() -> Generator[Session, None, None]:
    """
    Context-manager version for use outside FastAPI request scope
    (e.g., scripts, background tasks).
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def create_all_tables() -> None:
    """Create all tables defined in ORM models (used in tests and dev)."""
    # Import models so SQLAlchemy registers them before create_all
    import app.models  # noqa: F401
    Base.metadata.create_all(bind=engine)


def drop_all_tables() -> None:
    """Drop all tables — used only in test teardown."""
    Base.metadata.drop_all(bind=engine)
