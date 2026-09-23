"""Synthetic import acceptance tests; never copy real exports into fixtures."""

import csv
import importlib.util
import json
import shutil
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from command_center.db.artifacts import Artifact, ArtifactVersion
from command_center.db.career import decode_career
from command_center.db.crm import CandidateProfile, Contact, ContactObservation, Job, Opportunity
from command_center.db.models import Actor, AuditEvent, Task
from command_center.db.profile_facts import ProfileFact, ProfileFactRevision

spec = importlib.util.spec_from_file_location(
    "workspace_import", Path(__file__).resolve().parents[3] / "scripts/import_workspace.py"
)
importer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(importer)


def write_csv(path, columns, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(rows)


def table(headers, rows):
    return (
        '<table header-row="true">'
        + "".join(
            "<tr>" + "".join(f"<td>{value}</td>" for value in row) + "</tr>"
            for row in [headers, *rows]
        )
        + "</table>"
    )


@pytest.fixture
def sources(tmp_path):
    directory = tmp_path / "linkedin"
    columns = [
        "First Name",
        "Last Name",
        "URL",
        "Email Address",
        "Company",
        "Position",
        "Connected On",
    ]
    row = [
        "Alex",
        "Example",
        "https://www.linkedin.com/in/synthetic-alex/?tracking=x",
        "",
        "Synthetic Orbit",
        "Engineer",
        "01 Jan 2025",
    ]
    write_csv(directory / "Connections.csv", columns, [row, row, ["", "", "", "", "", "", ""]])
    original = (directory / "Connections.csv").read_text()
    (directory / "Connections.csv").write_text("Notes:\nSynthetic export preamble\n\n" + original)
    write_csv(
        directory / "Company Follows.csv",
        ["Organization", "Followed On"],
        [["Synthetic Orbit", "01 Jan 2025"]],
    )
    write_csv(
        directory / "Jobs/Saved Jobs.csv",
        ["Saved Date", "Job Url", "Job Title", "Company Name"],
        [
            [
                "2025-01-01",
                "https://linkedin.com/jobs/view/123456/?tracking=y",
                "Platform Engineer",
                "Synthetic Orbit",
            ]
        ],
    )
    write_csv(
        directory / "Profile.csv",
        ["First Name", "Last Name", "Headline", "Geo Location", "Birth Date"],
        [["Synthetic", "Owner", "Engineer", "Example City", "PRIVATE-EXCLUDED"]],
    )
    history = table(
        [
            "Company / Organization",
            "Attendees & Contacts",
            "Role & Focus",
            "Date & Platform",
            "Notes & Technical Problem Context",
        ],
        [
            [
                "Synthetic Orbit",
                "Alex Example (alex@example.com), Robin Example (no-reply@example.com)",
                "Past screen",
                "Jan 2025",
                "Historical meeting",
            ]
        ],
    )
    companies = table(
        ["#", "Company", "Primary Status / Stage", "Core Focus", "Founder(s) Listed"],
        [["1", "Synthetic Orbit", "Series A", "Tools", "Sam Example"]],
    )
    priority = table(
        [
            "Contact",
            "Relationship / context",
            "Current opportunity signal",
            "Recommended next action",
        ],
        [
            [
                "Alex Example",
                "Synthetic Orbit / recruiting",
                "Previous invitation",
                "Review current status",
            ]
        ],
    )
    doc = {
        "leads": {
            "url": "https://notion.so/synthetic-leads",
            "text": history + companies + "</page>",
            "page_last_edited_at": "2026-09-21T00:00:00Z",
        },
        "contacts": {
            "url": "https://notion.so/synthetic-contacts",
            "text": table(["Field"], [["Description"]]) + priority + "</page>",
        },
    }
    snapshot = tmp_path / "notion.json"
    snapshot.write_text(json.dumps(doc))
    return directory, snapshot


def test_import_preserves_history_deduplicates_and_is_repeatable(session, sources):
    owner = Actor(
        id=uuid4(),
        kind="human",
        display_name="Synthetic owner",
        auth_subject="synthetic|import-test",
    )
    other = Actor(id=uuid4(), kind="human", display_name="Other synthetic owner")
    session.add_all([owner, other])
    session.flush()
    other_contact = Contact(
        owner_id=other.id,
        name="Alex Example",
        linkedin_url="https://linkedin.com/in/synthetic-alex",
    )
    session.add(other_contact)
    session.flush()
    run = importer.WorkspaceImport(session, owner.id)
    run.linkedin(sources[0])
    run.notion(sources[1])
    session.flush()
    contacts = list(session.scalars(select(Contact).where(Contact.owner_id == owner.id)))
    assert len(contacts) == 3
    alex = next(c for c in contacts if c.name == "Alex Example")
    assert alex.email == "alex@example.com"
    assert alex.relationship == "connected"
    assert "Historical meeting" in alex.notes
    assert "Data row" not in alex.notes or "Source" in alex.notes
    assert next(c for c in contacts if c.name == "Robin Example").email is None
    assert run.counts["empty_connections_skipped"] == 1
    assert session.scalar(select(Job).where(Job.owner_id == owner.id)) is None
    opportunities = list(
        session.scalars(select(Opportunity).where(Opportunity.owner_id == owner.id))
    )
    assert len(opportunities) == 2 and all(o.stage == "researching" for o in opportunities)
    tasks = list(session.scalars(select(Task).where(Task.owner_id == owner.id)))
    assert len(tasks) == 1 and tasks[0].due_date is None and tasks[0].due_at is None
    assert tasks[0].title.startswith("Review imported lead:")
    assert session.get(CandidateProfile, owner.id).display_name == "Synthetic Owner"
    assert other_contact.notes is None  # No cross-owner identity merge or annotation.
    before = session.scalar(select(func.count()).select_from(AuditEvent))
    again = importer.WorkspaceImport(session, owner.id)
    again.linkedin(sources[0])
    again.notion(sources[1])
    session.flush()
    assert not any(value for key, value in again.counts.items() if key.endswith("_created"))
    assert session.scalar(select(func.count()).select_from(AuditEvent)) == before


def test_notions_malformed_and_partial_sources_fail_closed(session, sources):
    with pytest.raises(ValueError, match="Malformed"):
        importer.notion_tables(
            "<table><tr><td>A</td><td>B</td></tr><tr><td>Only one</td></tr></table>"
        )
    owner = Actor(id=uuid4(), kind="human", display_name="Synthetic")
    session.add(owner)
    session.flush()
    doc = json.loads(sources[1].read_text())
    doc["leads"]["truncated"] = True
    sources[1].write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="Incomplete"):
        importer.WorkspaceImport(session, owner.id).notion(sources[1])


