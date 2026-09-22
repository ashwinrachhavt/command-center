"""Async model-call spending gate injected at the provider callback boundary."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from langchain_core.messages import BaseMessage
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from command_center.db.spending import SpendingReservation

ReserveModel = Callable[[UUID, str, str, str, int, int], Awaitable[UUID]]
SettleModel = Callable[[UUID, int, int], Awaitable[None]]
UnknownModel = Callable[[UUID, str], Awaitable[None]]


def conservative_input_bound(
    messages: list[list[BaseMessage]], invocation_params: dict[str, Any]
) -> int:
    """Bound selected byte-token model inputs; deny models without a configured rate separately.

    The selected providers tokenize UTF-8-derived input. Counting encoded bytes plus a fixed
    4 KiB allowance for message/tool framing is conservative for this integration, but it is
    still a local bound rather than a provider invoice guarantee.
    """
    content = [
        {"type": message.type, "name": message.name, "content": message.content}
        for batch in messages
        for message in batch
    ]
    tools = invocation_params.get("tools", [])
    encoded = json.dumps({"messages": content, "tools": tools}, default=str).encode("utf-8")
    return len(encoded) + 4096


class ModelSpendingGate:
    def __init__(
        self,
        reserve: ReserveModel,
        settle: SettleModel,
        unknown: UnknownModel,
    ):
        self.reserve_call = reserve
        self.settle_call = settle
        self.unknown_call = unknown
        self.reservations: dict[UUID, UUID] = {}
        self.lock = asyncio.Lock()

    async def reserve(
        self,
        callback_id: UUID,
        *,
        role: str,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        reservation_id = await self.reserve_call(
            callback_id,
            role,
            provider,
            model,
            input_tokens,
            output_tokens,
        )
        async with self.lock:
            existing = self.reservations.get(callback_id)
            if existing is not None and existing != reservation_id:
                raise ValueError("Model callback reservation changed")
            self.reservations[callback_id] = reservation_id

    async def settle(self, callback_id: UUID, input_tokens: int, output_tokens: int) -> None:
        async with self.lock:
            reservation_id = self.reservations.get(callback_id)
        if reservation_id is None:
            raise ValueError("Model callback has no spending reservation")
        if input_tokens < 0 or output_tokens < 0 or input_tokens + output_tokens == 0:
            await self.unknown_call(reservation_id, "spending_usage_unknown")
        else:
            await self.settle_call(reservation_id, input_tokens, output_tokens)

    async def unknown(self, callback_id: UUID, reason: str) -> None:
        async with self.lock:
            reservation_id = self.reservations.get(callback_id)
        if reservation_id is not None:
            await self.unknown_call(reservation_id, reason)


def model_spending_gate(engine: Engine, run_id: UUID, lease_id: UUID) -> ModelSpendingGate:
    def reserve(
        callback_id: UUID,
        role: str,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> UUID:
        with Session(engine, expire_on_commit=False) as db, db.begin():
            row = SpendingReservation.reserve_model(
                db,
                run_id=run_id,
                lease_id=lease_id,
                callback_id=callback_id,
                role=role,
                provider=provider,
                model=model,
                input_token_bound=input_tokens,
                output_token_bound=output_tokens,
            )
            db.flush([row])
            return row.id

    def settle(reservation_id: UUID, input_tokens: int, output_tokens: int) -> None:
        with Session(engine) as db, db.begin():
            SpendingReservation.settle_model(
                db,
                reservation_id=reservation_id,
                lease_id=lease_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )

    def unknown(reservation_id: UUID, reason: str) -> None:
        with Session(engine) as db, db.begin():
            SpendingReservation.mark_unknown(
                db,
                reservation_id=reservation_id,
                lease_id=lease_id,
                reason=reason,
            )

    async def async_reserve(*args: Any) -> UUID:
        return await asyncio.to_thread(reserve, *args)

    async def async_settle(*args: Any) -> None:
        await asyncio.to_thread(settle, *args)

    async def async_unknown(*args: Any) -> None:
        await asyncio.to_thread(unknown, *args)

    return ModelSpendingGate(async_reserve, async_settle, async_unknown)


class FixedCostReservationHandle:
    """Idempotent settlement handle returned immediately before a provider call."""

    def __init__(self, engine: Engine, reservation_id: UUID, lease_id: UUID | None = None):
        self.engine = engine
        self.reservation_id = reservation_id
        self.lease_id = lease_id

    def settle(self, provider_billed_micros: int | None = None) -> None:
        with Session(self.engine) as db, db.begin():
            SpendingReservation.settle_connected_tool(
                db,
                reservation_id=self.reservation_id,
                provider_billed_micros=provider_billed_micros,
            )

    def unknown(self, reason: str) -> None:
        with Session(self.engine) as db, db.begin():
            SpendingReservation.mark_unknown(
                db,
                reservation_id=self.reservation_id,
                lease_id=self.lease_id,
                reason=reason,
            )


def connected_tool_reserver(
    engine: Engine,
    *,
    owner_id: UUID,
    task_id: UUID | None = None,
    opportunity_id: UUID | None = None,
    request_scope_id: UUID | None = None,
    run_id: UUID | None = None,
    lease_id: UUID | None = None,
) -> Callable[[str, UUID], FixedCostReservationHandle]:
    """Bind a trusted server-derived scope to the two-argument provider hook."""

    def reserve(tool_slug: str, operation_id: UUID) -> FixedCostReservationHandle:
        with Session(engine, expire_on_commit=False) as db, db.begin():
            row = SpendingReservation.reserve_connected_tool(
                db,
                owner_id=owner_id,
                operation_id=operation_id,
                slug=tool_slug,
                task_id=task_id,
                opportunity_id=opportunity_id,
                request_scope_id=request_scope_id,
                run_id=run_id,
                lease_id=lease_id,
            )
            db.flush([row])
            reservation_id = row.id
        return FixedCostReservationHandle(engine, reservation_id, lease_id)

    return reserve
