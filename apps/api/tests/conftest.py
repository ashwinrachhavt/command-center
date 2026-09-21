import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session

from command_center.core.config import Settings
from command_center.db import artifacts, evidence, models  # noqa: F401
from command_center.db.session import create_database_engine

TEST_DATABASE_URL = os.environ.get(
    "CC_TEST_DATABASE_URL",
    "postgresql+psycopg://test:test-only@127.0.0.1:55433/command_center_test",
)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        api_token="synthetic-test-token-with-at-least-32-characters",
        database_url=TEST_DATABASE_URL,
        allowed_hosts=["testserver"],
    )


@pytest.fixture(scope="session")
def migration_config() -> Iterator[Config]:
    if make_url(TEST_DATABASE_URL).database != "command_center_test":
        raise RuntimeError("Tests require the dedicated command_center_test database")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("CC_DATABASE_URL", TEST_DATABASE_URL)
        patch.setenv("CC_API_TOKEN", "synthetic-test-token-with-at-least-32-characters")
        yield Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))


@pytest.fixture(scope="session")
def engine(migration_config: Config) -> Iterator[Engine]:
    command.upgrade(migration_config, "head")
    database = create_database_engine(TEST_DATABASE_URL)
    yield database
    database.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode="create_savepoint") as database:
            yield database
        transaction.rollback()
