"""Optional Langfuse observations; failures never change application execution."""

import logging
import os
from contextvars import ContextVar, Token
from functools import lru_cache
from typing import Any
from uuid import UUID

from langfuse import Langfuse, propagate_attributes

from command_center.agents.trace_content import TraceContent
from command_center.core.config import Settings

logger = logging.getLogger(__name__)
current_trace: ContextVar["RunTrace | None"] = ContextVar("run_trace", default=None)


@lru_cache(maxsize=4)
def _client(pid: int, url: str, public_key: str, secret_key: str, environment: str) -> Langfuse:
    # PID prevents a Celery child from using an exporter created before fork.
    return Langfuse(
        base_url=url,
        public_key=public_key,
        secret_key=secret_key,
        environment=environment,
        timeout=3,
        flush_at=10,
        flush_interval=1,
    )


def langfuse_client(settings: Settings) -> Langfuse | None:
    if not settings.langfuse_enabled:
        return None
    if not (
        settings.langfuse_base_url
        and settings.langfuse_public_key.get_secret_value()
        and settings.langfuse_secret_key.get_secret_value()
    ):
        logger.warning("Langfuse enabled but incomplete; tracing unavailable")
        return None
    return _client(
        os.getpid(),
        settings.langfuse_base_url,
        settings.langfuse_public_key.get_secret_value(),
        settings.langfuse_secret_key.get_secret_value(),
        settings.environment,
    )


class RunTrace:
    def __init__(
        self,
        client: Langfuse | None,
        run_id: UUID,
        session_id: UUID | None,
        profile: str,
        revision: str,
        *,
        content: TraceContent | None = None,
        request: Any = None,
    ):
        self.client = client
        self.content = content or TraceContent()
        self.trace_id = run_id.hex
        self.root: Any = None
        self.generations: dict[UUID, Any] = {}
        self.tools: dict[str, Any] = {}
        self.token: Token[RunTrace | None] | None = None
        self.attributes: dict[str, Any] = {
            "trace_name": "Command Center request",
            "session_id": str(session_id) if session_id else None,
            "tags": ["command-center", profile],
        }
        if client is not None:
            try:
                with propagate_attributes(**self.attributes):
                    self.root = client.start_observation(
                        trace_context={"trace_id": self.trace_id},
                        name="agent-run",
                        as_type="agent",
                        input=self.content.capture(request),
                        metadata={"run_id": str(run_id), "profile": profile, "revision": revision},
                    )
            except Exception:
                logger.warning("Langfuse run observation unavailable; details suppressed")

    def activate(self) -> None:
        self.token = current_trace.set(self)

    def model_start(
        self,
        call_id: UUID,
        role: str,
        provider: str,
        model: str,
        message_chars: int,
        tool_schema_chars: int,
        tool_count: int,
        *,
        messages: Any = None,
    ) -> None:
        if self.root is None:
            return
        try:
            with propagate_attributes(**self.attributes):
                self.generations[call_id] = self.root.start_observation(
                    name=f"{role}.model",
                    as_type="generation",
                    model=model,
                    input=self.content.capture(messages),
                    metadata={
                        "provider": provider,
                        "role": role,
                        "call_id": str(call_id),
                        "message_chars": message_chars,
                        "tool_schema_chars": tool_schema_chars,
                        "tool_count": tool_count,
                    },
                )
        except Exception:
            logger.warning("Langfuse generation unavailable; details suppressed")

    def model_end(
        self,
        call_id: UUID,
        usage: dict[str, int],
        *,
        error: bool = False,
        output: Any = None,
        cost_details: dict[str, float] | None = None,
    ) -> None:
        generation = self.generations.pop(call_id, None)
        if generation is None:
            return
        try:
            # Cache reads are a subset of total input, never additional input tokens.
            # Langfuse's model catalog prices these usage types independently.
            generation.update(
                cost_details=cost_details,
                output=self.content.capture(output if not error else {"error": "provider_error"}),
                usage_details={
                    "input": usage["input_tokens"] - usage.get("cached_input_tokens", 0),
                    "input_cached_tokens": usage.get("cached_input_tokens", 0),
                    "output": usage["output_tokens"],
                }
                if not error and any(usage.values())
                else None,
                metadata={
                    "usage_status": "unknown" if error or not any(usage.values()) else "reported"
                },
                level="ERROR" if error else "DEFAULT",
                status_message="provider_error" if error else None,
            )
            generation.end()
        except Exception:
            logger.warning("Langfuse generation completion unavailable; details suppressed")

    def activity(self, event_type: str, role: str, data: dict[str, Any]) -> None:
        if self.root is None or not event_type.startswith("tool-"):
            return
        try:
            call_id = str(data["tool_call_id"])
            if event_type == "tool-input-available":
                with propagate_attributes(**self.attributes):
                    self.tools[call_id] = self.root.start_observation(
                        name=str(data["tool_name"]),
                        as_type="tool",
                        input=self.content.capture(data.get("input")),
                        metadata={"role": role, "call_id": call_id},
                    )
            elif observation := self.tools.pop(call_id, None):
                observation.update(
                    output=self.content.capture(data.get("output", data.get("error_text"))),
                    level="ERROR" if event_type == "tool-output-error" else "DEFAULT",
                )
                observation.end()
        except Exception:
            logger.warning("Langfuse tool observation unavailable; details suppressed")

    def finish(
        self, state: str, error_code: str | None = None, *, reused: bool = False, output: Any = None
    ) -> None:
        try:
            if self.root is not None:
                for generation in self.generations.values():
                    generation.update(
                        metadata={"usage_status": "unknown"}, level="WARNING", status_message=state
                    )
                    generation.end()
                for observation in self.tools.values():
                    observation.update(status_message=state)
                    observation.end()
                self.root.update(
                    output=self.content.capture(
                        {"state": state, "answer": output, "error_code": error_code}
                    ),
                    metadata={"state": state, "error_code": error_code, "answer_reused": reused},
                    level="ERROR" if state == "failed" else "DEFAULT",
                    status_message=error_code or state,
                )
                self.root.end()
                if self.client is not None:
                    self.client.flush()
        except Exception:
            logger.warning("Langfuse flush unavailable; application result preserved")
        finally:
            if self.token is not None:
                current_trace.reset(self.token)
                self.token = None


def start_run_trace(
    settings: Settings,
    run_id: UUID,
    session_id: UUID | None,
    profile: str,
    revision: str,
    *,
    request: Any = None,
) -> RunTrace:
    try:
        client = langfuse_client(settings)
    except Exception:
        logger.warning("Langfuse client unavailable; details suppressed")
        client = None
    content = TraceContent.from_settings(settings)
    trace = RunTrace(
        client, run_id, session_id, profile, revision, content=content, request=request
    )
    trace.activate()
    return trace
