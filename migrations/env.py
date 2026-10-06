import os

from alembic import context

from app import models  # noqa: F401 -- register tables in Base.metadata
from app.db import Base, create_db_engine

config = context.config
target_metadata = Base.metadata
url = (
    config.get_main_option("sqlalchemy.url")
    or os.environ.get("DATABASE_URL")
    or "sqlite:///./kvitto.db"
)


def run_migrations_offline() -> None:
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_db_engine(url)
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
