from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

SCHEMA_REVISION = "0036_email_delivery"


def create_database_engine(database_url: str, pool_mode: str = "session") -> Engine:
    if pool_mode == "transaction":
        return create_engine(
            database_url,
            poolclass=NullPool,
            connect_args={"connect_timeout": 5, "prepare_threshold": None},
        )
    return create_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        connect_args={
            "connect_timeout": 5,
            "options": "-c timezone=UTC -c statement_timeout=15000",
        },
    )


def database_is_ready(engine: Engine) -> bool:
    try:
        with engine.connect() as connection:
            revisions = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalars()
            return list(revisions) == [SCHEMA_REVISION]
    except SQLAlchemyError:
        return False