def test_contact_does_not_merge_names_across_companies_or_email_conflicts(session):
    owner = Actor(id=uuid4(), kind="human", display_name="Synthetic")
    session.add(owner)
    session.flush()
    run = importer.WorkspaceImport(session, owner.id)
    a = run.company("Synthetic One", "Source one")
    b = run.company("Synthetic Two", "Source two")
    one = run.contact(
        name="Same Name", company=a, locator="row1", notes="row1", email="one@example.com"
    )
    two = run.contact(
        name="Same Name", company=b, locator="row2", notes="row2", email="two@example.com"
    )
    three = run.contact(
        name="Same Name", company=a, locator="row3", notes="row3", email="three@example.com"
    )
    assert len({one.id, two.id, three.id}) == 3


def test_linkedin_maps_professional_fields_and_excludes_private_account_history(session, sources):
    owner = Actor(id=uuid4(), kind="human", display_name="Synthetic")
    session.add(owner)
    session.flush()
    directory = sources[0]
    for filename, (_, columns) in importer.LINKEDIN_TABLES.items():
        values = [f"Synthetic {column}" for column in columns]
        if "Started On" in columns:
            values[columns.index("Started On")] = "2020"
        if "Finished On" in columns:
            values[columns.index("Finished On")] = ""
        write_csv(directory / filename, columns, [values])
    write_csv(
        directory / "Messages.csv", ["FROM", "CONTENT"], [["Unknown", "EXCLUDED-MESSAGE-BODY"]]
    )
    write_csv(directory / "Invitations.csv", ["Message"], [["EXCLUDED-INVITATION"]])
    write_csv(
        directory / "Ad_Targeting.csv",
        ["Company", "Company", ""],
        [["EXCLUDED-AD", "PRIVATE", "PRIVATE"]],
    )
    run = importer.WorkspaceImport(session, owner.id)
    run.linkedin(directory)
    facts = list(session.scalars(select(ProfileFact).where(ProfileFact.owner_id == owner.id)))
    expected = {field for field, _ in importer.LINKEDIN_TABLES.values() if field}
    assert expected <= {fact.field for fact in facts}
    assert all(fact.active_revision_id is None for fact in facts)
    versions = list(
        session.scalars(select(ArtifactVersion).join(Artifact).where(Artifact.owner_id == owner.id))
    )
    text = "\n".join(str(version.payload) for version in versions)
    assert "PRIVATE-EXCLUDED" not in text
    assert "EXCLUDED-MESSAGE-BODY" not in text
    assert "EXCLUDED-INVITATION" not in text
    assert "EXCLUDED-AD" not in text
    for fact in facts:
        revision = session.get(ProfileFactRevision, fact.current_revision_id)
        source = session.get(ArtifactVersion, revision.source_version_id)
        assert revision.source_excerpt in source.payload["text"]
    experience = next(fact for fact in facts if fact.field == "experience")
    revision = session.get(ProfileFactRevision, experience.current_revision_id)
    entry = decode_career(revision.value)
    assert entry and entry.start_date == "2020"
    assert entry.current is None and entry.end_date is None
    assert revision.context is None
    assert "Started On: 2020" in revision.source_excerpt
    assert revision.source_excerpt.endswith("Finished On: ")
    observations = list(
        session.scalars(select(ContactObservation).where(ContactObservation.owner_id == owner.id))
    )
    assert len(observations) == 2  # Every named source row keeps its own evidence.
    assert observations[0].first_name == "Alex"
    assert observations[0].connected_on == "01 Jan 2025"
    assert observations[0].company == "Synthetic Orbit"
    inventory = next(item for item in run.column_mapping if item["file"] == "Ad_Targeting.csv")
    assert [item["position"] for item in inventory["columns"]] == [1, 2, 3]
    assert all(item["disposition"] == "excluded" for item in inventory["columns"])


