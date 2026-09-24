"""Optional Strands model bridge; all provider calls keep host accounting and compaction."""

import asyncio
import json
from collections.abc import AsyncGenerator
from contextlib import aclosing
from typing import Any, cast
from uuid import NAMESPACE_URL, uuid5

from langchain.agents.middleware.types import ExtendedModelResponse, ModelRequest, ModelResponse
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    SystemMessage,
    ToolMessage,
    message_chunk_to_message,
)
from strands.models import Model
from strands.types.content import Messages
from strands.types.streaming import StreamEvent
from strands.types.tools import ToolSpec

from command_center.agents.chat_context import ChatSummarizationMiddleware, SummarySink
from command_center.agents.config import AgentProfile
from command_center.agents.runtime_control import (
    ExecutionStopped,
    InstructionSource,
    ModelAccounting,
    RunControl,
    WorkMiddleware,
)
from command_center.agents.spending import ModelSpendingGate


class HostModel(Model):
    def __init__(
        self,
        model: BaseChatModel,
        profile: AgentProfile,
        control: RunControl,
        role: str,
        spending: ModelSpendingGate | None,
        instructions: InstructionSource | None,
        summary_sink: SummarySink | None,
    ) -> None:
        callbacks = [
            *(model.callbacks if isinstance(model.callbacks, list) else []),
            ModelAccounting(control, role, profile, spending),
        ]
        self.model = model.model_copy(update={"callbacks": callbacks})
        # The shared summarizer must not install implicit paid retries.
        object.__setattr__(self.model, "with_retry", lambda *args, **kwargs: self.model)
        self.summary = ChatSummarizationMiddleware(
            self.model, profile.max_context_chars, summary_sink
        )
        self.work = WorkMiddleware(control, role, instructions=instructions)
        self.control, self.profile = control, profile
        self.instructions = instructions
        self.state: dict[str, Any] = {"instruction_sequence": control.sequence}
        self.originals: dict[str, list[BaseMessage]] = {}
        self.message_count = 0
        self.updates: list[tuple[int, list[BaseMessage]]] = []
        self.tool_ids: set[str] = set()
        self.fatal: Exception | None = None

    def check(self) -> None:
        if self.fatal is not None:
            raise self.fatal

    def update_config(self, **model_config: Any) -> None:
        if model_config:
            raise ValueError("The host profile owns model configuration")

    def get_config(self) -> dict[str, Any]:
        return {"model_id": self.profile.model}

    async def structured_output(
        self, output_model: Any, prompt: Messages, system_prompt: str | None = None, **kwargs: Any
    ) -> AsyncGenerator[dict[str, Any], None]:
        raise ExecutionStopped("strands_structured_output_unsupported")
        yield {}  # pragma: no cover

    @staticmethod
    def key(message: dict[str, Any]) -> str:
        # Ignore SDK tracking metadata; retain provider reasoning/signatures privately.
        content = [
            block
            for block in message["content"]
            if not ("text" in block and not str(block["text"]).strip())
        ]
        if message["role"] == "assistant" and content == [{"text": "[blank text]"}]:
            # The pinned SDK replaces an entirely blank assistant message with this
            # sentinel. Ordered occurrences distinguish it from literal source text.
            content = []
        return json.dumps({"role": message["role"], "content": content}, sort_keys=True)

    def encode(self, message: BaseMessage) -> dict[str, Any]:
        self.message_count += 1
        if message.id is None:
            message = message.model_copy(
                update={
                    "id": str(
                        uuid5(NAMESPACE_URL, f"{self.message_count}:{message.model_dump_json()}")
                    )
                }
            )
        if isinstance(message, ToolMessage):
            content: list[dict[str, Any]] = [
                {
                    "toolResult": {
                        "toolUseId": message.tool_call_id,
                        "status": message.status,
                        "content": [{"text": str(message.content)}],
                    }
                }
            ]
            role = "user"
        else:
            content = [{"text": str(message.text)}] if message.text else []
            role = "assistant" if isinstance(message, AIMessage) else "user"
            if isinstance(message, AIMessage):
                content.extend(
                    {
                        "toolUse": {
                            "toolUseId": call["id"],
                            "name": call["name"],
                            "input": call["args"],
                        }
                    }
                    for call in message.tool_calls
                )
            if not content:
                content = [{"text": ""}]
        encoded = {"role": role, "content": content}
        self.originals.setdefault(self.key(encoded), []).append(message)
        return encoded

    def decode(self, messages: Messages) -> list[BaseMessage]:
        result: list[BaseMessage] = []
        occurrences: dict[str, int] = {}
        for index, message in enumerate(messages):
            for position, updates in self.updates:
                if position == index:
                    result.extend(updates)
            key = self.key(cast(dict[str, Any], message))
            occurrence = occurrences.get(key, 0)
            occurrences[key] = occurrence + 1
            originals = self.originals.get(key, [])
            if occurrence < len(originals):
                result.append(originals[occurrence])
                continue
            # Only new SDK tool results should miss the original-message map.
            for block in message["content"]:
                if "toolResult" not in block:
                    raise ExecutionStopped("strands_message_conversion")
                tool = block["toolResult"]
                result.append(
                    ToolMessage(
                        content="\n".join(str(part.get("text", "")) for part in tool["content"]),
                        tool_call_id=tool["toolUseId"],
                        status=tool["status"],
                        id=str(uuid5(NAMESPACE_URL, f"strands-tool:{tool['toolUseId']}")),
                    )
                )
        for position, updates in self.updates:
            if position == len(messages):
                result.extend(updates)
        return result

    async def stream(
        self,
        messages: Messages,
        tool_specs: list[ToolSpec] | None = None,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[StreamEvent, None]:
        try:
            async with aclosing(
                self._stream(messages, tool_specs, system_prompt, **kwargs)
            ) as events:
                async for event in events:
                    yield event
        except Exception as exc:
            # The SDK may wrap errors. Preserve steering/lease and conversion failures
            # from before the provider producer starts, as well as provider failures.
            self.fatal = exc
            raise

    async def _stream(
        self,
        messages: Messages,
        tool_specs: list[ToolSpec] | None = None,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[StreamEvent, None]:
        self.check()
        if self.instructions is not None:
            sequence, updates = await self.instructions(self.control.sequence)
            if sequence > self.control.sequence:
                # Persist the new cursor only once these instructions enter a model request.
                self.updates.append(
                    (
                        len(messages),
                        [
                            message
                            if message.id
                            else message.model_copy(
                                update={
                                    "id": str(uuid5(NAMESPACE_URL, f"steering:{sequence}:{index}"))
                                }
                            )
                            for index, message in enumerate(updates)
                        ],
                    )
                )
                self.control.sequence = sequence
                self.state["instruction_sequence"] = sequence
        decoded = self.decode(messages)
        self.state["messages"] = decoded
        schemas = [
            {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["inputSchema"]["json"],
            }
            for tool in tool_specs or []
        ]
        request = ModelRequest(
            model=self.model,
            messages=cast(Any, decoded),
            system_message=SystemMessage(content=system_prompt or self.profile.instructions),
            tools=cast(Any, schemas),
            state=cast(Any, self.state),
        )
        queue: asyncio.Queue[StreamEvent | BaseException | None] = asyncio.Queue(maxsize=32)

        async def generate(effective: ModelRequest[Any]) -> ModelResponse:
            self.check()
            bound = self.model.bind_tools(effective.tools) if effective.tools else self.model
            inputs = [
                *([effective.system_message] if effective.system_message else []),
                *effective.messages,
            ]
            full: AIMessageChunk | None = None
            await queue.put({"messageStart": {"role": "assistant"}})
            async with aclosing(cast(AsyncGenerator[Any, None], bound.astream(inputs))) as chunks:
                async for chunk in chunks:
                    if not isinstance(chunk, AIMessageChunk):
                        raise ExecutionStopped("strands_model_chunk")
                    full = chunk if full is None else full + chunk
                    if chunk.text:
                        await queue.put(
                            {
                                "contentBlockDelta": {
                                    "contentBlockIndex": 0,
                                    "delta": {"text": str(chunk.text)},
                                }
                            }
                        )
            if full is None:
                raise ExecutionStopped("strands_empty_response")
            final = cast(AIMessage, message_chunk_to_message(full))
            finish_reason = str(
                final.response_metadata.get(
                    "finish_reason", final.response_metadata.get("stop_reason", "")
                )
            ).lower()
            if finish_reason in {"length", "max_tokens"} or (
                final.response_metadata.get("status") == "incomplete"
            ):
                raise ExecutionStopped("output_limit")
            if final.invalid_tool_calls:
                raise ExecutionStopped("strands_invalid_tool_call")
            allowed = {tool["name"] for tool in tool_specs or []}
            if any(call["name"] not in allowed or not call["id"] for call in final.tool_calls):
                raise ExecutionStopped("strands_ungranted_tool")
            identifiers = [str(call["id"]) for call in final.tool_calls]
            if len(set(identifiers)) != len(identifiers) or self.tool_ids.intersection(identifiers):
                raise ExecutionStopped("tool_identity_conflict")
            self.tool_ids.update(identifiers)
            self.encode(final)
            await queue.put({"contentBlockStop": {"contentBlockIndex": 0}})
            for index, call in enumerate(final.tool_calls, 1):
                await queue.put(
                    {
                        "contentBlockStart": {
                            "contentBlockIndex": index,
                            "start": {
                                "toolUse": {"toolUseId": str(call["id"]), "name": call["name"]}
                            },
                        }
                    }
                )
                await queue.put(
                    {
                        "contentBlockDelta": {
                            "contentBlockIndex": index,
                            "delta": {"toolUse": {"input": json.dumps(call["args"])}},
                        }
                    }
                )
                await queue.put({"contentBlockStop": {"contentBlockIndex": index}})
            await queue.put(
                {"messageStop": {"stopReason": "tool_use" if final.tool_calls else "end_turn"}}
            )
            usage: dict[str, Any] = dict(final.usage_metadata or {})
            await queue.put(
                {
                    "metadata": {
                        "usage": {
                            "inputTokens": int(usage.get("input_tokens", 0)),
                            "outputTokens": int(usage.get("output_tokens", 0)),
                            "totalTokens": int(usage.get("total_tokens", 0)),
                        },
                        "metrics": {"latencyMs": 0},
                    }
                }
            )
            return ModelResponse(result=[final])

        async def with_budget(effective: ModelRequest[Any]) -> ModelResponse:
            return await self.work.awrap_model_call(effective, generate)

        async def produce() -> None:
            try:
                response = await self.summary.awrap_model_call(request, with_budget)
                if isinstance(response, ExtendedModelResponse) and response.command is not None:
                    self.state.update(response.command.update or {})
            except Exception as exc:
                self.fatal = exc
                await queue.put(exc)
            finally:
                # Cancellation must not hang on a full queue whose consumer has gone away.
                task = asyncio.current_task()
                if task is not None and not task.cancelling():
                    await queue.put(None)

        producing = asyncio.create_task(produce())
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                if isinstance(event, BaseException):
                    raise event
                yield event
        finally:
            producing.cancel()
            await asyncio.gather(producing, return_exceptions=True)
