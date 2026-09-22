"""Supported LangGraph PostgreSQL persistence, separate from domain transactions."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row
from sqlalchemy.engine import make_url

from command_center.core.config import Settings


@asynccontextmanager
async def checkpoint_store(settings: Settings) -> AsyncIterator[AsyncPostgresSaver]:
    if settings.database_pool_mode == "transaction" and not settings.agent_checkpoint_database_url:
        raise ValueError("checkpoint_connection_required")
    url = make_url(settings.agent_checkpoint_database_url or settings.database_url)
    connection = url.set(drivername="postgresql").render_as_string(hide_password=False)
    async with await AsyncConnection.connect(
        connection,
        autocommit=True,
        prepare_threshold=None,
        row_factory=dict_row,
        connect_timeout=5,
        options="-c search_path=agent_checkpoints -c statement_timeout=15000",
    ) as conn:
        saver = AsyncPostgresSaver(conn)
        # Saver migrations include concurrent indexes; use its documented autocommit
        # connection and serialize first-use setup between prefork workers.
        await conn.execute("SELECT pg_advisory_lock(706631582)")
        try:
            await saver.setup()
            for table in (
                "checkpoints",
                "checkpoint_blobs",
                "checkpoint_writes",
                "checkpoint_migrations",
            ):
                await conn.execute(
                    sql.SQL("ALTER TABLE {} ENABLE ROW LEVEL SECURITY").format(
                        sql.Identifier(table)
                    )
                )
        finally:
            await conn.execute("SELECT pg_advisory_unlock(706631582)")
        yield saver
