"""Synthetic import acceptance tests; never copy real exports into fixtures."""

import csv
import importlib.util
import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from command_center.db.crm import CandidateProfile, Contact, Job, Opportunity
from command_center.db.models import Actor, AuditEvent, Task

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
    assert session.scalar(select(Job).where(Job.owner_id == owner.id)).status == "unknown"
    opportunities = list(
        session.scalars(select(Opportunity).where(Opportunity.owner_id == owner.id))
    )
    assert len(opportunities) == 3 and all(o.stage == "researching" for o in opportunities)
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
