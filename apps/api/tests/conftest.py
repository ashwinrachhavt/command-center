import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session

from command_center.core.config import Settings
from command_center.db import (  # noqa: F401
    agent_events,
    agent_questions,
    application_preparations,
    artifacts,
    document_imports,
    evidence,
    models,
    pdf_exports,
    profile_facts,
    research_executions,
    reviewed_actions,
    spending,
    writing,
)
from command_center.db.session import create_database_engine

TEST_DATABASE_URL = os.environ.get(
    "CC_TEST_DATABASE_URL",
    "postgresql+psycopg://test:test-only@127.0.0.1:55433/command_center_test",
)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        api_token="synthetic-test-token-with-at-least-32-characters",
        database_url=TEST_DATABASE_URL,
        allowed_hosts=["testserver"],
        langfuse_enabled=False,
        jev_enabled=False,
        jev_provider="typesafe",
        TYPESAFE_API_KEY="",
        AI_GATEWAY_API_KEY="",
        VENICE_API_KEY="",
    )


@pytest.fixture(scope="session")
def migration_config() -> Iterator[Config]:
    if make_url(TEST_DATABASE_URL).database != "command_center_test":
        raise RuntimeError("Tests require the dedicated command_center_test database")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("CC_DATABASE_URL", TEST_DATABASE_URL)
        patch.setenv("CC_API_TOKEN", "synthetic-test-token-with-at-least-32-characters")
        yield Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))


@pytest.fixture(scope="session")
def engine(migration_config: Config) -> Iterator[Engine]:
    command.upgrade(migration_config, "head")
    database = create_database_engine(TEST_DATABASE_URL)
    yield database
    database.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode="create_savepoint") as database:
            yield database
        transaction.rollback()


@pytest.fixture
def agent_server(settings, engine):
    """Real local MCP/API server; only synthetic data and provider credentials."""
    import socket
    import threading
    import time

    import uvicorn
    from pydantic import SecretStr

    from command_center.main import create_app

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    config = settings.model_copy(
        update={
            "internal_api_url": f"http://127.0.0.1:{listener.getsockname()[1]}",
            "allowed_hosts": ["127.0.0.1"],
            "openai_api_key": SecretStr("synthetic-model-key"),
        }
    )
    server = uvicorn.Server(uvicorn.Config(create_app(config), log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        yield config
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
        assert not thread.is_alive()


@pytest.fixture
def scripted_model(mocker):
    """Use the real chat/tool adapter with only the paid generation boundary mocked."""
    import inspect

    from langchain_core.messages import AIMessageChunk
    from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
    from langchain_openai import ChatOpenAI

    def create(replies):
        model = ChatOpenAI(model="gpt-5-mini", api_key="synthetic-model-key", max_retries=0)
        iterator = iter(replies)

        async def next_reply(messages):
            reply = next(iterator)
            if callable(reply):
                reply = reply(messages)
            if inspect.isawaitable(reply):
                reply = await reply
            return reply

        async def generate(messages, **kwargs):
            reply = await next_reply(messages)
            return ChatResult(generations=[ChatGeneration(message=reply)])

        async def stream(messages, **kwargs):
            reply = await next_reply(messages)
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content=reply.content,
                    additional_kwargs=reply.additional_kwargs,
                    response_metadata=reply.response_metadata,
                    name=reply.name,
                    id=reply.id,
                    tool_calls=reply.tool_calls,
                    invalid_tool_calls=reply.invalid_tool_calls,
                    usage_metadata=reply.usage_metadata,
                    chunk_position="last",
                )
            )

        mocker.patch.object(model, "_agenerate", side_effect=generate)
        mocker.patch.object(model, "_astream", side_effect=stream)
        return model

    return create
