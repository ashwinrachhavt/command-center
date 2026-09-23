"""Owner-scoped daily projections read synthetic work without executing or mutating it."""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_workspace import client as client

from command_center.core.identity import Identity, authenticate
from command_center.db.agent_questions import AgentQuestion
from command_center.db.agents import AgentRun
from command_center.db.application_preparations import ApplicationPreparation
from command_center.db.artifacts import (
    Artifact,
    ArtifactReview,
    ArtifactVersion,
    Document,
    DocumentType,
    TaskArtifact,
)
from command_center.db.browser import BrowserCommand, BrowserDevice, BrowserSnapshot
from command_center.db.conversations import AgentSession
from command_center.db.models import Actor, AuditEvent, Task
from command_center.db.reviewed_actions import ExternalAccount, ReviewedAction

NOW = datetime(2026, 9, 22, 18, tzinfo=UTC)


def task(db, owner_id, **values):
    row = Task(owner_id=owner_id, title="Synthetic work", **values)
    db.add(row)
    db.flush()
    return row


def conversation(db, owner_id):
    work = task(db, owner_id)
    row = AgentSession(owner_id=owner_id, task_id=work.id, title="Synthetic conversation")
    db.add(row)
    db.flush()
    return row


def run(db, owner_id, state="failed", **values):
    row = AgentRun(
        owner_id=owner_id,
        title="Synthetic agent work",
        prompt="Private synthetic prompt must not be projected",
        profile="synthetic",
        state=state,
        config_snapshot={},
        updated_at=NOW,
        **values,
    )
    db.add(row)
    db.flush()
    return row


def action(db, owner_id, state="proposed", **values):
    account = ExternalAccount(
        owner_id=owner_id,
        toolkit="linear",
        composio_connected_account_id=f"synthetic-{uuid4()}",
        composio_auth_config_id="synthetic-config",
        display_name="Synthetic account",
        provider_identity={"secret": "never project account identity"},
        identity_verified_at=NOW,
    )
    db.add(account)
    db.flush()
    row = ReviewedAction(
        owner_id=owner_id,
        account_id=account.id,
        kind="linear_create",
        state=state,
        updated_at=NOW,
        **values,
    )
    db.add(row)
    db.flush()
    return row


def artifact(db, owner_id, kind="document", **values):
    row = Artifact(
        owner_id=owner_id, created_by_id=owner_id, kind=kind, title="Synthetic output", **values
    )
    db.add(row)
    db.flush()
    if kind == "document":
        document_type_id = db.scalar(select(DocumentType.id).where(DocumentType.slug == "notes"))
        db.add(Document(artifact_id=row.id, document_type_id=document_type_id))
    version = ArtifactVersion.from_payload(
        artifact_id=row.id,
        version=1,
        payload={"text": "Private synthetic document body"},
        schema_key="document.text.v1",
        created_by_id=owner_id,
    )
    version.created_at = NOW
    db.add(version)
    db.flush()
    return row, version


def work(client, lane="attention", **params):
    response = client.get("/api/v1/dashboard/work", params={"lane": lane, **params})
    assert response.status_code == 200, response.text
    return response.json()


def test_work_lanes_are_actor_owned_and_paginate_stable_ties(client, engine):
    with Session(engine) as db, db.begin():
        other = Actor(kind="human", display_name="Synthetic unrelated owner")
        db.add(other)
        db.flush()
        foreign_task = task(db, other.id)
        run(db, other.id)
        action(db, other.id)
        runs = [run(db, client.actor_id), run(db, client.actor_id)]
        proposed = action(db, client.actor_id, task_id=foreign_task.id)
        expected = [str(proposed.id), *sorted(str(row.id) for row in runs)]
    first = work(client, limit=1)
    assert first["total"] == 3 and first["limit"] == 1 and first["offset"] == 0
    assert first["items"][0]["task_id"] is None
    assert first["items"][0]["action_kind"] == "linear_create"
    assert [work(client, limit=1, offset=i)["items"][0]["id"] for i in range(3)] == expected
    assert work(client, offset=3)["items"] == []
    assert work(client, offset=3)["total"] == 3
    assert "Private synthetic" not in str(first) and "provider_identity" not in str(first)


