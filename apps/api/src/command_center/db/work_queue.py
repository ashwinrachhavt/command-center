"""Bounded, read-only dashboard projections over canonical owned work records."""

from datetime import datetime, time, timedelta
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import DateTime, and_, case, cast, func, or_, select, text
from sqlalchemy.orm import Session

from command_center.db.base import utc_now
from command_center.db.models import Task
from command_center.db.reviewed_actions import ACTION_LABEL_FOR_KIND

WorkLane = Literal["attention", "running", "outputs"]
TaskView = Literal["today", "upcoming", "unscheduled", "snoozed"]

_ITEM_COLUMNS = """id, kind, title, state, updated_at, task_id, opportunity_id,
run_id, artifact_id, version_id, detail, action_kind
"""
_ACTION_LABEL = (
    "CASE a.kind "
    + " ".join(
        f"WHEN :action_kind_{index} THEN :action_label_{index}"
        for index, _ in enumerate(ACTION_LABEL_FOR_KIND)
    )
    + " END"
)

# Every optional context join is owner-scoped. A corrupt legacy cross-owner link is
# omitted from the projection rather than exposing another actor's record identity.
# A newer run supersedes an old failure even if the newer run is later archived.
_SOURCES = """
WITH runs AS (
    SELECT r.id, r.session_id, r.title, r.state, r.updated_at,
           t.id AS task_id, o.id AS opportunity_id,
           coalesce(length(trim(r.output)), 0) > 0 AS has_output,
           NOT EXISTS (
               SELECT 1 FROM agent_runs newer
               WHERE newer.owner_id = :owner_id AND newer.session_id = r.session_id
                 AND (newer.created_at, newer.id) > (r.created_at, r.id)
           ) AS is_latest
    FROM agent_runs r
    LEFT JOIN agent_sessions s ON s.id = r.session_id AND s.owner_id = :owner_id
        AND s.archived_at IS NULL
    LEFT JOIN tasks t ON t.id = s.task_id AND t.owner_id = :owner_id
    LEFT JOIN opportunities o ON o.id = coalesce(s.opportunity_id, t.opportunity_id)
        AND o.owner_id = :owner_id
    WHERE r.owner_id = :owner_id AND r.archived_at IS NULL
      AND (r.session_id IS NULL OR s.id IS NOT NULL)
), question_rows AS (
    SELECT q.id, 'question'::text AS kind, r.title, q.state, q.updated_at,
           r.task_id, r.opportunity_id, r.id AS run_id,
           NULL::uuid AS artifact_id, NULL::uuid AS version_id,
           'An answer is needed to continue this conversation.'::text AS detail,
           NULL::text AS action_kind
    FROM agent_questions q JOIN runs r ON r.id = q.run_id AND r.session_id = q.session_id
    WHERE q.owner_id = :owner_id AND q.archived_at IS NULL AND q.state = 'open'
      AND r.state = 'waiting_for_user' AND r.is_latest
), run_rows AS (
    SELECT id, 'run'::text AS kind, title, state, updated_at, task_id, opportunity_id,
           id AS run_id, NULL::uuid AS artifact_id, NULL::uuid AS version_id,
           CASE state
               WHEN 'queued' THEN 'Waiting for a worker.'
               WHEN 'running' THEN 'Agent work is in progress.'
               WHEN 'waiting_for_user' THEN 'The conversation is waiting for your input.'
               WHEN 'failed' THEN 'Agent work stopped. Open the run for details.'
               WHEN 'completed' THEN 'A response is saved in this run.'
           END AS detail,
           NULL::text AS action_kind, is_latest, has_output
    FROM runs
), action_rows AS (
    SELECT a.id, 'action'::text AS kind, coalesce(t.title, ACTION_LABEL) AS title,
           a.state, a.updated_at, t.id AS task_id, o.id AS opportunity_id,
           NULL::uuid AS run_id, NULL::uuid AS artifact_id, NULL::uuid AS version_id,
           ACTION_LABEL AS detail, a.kind AS action_kind
    FROM reviewed_actions a
    JOIN external_accounts account ON account.id = a.account_id AND account.owner_id = :owner_id
    LEFT JOIN tasks t ON t.id = a.task_id AND t.owner_id = :owner_id
    LEFT JOIN opportunities o ON o.id = coalesce(a.opportunity_id, t.opportunity_id)
        AND o.owner_id = :owner_id
    WHERE a.owner_id = :owner_id AND a.archived_at IS NULL
), browser_rows AS (
    SELECT c.id, 'browser'::text AS kind,
           coalesce(nullif(s.title, ''), 'Application form') AS title,
           c.state, coalesce(c.completed_at, c.created_at) AS updated_at,
           t.id AS task_id, o.id AS opportunity_id, NULL::uuid AS run_id,
           p.artifact_id, CASE WHEN p.id IS NOT NULL THEN v.id END AS version_id,
           CASE
               WHEN c.state = 'claimed' AND c.expires_at <= :now
                   THEN 'Confirmation expired; the outcome is unknown. Inspect the page manually.'
               WHEN c.state = 'pending' AND d.revoked_at IS NOT NULL
                   THEN 'This device was revoked. The command cannot be claimed; review manually.'
               WHEN c.state = 'pending' AND s.protocol_version <> 2
                   THEN 'Reshare this form with the current companion before filling.'
               WHEN c.state = 'pending' THEN 'Review the pending fill in the browser companion.'
               WHEN c.state = 'claimed' THEN 'The companion has claimed this fill.'
               WHEN c.state = 'partial' THEN 'Only part of the fill was confirmed. Review the page.'
               WHEN c.state = 'failed' THEN 'The fill failed. Review its result before retrying.'
               ELSE 'The fill outcome is unknown. Inspect the page before another attempt.'
           END AS detail,
           NULL::text AS action_kind, c.expires_at
    FROM browser_commands c
    JOIN browser_snapshots s ON s.id = c.snapshot_id AND s.device_id = c.device_id
        AND s.owner_id = :owner_id
    JOIN browser_devices d ON d.id = c.device_id AND d.owner_id = :owner_id
    LEFT JOIN artifact_versions v ON v.id = c.preparation_version_id
    LEFT JOIN artifacts a ON a.id = v.artifact_id AND a.owner_id = :owner_id
    LEFT JOIN application_preparations p ON p.artifact_id = a.id
        AND p.snapshot_id = c.snapshot_id AND p.owner_id = :owner_id
    LEFT JOIN tasks t ON t.id = p.task_id AND t.owner_id = :owner_id
    LEFT JOIN opportunities o ON o.id = coalesce(p.opportunity_id, t.opportunity_id)
        AND o.owner_id = :owner_id
    WHERE c.owner_id = :owner_id
), artifact_rows AS (
    SELECT a.id, 'artifact'::text AS kind, a.title,
           coalesce(review.decision, 'unreviewed') AS state,
           v.created_at AS updated_at, context.task_id, context.opportunity_id,
           NULL::uuid AS run_id, a.id AS artifact_id, v.id AS version_id,
           'Saved version ' || v.version::text AS detail, NULL::text AS action_kind
    FROM artifacts a
    JOIN LATERAL (
        SELECT av.id, av.version, av.created_at FROM artifact_versions av
        WHERE av.artifact_id = a.id ORDER BY av.version DESC, av.id DESC LIMIT 1
    ) v ON true
    LEFT JOIN LATERAL (
        SELECT ar.decision FROM artifact_reviews ar
        WHERE ar.artifact_version_id = v.id AND ar.reviewer_id = :owner_id
        ORDER BY ar.created_at DESC, ar.id DESC LIMIT 1
    ) review ON true
    LEFT JOIN LATERAL (
        SELECT t.id AS task_id, o.id AS opportunity_id
        FROM task_artifacts link JOIN tasks t ON t.id = link.task_id AND t.owner_id = :owner_id
        LEFT JOIN opportunities o ON o.id = t.opportunity_id AND o.owner_id = :owner_id
        WHERE link.artifact_id = a.id ORDER BY t.updated_at DESC, t.id ASC LIMIT 1
    ) context ON true
    WHERE a.owner_id = :owner_id AND a.archived_at IS NULL
      AND a.kind IN ('document', 'message', 'research')
)
""".replace("ACTION_LABEL", _ACTION_LABEL)

