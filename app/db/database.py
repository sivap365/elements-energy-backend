import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from dotenv import load_dotenv

# Explicitly find and load .env from the project root
load_dotenv(dotenv_path=os.path.join(
    os.path.dirname(__file__), '..', '..', '.env'))

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://elements:elements_pass@localhost:5432/elements_energy"  # fallback
)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,       # Detects stale connections
    pool_size=10,             # Max persistent connections
    max_overflow=20,          # Extra connections under load
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency — yields a DB session, always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
