from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.config import settings


def _normalise_url(url: str) -> str:
    """Hosted Postgres providers (Neon, Supabase, Render) hand out
    `postgres://` or `postgresql://` URLs. SQLAlchemy 2 rejects the former and
    would default the latter to psycopg2 — point both at psycopg 3, which is
    what requirements.txt installs."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


_url = _normalise_url(settings.database_url)

if _url.startswith("sqlite"):
    engine = create_engine(_url, connect_args={"check_same_thread": False})
else:
    # pool_pre_ping: serverless Postgres (e.g. Neon) drops idle connections,
    # and Render's free plan sleeps the app — test each pooled connection
    # before use instead of failing the first request after a wake-up.
    engine = create_engine(_url, pool_pre_ping=True, pool_recycle=300)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
