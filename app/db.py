import os
import time

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./local.db")

_kwargs = {"connect_args": {"check_same_thread": False}} if DATABASE_URL.startswith("sqlite") else {"pool_pre_ping": True}
engine = create_engine(DATABASE_URL, **_kwargs)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _add_missing_columns():
    """Prosta migracja: dodaje kolumny, które pojawiły się po utworzeniu tabel (create_all ich nie doda)."""
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    wanted = {
        "users": {"only_job": "BOOLEAN NOT NULL DEFAULT TRUE"},
        "submissions": {"other_hours": "INTEGER"},
        "schedules": {"published": "BOOLEAN NOT NULL DEFAULT FALSE"},
    }
    with engine.begin() as conn:
        for table, cols in wanted.items():
            have = {c["name"] for c in insp.get_columns(table)}
            for name, ddl in cols.items():
                if name not in have:
                    default = ddl.replace("TRUE", "1").replace("FALSE", "0") if engine.dialect.name == "sqlite" else ddl
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {default}"))


def init_db(retries=30, delay=2.0):
    """Tworzy tabele. Czeka na bazę (kontener db może wstawać wolniej niż web)."""
    from . import models  # noqa: F401  (rejestruje tabele)

    for attempt in range(retries):
        try:
            Base.metadata.create_all(engine)
            _add_missing_columns()
            return
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(delay)
