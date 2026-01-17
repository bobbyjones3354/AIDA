from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
try:
    from app.models import Base
except ModuleNotFoundError:
    from models import Base

SQLALCHEMY_DATABASE_URL = "sqlite:///./aida.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.create_all(bind=engine)

def _ensure_sqlite_column(table: str, column: str, column_type: str) -> None:
    if engine.url.get_backend_name() != "sqlite":
        return
    with engine.begin() as conn:
        rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
        existing = {row[1] for row in rows}
        if column not in existing:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}"))

_ensure_sqlite_column("articles", "impact_level", "TEXT")
_ensure_sqlite_column("articles", "impact_reason", "TEXT")
_ensure_sqlite_column("articles", "image_url", "TEXT")
