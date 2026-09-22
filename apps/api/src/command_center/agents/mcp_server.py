"""Internal MCP adapter. Tool discovery is scoped to a live, leased agent run."""

from typing import Any, cast

from fastapi import HTTPException
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from command_center.agents.config import AgentProfile
from command_center.agents.tools import ToolRegistry
from command_center.core.capabilities import authenticate_run, issue_run_token, role_profile
from command_center.core.config import Settings
from command_center.db.agents import AgentRun


class AgentMCP:
    def __init__(self, settings: Settings):
        self.server: Server[Any, Any] = Server("command-center", version="0.1.0")
        self.manager = StreamableHTTPSessionManager(
            app=self.server,
            stateless=True,
            json_response=True,
            max_request_body_size=1_000_000,
            security_settings=TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=[
                    value for host in settings.allowed_hosts for value in (host, host + ":*")
                ],
                allowed_origins=settings.clerk_authorized_parties,
            ),
        )

        @self.server.list_tools()  # type: ignore[no-untyped-call, untyped-decorator]
        async def list_tools() -> list[types.Tool]:
            registry = await run_in_threadpool(self.registry)
            return [
                types.Tool(
                    name=t["function"]["name"],
                    description=t["function"]["description"],
                    inputSchema=t["function"]["parameters"],
                    annotations=types.ToolAnnotations(
                        readOnlyHint=t["function"]["name"]
                        not in {
                            "create_task",
                            "draft_artifact",
                            "memory_append",
                            "capture_lead",
                            "enrich_lead",
                            "propose_profile_fact",
                        },
                        destructiveHint=False,
                        openWorldHint=t["function"]["name"]
                        not in {
                            "workspace_summary",
                            "create_task",
                            "draft_artifact",
                            "memory_read",
                            "memory_append",
                            "document_read",
                            "propose_profile_fact",
                            "approved_profile",
                            "lead_evidence",
                            "capture_lead",
                        },
                    ),
                )
                for t in registry.schemas
            ]

        # Validate with this request's pinned schema, not a shared per-name cache.
        @self.server.call_tool(validate_input=False)  # type: ignore[untyped-decorator]
        async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
            request = cast(Request, self.server.request_context.request)
            call_id = request.headers.get("x-tool-call-id", "")
            if not call_id or len(call_id) > 200:
                return [
                    types.TextContent(
                        type="text", text="Denied: a stable tool-call ID is required."
                    )
                ]
            registry = await run_in_threadpool(self.registry)
            result = await run_in_threadpool(registry.execute, name, arguments, call_id)
            return [types.TextContent(type="text", text=result)]

    def registry(self) -> ToolRegistry:
        request = cast(Request, self.server.request_context.request)
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        actor_id, run_id = authenticate_run(
            request, token, audience="command-center-mcp", check_scope=False
        )
        with Session(request.app.state.engine) as db:
            run = db.get(AgentRun, run_id)
            assert run and run.lease_id
            role = request.state.agent_role
            profile = AgentProfile.model_validate(role_profile(run.config_snapshot, role))
            api_token = issue_run_token(request.app.state.settings, run_id, run.lease_id, role=role)
        return ToolRegistry(request.app.state.settings, profile, actor_id, run_id, api_token)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive)
        try:
            token = request.headers.get("authorization", "").removeprefix("Bearer ")
            await run_in_threadpool(
                authenticate_run, request, token, audience="command-center-mcp", check_scope=False
            )
        except HTTPException as exc:
            await JSONResponse({"detail": exc.detail}, status_code=exc.status_code)(
                scope, receive, send
            )
            return
        await self.manager.handle_request(scope, receive, send)
