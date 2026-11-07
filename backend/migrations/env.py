"""Alembic environment: uses the app's settings and models."""
from alembic import context
from sqlalchemy import create_engine

from app.config import get_settings
from app.db import Base
from app import models  # noqa: F401  (registers the tables)

target_metadata = Base.metadata


def run_migrations_online() -> None:
    url = context.config.get_main_option("sqlalchemy.url") or get_settings().database_url
    engine = create_engine(url)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
