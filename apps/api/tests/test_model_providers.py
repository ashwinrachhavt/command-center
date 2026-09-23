"""Offline contracts for selectable native LangChain model providers."""

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from langchain_cohere import ChatCohere
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_mistralai import ChatMistralAI
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import SecretStr, ValidationError

from command_center.agents.config import AgentProfile, load_profiles
from command_center.agents.models import (
    BoundedChatCohere,
    create_chat_model,
    missing_profile_credentials,
)
from command_center.agents.runtime import run_graph
from command_center.api.agents import missing_profile_configuration
from command_center.api.agents import profiles as list_profiles
from command_center.core.identity import Identity


def profile(provider="openai", model="gpt-5-mini", **changes):
    return AgentProfile(
        name="Synthetic provider",
        description="Offline provider contract",
        provider=provider,
        model=model,
        instructions="Use only synthetic data.",
        tools=[],
        **changes,
    )


def test_cohere_native_errors_are_classified_without_exposing_provider_details():
    from cohere.core.api_error import ApiError

    from command_center.agents.models import model_failure_code

    assert (
        model_failure_code(ApiError(status_code=400, body="private upstream detail"))
        == "model_request_rejected"
    )
    assert (
        model_failure_code(ApiError(status_code=429, body="private upstream detail"))
        == "model_rate_limited"
    )


def configured_settings(settings):
    return settings.model_copy(
        update={
            "openai_api_key": SecretStr("synthetic-openai"),
            "gemini_api_key": SecretStr("synthetic-gemini"),
            "mistral_api_key": SecretStr("synthetic-mistral"),
            "cohere_api_key": SecretStr("synthetic-cohere"),
        }
    )


def test_quick_note_uses_low_reasoning_and_bounded_tools_without_reducing_company_research(
    settings,
):
    profiles, _ = load_profiles(Path("agents/profiles.toml"), Path("agents/skills"))
    quick, research = profiles["connection"], profiles["research"]
    assert quick.max_output_tokens == 800
    assert quick.max_tool_calls == 8
    assert quick.tool_call_limits["research_search"] == 1
    assert quick.tool_call_limits["capture_research_source"] == 1
    assert not quick.skill_files
    assert research.max_steps == 12
    assert research.max_output_tokens == 2500
    model = create_chat_model(configured_settings(settings), quick)
    assert model.reasoning_effort == "low"
    assert (
        create_chat_model(
            configured_settings(settings), quick.model_copy(update={"model": "gpt-4.1-mini"})
        ).reasoning_effort
        is None
    )


def test_quick_note_real_graph_fits_its_context_budget(settings, scripted_model, mocker):
    from command_center.agents.tools import ToolRegistry

    profiles, _ = load_profiles(Path("agents/profiles.toml"), Path("agents/skills"))
    quick = profiles["connection"]
    registry = ToolRegistry(settings, quick, uuid4(), uuid4(), "synthetic")
    task_id = str(uuid4())
    execute = mocker.AsyncMock(
        side_effect=[
            '{"record":{"name":"Synthetic Casey","notes":"Developer tools"},'
            '"research_requested":false,"connection_note":true}' + " " * 6000,
            '{"output_artifact_id":"synthetic-note"}',
        ],
    )

    class SyntheticTools:
        schemas = registry.schemas
        aexecute = execute

    model = scripted_model(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "record_work_context", "args": {"task_id": task_id}, "id": "context"}
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "save_record_work",
                        "args": {
                            "task_id": task_id,
                            "text": "Hi Casey, I’m exploring developer tools. Could we connect?",
                            "source_version_ids": [],
                        },
                        "id": "save",
                    }
                ],
            ),
            AIMessage(content="Your connection note is saved."),
        ]
    )
    snapshots = []

    async def persist(state):
        snapshots.append(state)

    output = asyncio.run(
        run_graph(
            quick,
            "Write a short note from saved context." + " " * 3000,
            SyntheticTools(),
            persist,
            model=model,
            checkpointer=InMemorySaver(),
            thread_id=str(uuid4()),
        )
    )
    assert output == "Your connection note is saved."
    assert [call.args[0] for call in execute.await_args_list] == [
        "record_work_context",
        "save_record_work",
    ]
    assert snapshots[-1]["steps"] == 3


def request_for(settings):
    app = FastAPI()
    app.state.settings = settings
    return type("Request", (), {"app": app})()