_LANES = {
    "attention": (
        "question_rows",
        "run_rows WHERE is_latest AND state IN ('failed', 'waiting_for_user') "
        "AND NOT EXISTS (SELECT 1 FROM question_rows q WHERE q.run_id = run_rows.id)",
        "action_rows WHERE state IN "
        "('proposed', 'failed', 'conflicted', 'partial', 'outcome_unknown')",
        "browser_rows WHERE (state = 'pending' AND expires_at > :now) "
        "OR (state = 'claimed' AND expires_at <= :now) "
        "OR state IN ('failed', 'partial', 'outcome_unknown')",
    ),
    "running": (
        "run_rows WHERE state IN ('queued', 'running')",
        "action_rows WHERE state IN ('queued', 'running')",
        "browser_rows WHERE state = 'claimed' AND expires_at > :now",
    ),
    "outputs": (
        "artifact_rows",
        "action_rows WHERE state = 'succeeded'",
        "run_rows WHERE state = 'completed' AND has_output",
    ),
}


def work_queue_page(
    session: Session, owner_id: UUID, *, lane: WorkLane, limit: int, offset: int
) -> dict[str, Any]:
    """Count and page the same SQL union; never run expiration or recovery transitions."""
    union = " UNION ALL ".join(f"SELECT {_ITEM_COLUMNS} FROM {source}" for source in _LANES[lane])
    query = _SOURCES + f", queue AS ({union}) "
    parameters: dict[str, Any] = {
        "owner_id": owner_id,
        "now": utc_now(),
        "limit": limit,
        "offset": offset,
    }
    for index, (kind, label) in enumerate(ACTION_LABEL_FOR_KIND.items()):
        parameters[f"action_kind_{index}"] = kind
        parameters[f"action_label_{index}"] = label
    total = session.scalar(text(query + "SELECT count(*) FROM queue"), parameters)
    rows = session.execute(
        text(
            query + "SELECT * FROM queue ORDER BY updated_at DESC, kind ASC, id ASC "
            "LIMIT :limit OFFSET :offset"
        ),
        parameters,
    ).mappings()
    return {"items": [dict(row) for row in rows], "total": total, "limit": limit, "offset": offset}


