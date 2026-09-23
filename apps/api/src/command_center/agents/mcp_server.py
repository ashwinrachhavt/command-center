"""FastMCP transport with request-local authorization, catalogs and durable call IDs."""

from contextvars import ContextVar
from typing import Any

from fastapi import HTTPException, Request
from fastmcp import FastMCP
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from starlette.types import Message, Receive, Scope, Send

from command_center.agents.config import AgentProfile
from command_center.agents.mcp_catalog import CatalogProvider, add_api_tools, add_catalog_tools
from command_center.agents.mcp_policy import catalog_tool_names
from command_center.agents.tools import ToolRegistry
from command_center.core.capabilities import (
    CAPABILITIES,
    authenticate_run,
    issue_run_token,
    role_profile,
)
from command_center.core.config import Settings
from command_center.core.local_credentials import issue_client_api_token
from command_center.db.agents import AgentRun
from command_center.db.mcp_clients import MCPClientCredential

_current_request: ContextVar[Request] = ContextVar("mcp_request")


class AgentMCP:
    def __init__(self, settings: Settings):
        self.openapi: dict[str, Any] = {}
        self.server = FastMCP(
            "command-center",
            version="0.2.0",
            providers=[CatalogProvider(self.registry)],
            mask_error_details=True,
            strict_input_validation=False,
        )
        self.http_app = self.server.http_app(
            path="/",
            stateless_http=True,
            json_response=True,
            host_origin_protection=True,
            allowed_hosts=[
                value for host in settings.allowed_hosts for value in (host, host + ":*")
            ],
            allowed_origins=settings.clerk_authorized_parties,
        )

    def registry(self) -> tuple[ToolRegistry, bool, str]:
        request = _current_request.get()
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        local = token.startswith("cc_local.")
        if local:
            with Session(request.app.state.engine) as db:
                credential = MCPClientCredential.authenticate(db, token)
                actor_id, run_id = credential.owner_id, credential.id
            profile = AgentProfile(
                name="local-client",
                description="Actor-bound local MCP client",
                model="local-client",
                instructions="",
                tools=sorted(set(CAPABILITIES) | catalog_tool_names()),
            )
            api_token = issue_client_api_token(request.app.state.settings, run_id)
        else:
            actor_id, run_id = authenticate_run(
                request, token, audience="command-center-mcp", check_scope=False
            )
            with Session(request.app.state.engine) as db:
                run = db.get(AgentRun, run_id)
                assert run and run.lease_id
                role = request.state.agent_role
                profile = AgentProfile.model_validate(role_profile(run.config_snapshot, role))
                api_token = issue_run_token(
                    request.app.state.settings, run_id, run.lease_id, role=role
                )
        registry = ToolRegistry(request.app.state.settings, profile, actor_id, run_id, api_token)
        add_api_tools(registry, self.openapi, local=local)
        add_catalog_tools(registry, self.openapi, local=local)
        return registry, local, request.headers.get("x-tool-call-id", "")[:201]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # A mounted app replaces scope['app']; retain the API state in a private copy.
        request = Request(dict(scope), receive)
        context = _current_request.set(request)
        try:
            token = request.headers.get("authorization", "").removeprefix("Bearer ")
            if token.startswith("cc_local."):

                def check_local() -> None:
                    with Session(request.app.state.engine) as db:
                        MCPClientCredential.authenticate(db, token)

                try:
                    await run_in_threadpool(check_local)
                except ValueError as exc:
                    raise HTTPException(401, "Invalid or revoked local MCP credential") from exc
            else:
                await run_in_threadpool(
                    authenticate_run,
                    request,
                    token,
                    audience="command-center-mcp",
                    check_scope=False,
                )
            if request.method == "POST":
                payload = bytearray()
                async for chunk in request.stream():
                    if len(payload) + len(chunk) > 1_000_000:
                        await JSONResponse(
                            {"detail": "MCP request exceeds the size limit"}, status_code=413
                        )(scope, receive, send)
                        return
                    payload.extend(chunk)
                delivered = False

                async def replay() -> Message:
                    nonlocal delivered
                    if not delivered:
                        delivered = True
                        return {"type": "http.request", "body": bytes(payload), "more_body": False}
                    return await receive()

                await self.http_app(scope, replay, send)
            else:
                await self.http_app(scope, receive, send)
        except HTTPException as exc:
            await JSONResponse({"detail": exc.detail}, status_code=exc.status_code)(
                scope, receive, send
            )
        finally:
            _current_request.reset(context)