def test_structured_import_upgrade_does_not_duplicate_or_change_approved_legacy_facts(
    session, sources, monkeypatch
):
    owner = Actor(id=uuid4(), kind="human", display_name="Synthetic")
    session.add(owner)
    session.flush()
    columns = importer.LINKEDIN_TABLES["Positions.csv"][1]
    write_csv(
        sources[0] / "Positions.csv",
        columns,
        [["Synthetic Orbit", "Engineer", "Built tools", "Remote", "2020", ""]],
    )
    with monkeypatch.context() as legacy_mapping:
        legacy_mapping.setattr(importer, "linkedin_career", lambda field, row: None)
        importer.WorkspaceImport(session, owner.id).linkedin(sources[0])
    fact = session.scalar(
        select(ProfileFact).where(
            ProfileFact.owner_id == owner.id, ProfileFact.field == "experience"
        )
    )
    original_revision = fact.current_revision_id
    fact.review(
        reviewer_id=owner.id,
        revision_id=original_revision,
        decision="approved",
        reviewer_is_human=True,
        reason="Checked source",
        request_id=uuid4(),
    )
    session.flush()
    replay = importer.WorkspaceImport(session, owner.id)
    replay.linkedin(sources[0])
    session.refresh(fact)
    assert fact.current_revision_id == original_revision
    assert fact.active_revision_id == original_revision
    assert decode_career(session.get(ProfileFactRevision, original_revision).value) is None
    assert (
        session.scalar(
            select(func.count())
            .select_from(ProfileFact)
            .where(ProfileFact.owner_id == owner.id, ProfileFact.field == "experience")
        )
        == 1
    )


def test_linkedin_replay_after_folder_move_preserves_manual_edits_and_reviews(
    session, sources, tmp_path
):
    owner = Actor(id=uuid4(), kind="human", display_name="Synthetic")
    session.add(owner)
    session.flush()
    run = importer.WorkspaceImport(session, owner.id)
    run.linkedin(sources[0])
    contact = session.scalar(select(Contact).where(Contact.owner_id == owner.id))
    contact.revise(
        {"title": "Manually updated title", "notes": "My private notes"}, request_id=uuid4()
    )
    fact = session.scalar(select(ProfileFact).where(ProfileFact.owner_id == owner.id))
    fact.review(
        reviewer_id=owner.id,
        revision_id=fact.current_revision_id,
        decision="rejected",
        reviewer_is_human=True,
        reason="Review later",
        request_id=uuid4(),
    )
    session.flush()
    before_sources = session.scalar(
        select(func.count()).select_from(Artifact).where(Artifact.owner_id == owner.id)
    )
    before_facts = session.scalar(
        select(func.count()).select_from(ProfileFact).where(ProfileFact.owner_id == owner.id)
    )
    moved = tmp_path / "moved-linkedin"
    shutil.copytree(sources[0], moved)
    replay = importer.WorkspaceImport(session, owner.id)
    replay.linkedin(moved)
    assert contact.title == "Manually updated title"
    assert contact.notes == "My private notes"
    assert session.get(ProfileFactRevision, fact.current_revision_id).review_state() == "rejected"
    assert (
        session.scalar(
            select(func.count()).select_from(Artifact).where(Artifact.owner_id == owner.id)
        )
        == before_sources
    )
    assert (
        session.scalar(
            select(func.count()).select_from(ProfileFact).where(ProfileFact.owner_id == owner.id)
        )
        == before_facts
    )
    assert (
        session.scalar(
            select(func.count())
            .select_from(ContactObservation)
            .where(ContactObservation.owner_id == owner.id)
        )
        == 2
    )


def test_allowed_csv_fails_closed_on_duplicate_headers(tmp_path):
    path = tmp_path / "Skills.csv"
    write_csv(path, ["Name", "Name"], [["One", "Two"]])
    with pytest.raises(ValueError, match="duplicate"):
        importer.csv_rows(path)