def daily_tasks_page(
    session: Session, owner_id: UUID, *, view: TaskView, timezone: ZoneInfo, limit: int, offset: int
) -> dict[str, Any]:
    now = utc_now()
    today = now.astimezone(timezone).date()
    tomorrow = datetime.combine(today + timedelta(days=1), time.min, tzinfo=timezone)
    active = Task.state.in_(("open", "in_progress"))
    due_today = or_(Task.due_date <= today, Task.due_at < tomorrow)
    predicates = {
        "today": and_(active, due_today),
        "upcoming": and_(active, or_(Task.due_date > today, Task.due_at >= tomorrow)),
        "unscheduled": and_(active, Task.due_date.is_(None), Task.due_at.is_(None)),
        "snoozed": Task.state == "snoozed",
    }
    counts = dict(
        session.execute(
            select(
                *(
                    func.count().filter(predicate).label(name)
                    for name, predicate in predicates.items()
                )
            )
            .select_from(Task)
            .where(Task.owner_id == owner_id)
        )
        .one()
        ._mapping
    )
    due_status = case(
        (or_(Task.due_date < today, Task.due_at < now), "overdue"),
        (due_today, "today"),
        (or_(Task.due_date.is_not(None), Task.due_at.is_not(None)), "upcoming"),
        else_="unscheduled",
    )
    deadline = func.coalesce(
        Task.due_at, func.timezone(timezone.key, cast(Task.due_date, DateTime()))
    )
    rows = session.execute(
        select(*Task.__table__.columns, due_status.label("due_status"))
        .where(Task.owner_id == owner_id, predicates[view])
        .order_by(deadline.asc().nulls_last(), Task.priority.desc(), Task.id.asc())
        .limit(limit)
        .offset(offset)
    ).mappings()
    return {
        "items": [dict(row) for row in rows],
        "total": counts[view],
        "limit": limit,
        "offset": offset,
        "timezone": timezone.key,
        "today": today,
        "counts": counts,
    }
