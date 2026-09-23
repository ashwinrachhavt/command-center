from alembic import context

from command_center.core.config import Settings
from command_center.db import (  # noqa: F401
    agent_events,
    agent_questions,
    agents,
    application_materials,
    application_preparations,
    applications,
    artifacts,
    browser,
    contact_discovery,
    conversations,
    correspondence,
    crm,
    document_imports,
    evidence,
    idempotency,
    mcp_clients,
    memory,
    models,
    pdf_exports,
    profile_facts,
    record_work,
    research_executions,
    reviewed_actions,
    spending,
    writing,
)
from command_center.db.base import Base, UTCDateTime
from command_center.db.session import create_database_engine

settings = Settings()
database_url = settings.migration_database_url or settings.database_url
target_metadata = Base.metadata


def render_item(kind: str, obj: object, _: object) -> str | bool:
    if kind == "type" and isinstance(obj, UTCDateTime):
        return "sa.DateTime(timezone=True)"
    return False


if context.is_offline_mode():
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        render_item=render_item,
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_database_engine(database_url)
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
                render_item=render_item,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()