def test_attention_uses_current_conversation_run_and_open_questions_once(client, engine):
    with Session(engine) as db, db.begin():
        finished = conversation(db, client.actor_id)
        run(db, client.actor_id, session_id=finished.id, created_at=NOW - timedelta(days=2))
        run(
            db,
            client.actor_id,
            "completed",
            session_id=finished.id,
            created_at=NOW,
            archived_at=NOW,
        )
        waiting = conversation(db, client.actor_id)
        current = run(db, client.actor_id, "waiting_for_user", session_id=waiting.id)
        question = AgentQuestion(
            owner_id=client.actor_id,
            run_id=current.id,
            session_id=waiting.id,
            interrupt_id="synthetic-interrupt",
            branch_id="lead",
            role="Lead",
            tool_call_id="synthetic-call",
            prompt="Private synthetic question body",
        )
        db.add(question)
        without_question = conversation(db, client.actor_id)
        waiting_run = run(db, client.actor_id, "waiting_for_user", session_id=without_question.id)
        failed = conversation(db, client.actor_id)
        obsolete = run(
            db, client.actor_id, session_id=failed.id, created_at=NOW - timedelta(days=1)
        )
        db.add(
            AgentQuestion(
                owner_id=client.actor_id,
                run_id=obsolete.id,
                session_id=failed.id,
                interrupt_id="obsolete",
                branch_id="lead",
                role="Lead",
                tool_call_id="old-call",
                prompt="An obsolete question must be omitted",
            )
        )
        latest = run(db, client.actor_id, session_id=failed.id, created_at=NOW)
        db.flush()
        expected = {str(question.id), str(waiting_run.id), str(latest.id)}
        question_id, task_id, run_id = str(question.id), str(waiting.task_id), str(current.id)
    result = work(client)
    assert result["total"] == 3
    assert {row["id"] for row in result["items"]} == expected
    row = next(row for row in result["items"] if row["id"] == question_id)
    assert (row["kind"], row["state"], row["task_id"], row["run_id"]) == (
        "question",
        "open",
        task_id,
        run_id,
    )
    assert "Private synthetic question" not in str(result)


def test_action_and_run_lanes_preserve_exact_states_without_writes(client, engine):
    attention = {"proposed", "failed", "conflicted", "partial", "outcome_unknown"}
    with Session(engine) as db, db.begin():
        for state in attention | {"queued", "running", "succeeded", "rejected", "revoked"}:
            action(db, client.actor_id, state)
        for state in ("queued", "running", "cancelled", "completed"):
            run(db, client.actor_id, state)
        ready = run(db, client.actor_id, "completed", output="Private synthetic completed output")
        ready_id = str(ready.id)
    with Session(engine) as db:
        before = [
            (row.id, row.state, row.row_version)
            for row in db.scalars(
                select(ReviewedAction).where(ReviewedAction.owner_id == client.actor_id)
            )
        ]
        audit_before = db.scalar(select(func.count()).select_from(AuditEvent))
    assert {row["state"] for row in work(client)["items"]} == attention
    running = work(client, "running")
    assert running["total"] == 4
    assert {(row["kind"], row["state"]) for row in running["items"]} == {
        ("run", "queued"),
        ("run", "running"),
        ("action", "queued"),
        ("action", "running"),
    }
    outputs = work(client, "outputs")
    assert outputs["total"] == 2
    assert any(row["id"] == ready_id and row["state"] == "completed" for row in outputs["items"])
    assert "Private synthetic completed output" not in str(outputs)
    with Session(engine) as db:
        assert [
            (row.id, row.state, row.row_version)
            for row in db.scalars(
                select(ReviewedAction).where(ReviewedAction.owner_id == client.actor_id)
            )
        ] == before
        assert db.scalar(select(func.count()).select_from(AuditEvent)) == audit_before