@pytest.mark.parametrize(
    ("provider", "model_name", "expected_type", "token_field", "timeout_field"),
    [
        ("openai", "gpt-5-mini", ChatOpenAI, "max_tokens", "request_timeout"),
        ("gemini", "gemini-2.5-flash", ChatGoogleGenerativeAI, "max_output_tokens", "timeout"),
        ("mistral", "mistral-small-latest", ChatMistralAI, "max_tokens", "timeout"),
        ("cohere", "command-a-03-2025", ChatCohere, "max_tokens", "timeout_seconds"),
    ],
)
def test_native_provider_models_are_bounded_and_bind_into_the_tool_graph(
    settings, mocker, provider, model_name, expected_type, token_field, timeout_field
):
    selected = profile(provider, model_name, max_output_tokens=777, max_steps=3)
    model = create_chat_model(configured_settings(settings), selected)

    assert isinstance(model, expected_type)
    assert getattr(model, token_field) == 777
    if provider == "cohere":
        assert isinstance(model, BoundedChatCohere)
        assert model._default_params["max_tokens"] == 777
    if provider == "gemini":
        assert model.vertexai is False
    assert model.max_retries == 0
    assert getattr(model, timeout_field) == 60

    calls = []

    async def generate(_model, messages, stop=None, run_manager=None, **kwargs):
        calls.append((messages, kwargs))
        if len(calls) == 1:
            message = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "synthetic_lookup",
                        "args": {"query": "bounded provider"},
                        "id": "synthetic-tool-call",
                    }
                ],
            )
        else:
            assert any(
                isinstance(message, ToolMessage) and message.content == "synthetic tool result"
                for message in messages
            )
            message = AIMessage(content="Synthetic provider finished.")
        return ChatResult(generations=[ChatGeneration(message=message)])

    mocker.patch.object(expected_type, "_agenerate", autospec=True, side_effect=generate)

    class ToolRegistry:
        schemas = [
            {
                "type": "function",
                "function": {
                    "name": "synthetic_lookup",
                    "description": "Return a synthetic lookup result.",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                        "additionalProperties": False,
                    },
                },
            }
        ]

        def __init__(self):
            self.executed = []

        async def aexecute(self, name, arguments, call_id):
            self.executed.append((name, arguments, call_id))
            return "synthetic tool result"

    registry = ToolRegistry()

    async def exercise():
        async def checkpoint(state):
            return None

        return await run_graph(
            selected,
            "Use the synthetic lookup tool.",
            registry,
            checkpoint,
            model=model,
            checkpointer=InMemorySaver(),
            thread_id=str(uuid4()),
            root_role="synthetic",
        )

    assert asyncio.run(exercise()) == "Synthetic provider finished."
    assert registry.executed == [
        ("synthetic_lookup", {"query": "bounded provider"}, "synthetic-tool-call")
    ]
    assert len(calls) == 2
    assert calls[0][1].get("tools")


def test_profile_provider_and_model_are_explicit_and_validated(tmp_path: Path):
    directives = tmp_path / "directives"
    directives.mkdir()
    (directives / "test.md").write_text("Synthetic directive")
    config = tmp_path / "profiles.toml"
    config.write_text(
        '[profiles.test]\nname="Test"\ndescription="Test"\nprovider="gemini"\n'
        'model="gemini-2.5-flash"\ndirective="test"\n'
    )
    profiles, _ = load_profiles(str(config))
    assert profiles["test"].provider == "gemini"

    with pytest.raises(ValidationError):
        profile("unsupported", "synthetic")
    with pytest.raises(ValidationError):
        profile("openai", "gemini:gemini-2.5-flash")


def test_credentials_are_checked_for_lead_and_each_specialist(settings):
    specialist = profile("mistral", "mistral-small-latest")
    lead = profile(specialists={"research": specialist})
    only_openai = settings.model_copy(
        update={
            "openai_api_key": SecretStr("synthetic-openai"),
            "mistral_api_key": SecretStr(""),
        }
    )

    assert missing_profile_credentials(only_openai, lead) == ("MISTRAL_API_KEY",)
    assert missing_profile_credentials(configured_settings(settings), lead) == ()


