"""Celery dispatch; PostgreSQL remains the authoritative run ledger."""

from uuid import UUID

from celery import Celery
from sqlalchemy import select
from sqlalchemy.orm import Session

from command_center.agents.worker import perform_next
from command_center.core.config import Settings
from command_center.db.agents import AgentRun
from command_center.db.document_imports import DocumentImport
from command_center.db.session import create_database_engine
from command_center.documents.worker import perform_document_import

settings = Settings()
celery = Celery("command_center", broker=settings.redis_url)
celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_ignore_result=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    task_soft_time_limit=840,
    task_time_limit=900,
    broker_transport_options={"visibility_timeout": 1200},
    beat_schedule={
        "dispatch-persisted-runs": {
            "task": "command_center.dispatch",
            "schedule": 5.0,
            "options": {"expires": 5},
        }
    },
    timezone="UTC",
)


@celery.task(name="command_center.dispatch")
def dispatch() -> int:
    engine = create_database_engine(settings.database_url, settings.database_pool_mode)
    try:
        with Session(engine) as db, db.begin():
            AgentRun.expire_stale(db)
            DocumentImport.expire_stale(db)
            pending = list(
                db.scalars(
                    select(AgentRun.id)
                    .where(AgentRun.state == "queued")
                    .order_by(AgentRun.created_at)
                    .limit(20)
                )
            )
            pending_documents = list(
                db.scalars(
                    select(DocumentImport.id)
                    .where(DocumentImport.state == "queued")
                    .order_by(DocumentImport.created_at)
                    .limit(20)
                )
            )
        # A broker outage leaves SQL rows queued. The next beat retries dispatch.
        for run_id in pending:
            execute_run.apply_async(args=(str(run_id),), task_id=str(run_id), expires=60)
        for import_id in pending_documents:
            execute_document_import.apply_async(
                args=(str(import_id),),
                task_id=f"document-import:{import_id}",
                expires=60,
            )
        return len(pending) + len(pending_documents)
    finally:
        engine.dispose()


@celery.task(name="command_center.execute_run")
def execute_run(run_id: str) -> bool:
    engine = create_database_engine(settings.database_url, settings.database_pool_mode)
    try:
        # Duplicate deliveries cannot claim a running/completed row.
        return perform_next(engine, settings, UUID(run_id))
    finally:
        engine.dispose()


@celery.task(name="command_center.execute_document_import")
def execute_document_import(import_id: str) -> bool:
    engine = create_database_engine(settings.database_url, settings.database_pool_mode)
    try:
        return perform_document_import(engine, settings, UUID(import_id))
    finally:
        engine.dispose()
