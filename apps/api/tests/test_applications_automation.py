"""Automation run state machine: authorization gate, token fence, evidence."""

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from command_center.db.applications_automation import (
    Application,
    ApplicationImport,
    AutomationRun,
)
from command_center.db.browser import BrowserDevice
from command_center.db.base import utc_now
from command_center.db.errors import RecordConflict
from command_center.db.models import Actor, AuditEvent


@pytest.fixture
def owner(engine) -> UUID:
    actor_id = uuid4()
    with Session(engine) as db, db.begin():
        db.add(Actor(id=actor_id, kind="human", display_name="Synthetic automation owner"))
    return actor_id


@pytest.fixture
def session(engine, owner):
    # Isolate each test: outer transaction rolled back, savepoint inside.
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            yield db
        transaction.rollback()


def make_application(session, owner) -> Application:
    batch = ApplicationImport(
        id=uuid4(),
        owner_id=owner,
        filename="applications.csv",
        byte_size=64,
        state="completed",
        row_count=1,
        accepted_count=1,
    )
    session.add(batch)
    session.flush()
    application = Application(
        id=uuid4(),
        owner_id=owner,
        import_id=batch.id,
        source_row=1,
        source_hash="a" * 64,
        company="Acme",
        job_title="Engineer",
        job_url="https://boards.greenhouse.io/acme/jobs/123",
        adapter_platform="greenhouse",
        status="ready_to_run",
    )
    session.add(application)
    session.flush()
    return application


def make_device(session, owner) -> UUID:
    device = BrowserDevice(
        id=uuid4(),
        owner_id=owner,
        name="Synthetic device",
        pairing_expires_at=utc_now() + timedelta(minutes=5),
    )
    session.add(device)
    session.flush()
    return device.id


def enqueue(session, application, mode="fill_only") -> AutomationRun:
    return AutomationRun.enqueue(
        session,
        application=application,
        mode=mode,
        adapter_platform="greenhouse",
        adapter_revision="0" * 64,
        request_id=uuid4(),
    )


def test_enqueue_refuses_submit_without_authorization(session, owner):
    application = make_application(session, owner)
    with pytest.raises(RecordConflict, match="explicit authorization"):
        enqueue(session, application, mode="submit")


def test_authorize_stamps_flag_and_audit(session, owner):
    application = make_application(session, owner)
    request_id = uuid4()
    application.authorize(request_id=request_id)
    session.flush()
    assert application.submit_authorized_at is not None
    assert application.submit_authorized_by == owner
    event = session.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "application.submit_authorized",
            AuditEvent.subject_id == application.id,
        )
    )
    assert event is not None
    assert event.request_id == request_id  # same transaction, same request


def test_authorized_submit_mode_enqueue_then_complete(session, owner):
    application = make_application(session, owner)
    application.authorize(request_id=uuid4())
    run = enqueue(session, application, mode="submit")
    session.flush()
    claimed = AutomationRun.claim(session, device_id=make_device(session, owner))
    assert claimed is not None and claimed.id == run.id
    assert application.status == "running"
    claimed.complete(
        claimed.run_token,
        field_evidence={"f001": {"status": "filled"}},
        request_id=uuid4(),
    )
    session.flush()
    assert application.status == "submitted"


def test_fill_only_run_completes_to_ready_for_review(session, owner):
    application = make_application(session, owner)
    application.authorize(request_id=uuid4())  # authorized but fill_only anyway
    run = enqueue(session, application, mode="fill_only")
    session.flush()
    claimed = AutomationRun.claim(session, device_id=make_device(session, owner))
    assert claimed is not None and claimed.id == run.id
    claimed.complete(
        claimed.run_token,
        field_evidence={"f001": {"status": "filled"}},
        request_id=uuid4(),
    )
    session.flush()
    assert application.status == "ready_for_review"


def test_failed_and_unknown_runs_mark_application_failed(session, owner):
    application = make_application(session, owner)
    run = enqueue(session, application)
    session.flush()
    claimed = AutomationRun.claim(session, device_id=make_device(session, owner))
    claimed.mark_outcome_unknown(
        claimed.run_token, detail="page changed mid-run", request_id=uuid4()
    )
    session.flush()
    assert application.status == "failed"
    assert claimed.state == "outcome_unknown"
    assert run.state == "outcome_unknown"


def test_run_token_fence_rejects_wrong_token(session, owner):
    application = make_application(session, owner)
    run = enqueue(session, application)
    session.flush()
    claimed = AutomationRun.claim(session, device_id=make_device(session, owner))
    with pytest.raises(RecordConflict, match="token was lost"):
        claimed.complete(UUID(int=1), field_evidence={}, request_id=uuid4())
    assert run.state == "running"


def test_expire_stale_recycles_for_reclaim(session, owner):
    application = make_application(session, owner)
    run = enqueue(session, application)
    session.flush()
    first = AutomationRun.claim(session, device_id=make_device(session, owner))
    assert first.id == run.id
    # Force the token to expire.
    first.run_token_expires_at = utc_now() - timedelta(minutes=1)
    session.flush()
    expired = AutomationRun.expire_stale(session)
    assert expired == 1
    assert run.state == "failed"
    assert run.error == "run_token_expired"
    second = AutomationRun.claim(session, device_id=make_device(session, owner))
    if second is not None:
        # Recycling creates a new attempt, never a silently reused token.
        assert second.id != run.id or second.run_token != first.run_token


def test_no_path_reaches_submitted_without_authorization(session, owner):
    application = make_application(session, owner)
    enqueue(session, application, mode="fill_only")
    session.flush()
    claimed = AutomationRun.claim(session, device_id=make_device(session, owner))
    claimed.complete(claimed.run_token, field_evidence={}, request_id=uuid4())
    session.flush()
    assert application.status == "ready_for_review"
    assert application.submit_authorized_at is None
    assert application.status != "submitted"


def test_revoke_authorization_clears_stamp(session, owner):
    application = make_application(session, owner)
    application.authorize(request_id=uuid4())
    session.flush()
    application.revoke_authorization(request_id=uuid4())
    session.flush()
    assert application.submit_authorized_at is None
    assert application.submit_authorized_by is None
