"""Celery calls this execution boundary; domain transitions stay on AgentRun."""

import logging
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from command_center.agents.config import AgentProfile
from command_center.agents.mcp_client import MCPTools
from command_center.agents.runtime import openai_model, run_graph
from command_center.core.capabilities import issue_run_token
from command_center.core.config import Settings
from command_center.db import artifacts, browser, evidence  # noqa: F401
from command_center.db.agents import AgentRun
from command_center.db.base import utc_now

logger = logging.getLogger(__name__)


class LeaseLost(Exception):
    pass


def leased(db: Session, run_id: UUID, lease_id: UUID) -> AgentRun:
    run = db.scalar(select(AgentRun).where(AgentRun.id == run_id).with_for_update())
    if (
        run is None
        or run.state != "running"
        or run.lease_id != lease_id
        or run.lease_expires_at is None
        or run.lease_expires_at <= utc_now()
    ):
        raise LeaseLost()
    return run


def perform_next(engine: Engine, settings: Settings, run_id: UUID | None = None) -> bool:
    with Session(engine, expire_on_commit=False) as db, db.begin():
        run = AgentRun.claim(db, run_id)
        if run is None:
            return False
        run_id, lease_id, prompt, snapshot = (
            run.id,
            run.lease_id,
            run.prompt,
            run.config_snapshot,
        )
        assert lease_id

    def checkpoint(state: dict[str, Any]) -> None:
        with Session(engine) as db, db.begin():
            current = leased(db, run_id, lease_id)
            current.checkpoint = state
            current.lease_expires_at = utc_now() + timedelta(minutes=5)

    output, error_code = None, None
    try:
        if not settings.openai_api_key.get_secret_value():
            raise ValueError("OpenAI key is not configured")
        profile = AgentProfile.model_validate(snapshot["profile"])
        registry = MCPTools(
            settings.internal_api_url,
            issue_run_token(settings, run_id, lease_id, audience="command-center-mcp"),
        )
        output = run_graph(
            profile, prompt, registry, checkpoint, model=openai_model(settings, profile)
        )
    except LeaseLost:
        return True
    except Exception:
        error_code = "agent_execution_failed"
        logger.warning("Agent run %s failed; provider details suppressed", run_id)
    try:
        with Session(engine) as db, db.begin():
            current = leased(db, run_id, lease_id)
            current.finish(
                "failed" if error_code else "completed", output=output, error_code=error_code
            )
    except LeaseLost:
        pass
    return True