def test_browser_lanes_show_uncertainty_and_real_preparation_links_without_expiring(
    client, engine, mocker
):
    mocker.patch("command_center.db.work_queue.utc_now", return_value=NOW)
    with Session(engine) as db, db.begin():
        device = BrowserDevice(
            owner_id=client.actor_id, name="Synthetic browser", pairing_expires_at=NOW
        )
        revoked = BrowserDevice(
            owner_id=client.actor_id,
            name="Synthetic revoked browser",
            pairing_expires_at=NOW,
            revoked_at=NOW,
        )
        db.add_all([device, revoked])
        db.flush()
        snapshots = []
        for source in (device, revoked):
            snapshot = BrowserSnapshot(
                id=uuid4(),
                owner_id=client.actor_id,
                device_id=source.id,
                protocol_version=2,
                origin="https://synthetic.example",
                page_url="https://synthetic.example/apply",
                title="Synthetic application",
                fields=[],
            )
            db.add(snapshot)
            snapshots.append(snapshot)
        db.flush()
        package, version = artifact(db, client.actor_id, "package")
        current_task = task(db, client.actor_id)
        db.add(
            ApplicationPreparation(
                id=uuid4(),
                owner_id=client.actor_id,
                task_id=current_task.id,
                snapshot_id=snapshots[0].id,
                artifact_id=package.id,
                current_version_id=version.id,
            )
        )
        commands = {}
        for label, state, remaining, index in (
            ("live", "pending", 1, 0),
            ("expired", "pending", -1, 0),
            ("running", "claimed", 1, 0),
            ("uncertain", "claimed", -1, 0),
            ("failed", "failed", -1, 0),
            ("partial", "partial", -1, 0),
            ("unknown", "outcome_unknown", -1, 0),
            ("revoked", "pending", 1, 1),
        ):
            snapshot = snapshots[index]
            command = BrowserCommand(
                id=uuid4(),
                owner_id=client.actor_id,
                device_id=snapshot.device_id,
                snapshot_id=snapshot.id,
                fields={"f0": "Private synthetic answer"},
                state=state,
                expires_at=NOW + timedelta(minutes=remaining),
                created_at=NOW,
                preparation_version_id=version.id if index == 0 else None,
            )
            db.add(command)
            commands[label] = command.id
        task_id, version_id = str(current_task.id), str(version.id)
    attention = work(client, limit=100)
    assert {row["id"] for row in attention["items"]} == {
        str(value) for key, value in commands.items() if key not in {"running", "expired"}
    }
    by_id = {row["id"]: row for row in attention["items"]}
    uncertain = by_id[str(commands["uncertain"])]
    assert uncertain["state"] == "claimed" and "confirmation" in uncertain["detail"].lower()
    assert uncertain["task_id"] == task_id and uncertain["version_id"] == version_id
    assert "revoked" in by_id[str(commands["revoked"])]["detail"].lower()
    assert "cannot" in by_id[str(commands["revoked"])]["detail"].lower()
    assert [row["id"] for row in work(client, "running")["items"]] == [str(commands["running"])]
    with Session(engine) as db:
        assert db.get(BrowserCommand, commands["expired"]).state == "pending"
        assert db.get(BrowserCommand, commands["uncertain"]).state == "claimed"
        assert db.get(BrowserCommand, commands["uncertain"]).field_results == {}


def test_outputs_pin_latest_owned_active_versions_and_deduplicate_task_links(client, engine):
    with Session(engine) as db, db.begin():
        other = Actor(kind="human", display_name="Synthetic foreign author")
        db.add(other)
        db.flush()
        own, first = artifact(db, client.actor_id)
        latest = ArtifactVersion.from_payload(
            artifact_id=own.id,
            version=2,
            payload={"text": "Private synthetic second version"},
            schema_key="document.text.v1",
            created_by_id=client.actor_id,
        )
        db.add(latest)
        db.flush()
        db.add(
            ArtifactReview(
                artifact_version_id=first.id,
                reviewer_id=client.actor_id,
                decision="approved",
                reason="Synthetic prior review",
            )
        )
        linked = [task(db, client.actor_id), task(db, client.actor_id)]
        foreign_task = task(db, other.id)
        for row in [*linked, foreign_task]:
            db.add(TaskArtifact(task_id=row.id, artifact_id=own.id))
        for kind in ("message", "research", "source", "package"):
            artifact(db, client.actor_id, kind)
        artifact(db, client.actor_id, archived_at=NOW)
        artifact(db, other.id)
        db.add(
            Artifact(
                owner_id=client.actor_id,
                created_by_id=client.actor_id,
                kind="research",
                title="Synthetic artifact without saved version",
            )
        )
        output_id, version_id = str(own.id), str(latest.id)
        other_id = other.id
        linked_ids = {str(row.id) for row in linked}
    result = work(client, "outputs", limit=100)
    assert result["total"] == 3
    row = next(row for row in result["items"] if row["id"] == output_id)
    assert row["artifact_id"] == output_id and row["version_id"] == version_id
    assert row["task_id"] in linked_ids
    assert row["state"] == "unreviewed"
    assert "Private synthetic" not in str(result)
    with Session(engine) as db, db.begin():
        for reviewer_id, decision, created_at in (
            (client.actor_id, "approved", NOW),
            (client.actor_id, "revoked", NOW + timedelta(seconds=1)),
            (other_id, "approved", NOW + timedelta(seconds=2)),
        ):
            db.add(
                ArtifactReview(
                    artifact_version_id=UUID(version_id),
                    reviewer_id=reviewer_id,
                    decision=decision,
                    reason="Synthetic exact-version review",
                    created_at=created_at,
                )
            )
    updated = next(item for item in work(client, "outputs")["items"] if item["id"] == output_id)
    assert updated["state"] == "revoked" and updated["detail"] == "Saved version 2"