def test_profile_metadata_reports_provider_readiness_for_ui(settings):
    configured = configured_settings(settings)
    records = list_profiles(Identity(id=uuid4(), subject="synthetic"), request_for(configured))
    assert records
    assert all(record["ready"] is True for record in records)
    assert all(record["missing_credentials"] == [] for record in records)
    assert all(record["provider"] == "openai" for record in records)

    specialist = profile("mistral", "mistral-small-latest")
    lead = profile(
        specialists={"research": specialist},
    )
    only_openai = settings.model_copy(
        update={
            "openai_api_key": SecretStr("synthetic-openai"),
            "mistral_api_key": SecretStr(""),
            "composio_api_key": SecretStr(""),
        }
    )
    assert missing_profile_configuration(request_for(only_openai), lead) == [
        "MISTRAL_API_KEY",
    ]


def test_google_api_key_is_a_supported_gemini_alias(monkeypatch):
    from command_center.core.config import Settings

    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "CC_GEMINI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "synthetic-google-alias")
    configured = Settings(
        _env_file=None,
        api_token="synthetic-test-token-with-at-least-32-characters",
        database_url="postgresql+psycopg://test:test@localhost/test",
    )
    assert configured.gemini_api_key.get_secret_value() == "synthetic-google-alias"


def test_cohere_bounds_reach_the_actual_sdk_request(settings, mocker):
    import asyncio
    from unittest.mock import AsyncMock

    from langchain_core.messages import HumanMessage

    model = create_chat_model(
        configured_settings(settings), profile("cohere", "command-a-03-2025", max_output_tokens=777)
    )
    send = mocker.patch.object(
        model.async_client.v2,
        "chat",
        new_callable=AsyncMock,
        side_effect=RuntimeError("Synthetic SDK boundary; no network request"),
    )
    with pytest.raises(RuntimeError, match="Synthetic SDK boundary"):
        asyncio.run(model.ainvoke([HumanMessage(content="Synthetic request")]))
    assert send.await_args.kwargs["max_tokens"] == 777
    assert send.await_args.kwargs["request_options"] == {"max_retries": 0, "timeout_in_seconds": 60}


def test_gpt6_tool_calls_use_responses_with_bounded_output(settings, mocker):
    import httpx

    requests = []

    def respond(request):
        import json

        requests.append((request.url.path, json.loads(request.content)))
        return httpx.Response(
            200,
            json={
                "id": "resp_synthetic",
                "object": "response",
                "created_at": 1,
                "model": "gpt-6-astra",
                "status": "completed",
                "error": None,
                "incomplete_details": None,
                "output": [
                    {
                        "type": "function_call",
                        "id": "fc_synthetic",
                        "call_id": "call_synthetic",
                        "name": "synthetic_lookup",
                        "arguments": '{"query":"synthetic"}',
                        "status": "completed",
                    }
                ],
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            },
        )

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            mocker.patch(
                "command_center.agents.models.ChatOpenAI",
                side_effect=lambda **kwargs: ChatOpenAI(**kwargs, http_async_client=http),
            )
            model = create_chat_model(
                configured_settings(settings),
                profile("openai", "gpt-6-astra", max_output_tokens=256),
            )
            result = await model.bind_tools(
                [
                    {
                        "name": "synthetic_lookup",
                        "description": "Synthetic lookup",
                        "parameters": {
                            "type": "object",
                            "properties": {"query": {"type": "string"}},
                            "required": ["query"],
                        },
                    }
                ]
            ).ainvoke("Look up synthetic data.")
            assert result.tool_calls[0]["name"] == "synthetic_lookup"
            assert result.usage_metadata["total_tokens"] == 15

    asyncio.run(check())
    path, body = requests[0]
    assert path == "/v1/responses"
    assert body["max_output_tokens"] == 256
    assert body["store"] is False
    assert body["tools"][0]["name"] == "synthetic_lookup"


@pytest.mark.parametrize(
    "kind,code",
    [
        ("ModelNotFoundError", "model_not_found"),
        ("ModelAuthenticationError", "model_authentication_failed"),
        ("ModelPermissionDeniedError", "model_access_denied"),
        ("ModelRateLimitError", "model_rate_limited"),
        ("ModelInvalidRequestError", "model_request_rejected"),
        ("ModelTimeoutError", "model_timeout"),
        ("ModelConnectionError", "model_connection_failed"),
        ("ModelAPIError", "model_provider_unavailable"),
    ],
)
def test_provider_errors_have_safe_actionable_codes(kind, code):
    from langchain_core import exceptions

    from command_center.agents.models import model_failure_code

    assert model_failure_code(getattr(exceptions, kind)("synthetic secret")) == code
    assert model_failure_code(RuntimeError("synthetic secret")) == "agent_execution_failed"
