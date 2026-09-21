from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from command_center.db.session import database_is_ready


def test_upgrade_downgrade_upgrade_and_no_schema_drift(
    engine: Engine, migration_config: Config
) -> None:
    assert database_is_ready(engine)
    command.check(migration_config)
    command.downgrade(migration_config, "base")
    assert inspect(engine).get_table_names() == ["alembic_version"]
    assert not database_is_ready(engine)
    command.upgrade(migration_config, "head")
    assert database_is_ready(engine)
    command.check(migration_config)