@pytest.mark.parametrize(
    "now",
    [
        datetime(2026, 3, 8, 9, 30, tzinfo=UTC),
        datetime(2026, 11, 1, 8, 30, tzinfo=UTC),
    ],
)
def test_daily_tasks_use_local_calendar_days_and_dst_boundaries(client, engine, mocker, now):
    from zoneinfo import ZoneInfo

    mocker.patch("command_center.db.work_queue.utc_now", return_value=now)
    zone = ZoneInfo("America/Los_Angeles")
    today = now.astimezone(zone).date()
    end = datetime.combine(today + timedelta(days=1), datetime.min.time(), zone)
    with Session(engine) as db, db.begin():
        rows = {
            "overdue_date": task(db, client.actor_id, due_date=today - timedelta(days=1)),
            "today_date": task(db, client.actor_id, due_date=today),
            "overdue_instant": task(db, client.actor_id, due_at=now - timedelta(seconds=1)),
            "end_of_day": task(
                db, client.actor_id, state="in_progress", due_at=end - timedelta(seconds=1)
            ),
            "next_date": task(db, client.actor_id, due_date=today + timedelta(days=1)),
            "next_instant": task(db, client.actor_id, due_at=end),
            "unscheduled": task(db, client.actor_id),
            "snoozed": task(db, client.actor_id, state="snoozed", due_date=today),
        }
        task(db, client.actor_id, state="done", completed_at=now, due_date=today)
        task(db, client.actor_id, state="cancelled", due_date=today)
        other = Actor(kind="human", display_name="Synthetic other task owner")
        db.add(other)
        db.flush()
        task(db, other.id, due_date=today)
        ids = {key: str(row.id) for key, row in rows.items()}
    response = client.get("/api/v1/dashboard/tasks", params={"timezone": zone.key, "limit": 100})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["today"] == today.isoformat() and result["timezone"] == zone.key
    assert result["counts"] == {"today": 4, "upcoming": 2, "unscheduled": 1, "snoozed": 1}
    assert [row["id"] for row in result["items"]] == [
        ids["overdue_date"],
        ids["today_date"],
        ids["overdue_instant"],
        ids["end_of_day"],
    ]
    assert {row["id"]: row["due_status"] for row in result["items"]} == {
        ids["overdue_date"]: "overdue",
        ids["today_date"]: "today",
        ids["overdue_instant"]: "overdue",
        ids["end_of_day"]: "today",
    }
    for view, expected in (
        ("upcoming", {ids["next_date"], ids["next_instant"]}),
        ("unscheduled", {ids["unscheduled"]}),
        ("snoozed", {ids["snoozed"]}),
    ):
        page = client.get(
            "/api/v1/dashboard/tasks", params={"timezone": zone.key, "view": view}
        ).json()
        assert page["total"] == len(expected)
        assert {row["id"] for row in page["items"]} == expected
        assert page["counts"] == result["counts"]


def test_daily_tasks_paginate_due_priority_id_and_validate_human_timezone(client, engine, mocker):
    mocker.patch("command_center.db.work_queue.utc_now", return_value=NOW)
    with Session(engine) as db, db.begin():
        high = [task(db, client.actor_id, due_date=date(2026, 9, 22), priority=3) for _ in range(2)]
        low = task(db, client.actor_id, due_date=date(2026, 9, 22), priority=0)
        expected = [*sorted(str(row.id) for row in high), str(low.id)]
    path = "/api/v1/dashboard/tasks"
    for index, record_id in enumerate(expected):
        response = client.get(path, params={"limit": 1, "offset": index})
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["timezone"] == "UTC" and result["total"] == 3
        assert result["items"][0]["id"] == record_id
    assert client.get(path, params={"offset": 9}).json()["items"] == []
    for params in ({"timezone": "Not/A_Timezone"}, {"timezone": "../UTC"}, {"limit": 101}):
        assert client.get(path, params=params).status_code == 422
    assert client.get("/api/v1/dashboard/work", params={"lane": "invented"}).status_code == 422
    client.app.dependency_overrides[authenticate] = lambda: Identity(
        client.actor_id, "synthetic-agent", run_id=uuid4()
    )
    assert client.get(path).status_code == 403
    assert client.get("/api/v1/dashboard/work").status_code == 403
