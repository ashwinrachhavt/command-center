"""Thin HTTP boundary for durable agent questions and exact answers."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field
from sqlalchemy import select

from command_center.api import schemas as s
from command_center.api.workspace import Database, WriteKey, owned, write
from command_center.core.identity import CurrentIdentity
from command_center.db.agent_questions import AgentQuestion
from command_center.db.agents import AgentRun

router = APIRouter(prefix="/api/v1", tags=["agent-questions"])


class QuestionAnswer(s.Revision):
    answer: str = Field(min_length=1, max_length=20000)


class QuestionRead(s.ResponseContract):
    id: UUID
    row_version: int
    run_id: UUID
    session_id: UUID
    interrupt_id: str
    branch_id: str
    role: str
    tool_call_id: str
    prompt: str
    state: Literal["open", "answered", "resumed", "cancelled"]
    answer: str | None
    created_at: datetime
    answered_at: datetime | None


def read(question: AgentQuestion) -> QuestionRead:
    return QuestionRead(
        id=question.id,
        row_version=question.row_version,
        run_id=question.run_id,
        session_id=question.session_id,
        interrupt_id=question.interrupt_id,
        branch_id=question.branch_id,
        role=question.role,
        tool_call_id=question.tool_call_id,
        prompt=question.prompt,
        state=question.state,
        answer=question.answer,
        created_at=question.created_at,
        answered_at=question.answered_at,
    )


@router.get("/agent-runs/{run_id}/questions", response_model=list[QuestionRead])
def questions(run_id: UUID, identity: CurrentIdentity, db: Database) -> list[QuestionRead]:
    owned(db, AgentRun, run_id, identity.id)
    rows = db.scalars(
        select(AgentQuestion)
        .where(AgentQuestion.owner_id == identity.id, AgentQuestion.run_id == run_id)
        .order_by(AgentQuestion.created_at, AgentQuestion.id)
    ).all()
    return [read(question) for question in rows]


@router.post(
    "/agent-runs/{run_id}/questions/{question_id}/answer",
    response_model=QuestionRead,
)
def answer_question(
    run_id: UUID,
    question_id: UUID,
    body: QuestionAnswer,
    identity: CurrentIdentity,
    db: Database,
    key: WriteKey,
    request: Request,
) -> dict[str, Any]:
    if identity.run_id is not None:
        raise HTTPException(403, "Only the human owner can answer agent questions")

    def change(_: UUID) -> dict[str, Any]:
        question = db.scalar(
            select(AgentQuestion)
            .where(
                AgentQuestion.id == question_id,
                AgentQuestion.run_id == run_id,
                AgentQuestion.owner_id == identity.id,
            )
            .with_for_update()
        )
        if question is None:
            raise HTTPException(404, "Question not found")
        question.answer_once(
            db,
            answer=body.answer,
            expected_version=body.expected_version,
            request_id=UUID(request.state.request_id),
        )
        db.flush()
        return read(question).model_dump(mode="json")

    return write(
        db,
        identity.id,
        key,
        f"ANSWER:agent-runs:{run_id}:questions:{question_id}",
        body,
        change,
    )
