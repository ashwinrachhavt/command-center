"""Celery dispatch; PostgreSQL remains the authoritative run ledger."""

from uuid import UUID

from celery import Celery
from sqlalchemy import select
from sqlalchemy.orm import Session

from command_center.actions.worker import perform_reviewed_action
from command_center.agents.spending import connected_tool_reserver
from command_center.agents.worker import perform_next
from command_center.core.config import Settings
from command_center.db.agents import AgentRun
from command_center.db.document_imports import DocumentImport
from command_center.db.pdf_exports import PdfExport
from command_center.db.research_executions import ResearchExecution
from command_center.db.reviewed_actions import ReviewedAction
from command_center.db.session import create_database_engine
from command_center.db.spending import SpendingReservation
from command_center.documents.pdf_worker import perform_pdf_export, reap_pdf_sandboxes
from command_center.documents.worker import perform_document_import
from command_center.research.worker import perform_research_execution, reap_research_sandboxes

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
    task_default_queue="control",
    task_routes={
        "command_center.execute_run": {"queue": "agents"},
        "command_center.execute_document_import": {"queue": "documents"},
        "command_center.execute_reviewed_action": {"queue": "actions"},
        "command_center.execute_research_execution": {"queue": "execution"},
        "command_center.execute_pdf_export": {"queue": "execution"},
        "command_center.cleanup_execution_containers": {"queue": "execution"},
    },
    beat_schedule={
        "dispatch-persisted-runs": {
            "task": "command_center.dispatch",
            "schedule": 5.0,
            "options": {"expires": 5},
        },
        "cleanup-interrupted-containers": {
            "task": "command_center.cleanup_execution_containers",
            "schedule": 30.0,
            "options": {"expires": 25},
        },
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
            ReviewedAction.expire_stale(db)
            ResearchExecution.expire_stale(db)
            PdfExport.expire_stale(db)
            SpendingReservation.expire_stale(db)
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
            pending_actions = list(
                db.scalars(
                    select(ReviewedAction.id)
                    .where(ReviewedAction.state == "queued")
                    .order_by(ReviewedAction.created_at)
                    .limit(20)
                )
            )
            pending_research = list(
                db.scalars(
                    select(ResearchExecution.id)
                    .where(ResearchExecution.state == "queued")
                    .order_by(ResearchExecution.created_at)
                    .limit(20)
                )
            )
            pending_exports = list(
                db.scalars(
                    select(PdfExport.id)
                    .where(PdfExport.state == "queued")
                    .order_by(PdfExport.created_at)
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
        for task, ids, prefix in (
            (execute_reviewed_action, pending_actions, "reviewed-action"),
            (execute_research_execution, pending_research, "research-execution"),
            (execute_pdf_export, pending_exports, "pdf-export"),
        ):
            for identifier in ids:
                task.apply_async(
                    args=(str(identifier),), task_id=f"{prefix}:{identifier}", expires=60
                )
        return sum(
            map(
                len,
                (pending, pending_documents, pending_actions, pending_research, pending_exports),
            )
        )
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


@celery.task(name="command_center.execute_reviewed_action")
def execute_reviewed_action(action_id: str) -> bool:
    engine = create_database_engine(settings.database_url, settings.database_pool_mode)
    try:
        with Session(engine) as db:
            action = db.get(ReviewedAction, UUID(action_id))
            if action is None:
                return False
            reserve = connected_tool_reserver(
                engine,
                owner_id=action.owner_id,
                task_id=action.task_id,
                opportunity_id=action.opportunity_id,
                request_scope_id=action.id
                if action.task_id is None and action.opportunity_id is None
                else None,
            )
        return perform_reviewed_action(engine, settings, action_id, reserve_budget=reserve)
    finally:
        engine.dispose()


@celery.task(name="command_center.execute_research_execution")
def execute_research_execution(execution_id: str) -> bool:
    engine = create_database_engine(settings.database_url, settings.database_pool_mode)
    try:
        return perform_research_execution(engine, settings, execution_id)
    finally:
        engine.dispose()


@celery.task(name="command_center.execute_pdf_export")
def execute_pdf_export(export_id: str) -> bool:
    engine = create_database_engine(settings.database_url, settings.database_pool_mode)
    try:
        return perform_pdf_export(engine, settings, export_id)
    finally:
        engine.dispose()


@celery.task(name="command_center.cleanup_execution_containers")
def cleanup_execution_containers() -> int:
    engine = create_database_engine(settings.database_url, settings.database_pool_mode)
    try:
        return reap_research_sandboxes(engine) + reap_pdf_sandboxes(engine)
    finally:
        engine.dispose()
