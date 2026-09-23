"""Operator-only, transactional import of local Notion and LinkedIn snapshots.

Dry-run by default. Inputs and reports contain private data and belong outside Git.
Use the existing schemas/models; this does not create an unauthenticated API.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid5

from command_center.api import schemas
from command_center.core.config import Settings
from command_center.db.artifacts import Artifact, ArtifactVersion
from command_center.db.career import CareerEntry, linkedin_career
from command_center.db.crm import (
    CandidateProfile,
    Company,
    Contact,
    ContactObservation,
    Job,
    Opportunity,
    record_event,
)
from command_center.db.evidence import SourceRecord
from command_center.db.models import Actor, Task
from command_center.db.profile_facts import FactField, ProfileFact
from command_center.db.session import create_database_engine
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.orm import Session


def normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def plain(value: str) -> str:
    value = re.sub(r"<br\s*/?>", "\n", value)
    value = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", value)
    return (
        html.unescape(re.sub(r"<[^>]+>", "", value))
        .replace("**", "")
        .replace("`", "")
        .strip()
    )


def canonical_url(value: str) -> str:
    if not value.strip():
        return ""
    url = urlsplit(value.strip())
    if url.scheme not in {"http", "https"} or not url.hostname:
        raise ValueError("Invalid source URL")
    host = url.hostname.casefold().removeprefix("www.")
    return urlunsplit(("https", host, url.path.rstrip("/"), "", ""))


def csv_rows(path: Path) -> list[dict[str, str]]:
    content = path.read_text(encoding="utf-8-sig")
    if path.name == "Connections.csv":
        marker = "First Name,Last Name,URL,Email Address,Company,Position,Connected On"
        position = content.find(marker)
        if position < 0:
            raise ValueError("Unrecognized LinkedIn Connections.csv header")
        content = content[position:]
    reader = csv.DictReader(io.StringIO(content))
    headers = reader.fieldnames or []
    if len(set(headers)) != len(headers) or any(not key for key in headers):
        raise ValueError(f"Ambiguous duplicate or empty headers in {path.name}")
    rows = list(reader)
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValueError(f"Malformed column count in {path.name}")
    return [
        {key: (value or "").strip() for key, value in row.items() if key is not None}
        for row in rows
    ]


# Explicit allowlist: export files are never imported merely because they exist.
LINKEDIN_PROFILE_COLUMNS = (
    "First Name",
    "Last Name",
    "Headline",
    "Summary",
    "Industry",
    "Geo Location",
    "Websites",
    "Twitter Handles",
)
LINKEDIN_TABLES: dict[str, tuple[FactField | None, tuple[str, ...]]] = {
    "Profile Summary.csv": ("summary", ("Profile Summary",)),
    "Positions.csv": (
        "experience",
        (
            "Company Name",
            "Title",
            "Description",
            "Location",
            "Started On",
            "Finished On",
        ),
    ),
    "Education.csv": (
        "education",
        ("School Name", "Start Date", "End Date", "Notes", "Degree Name", "Activities"),
    ),
    "Skills.csv": ("skill", ("Name",)),
    "Projects.csv": (
        "project",
        ("Title", "Description", "Url", "Started On", "Finished On"),
    ),
    "Certifications.csv": (
        "certification",
        ("Name", "Url", "Authority", "Started On", "Finished On", "License Number"),
    ),
    "Courses.csv": ("course", ("Name", "Number")),
    "Languages.csv": ("language", ("Name", "Proficiency")),
    "Publications.csv": (
        "publication",
        ("Name", "Published On", "Description", "Publisher", "Url"),
    ),
    "Recommendations_Received.csv": (
        "recommendation",
        (
            "First Name",
            "Last Name",
            "Company",
            "Job Title",
            "Text",
            "Creation Date",
            "Status",
        ),
    ),
    "Endorsement_Received_Info.csv": (
        None,
        (
            "Endorsement Date",
            "Skill Name",
            "Endorser First Name",
            "Endorser Last Name",
            "Endorser Public Url",
            "Endorsement Status",
        ),
    ),
}
LINKEDIN_CONTACT_COLUMNS = (
    "First Name",
    "Last Name",
    "URL",
    "Email Address",
    "Company",
    "Position",
    "Connected On",
)


def linkedin_row_text(row: dict[str, str], columns: tuple[str, ...]) -> str:
    return "\n".join(f"{key}: {row.get(key, '')}" for key in columns)


def linkedin_destination(filename: str, column: str) -> str:
    if filename == "Connections.csv":
        field = dict(
            zip(
                LINKEDIN_CONTACT_COLUMNS,
                (
                    "first_name",
                    "last_name",
                    "linkedin_url",
                    "email",
                    "company",
                    "position",
                    "connected_on",
                ),
                strict=True,
            )
        ).get(column)
        return (
            f"contact_observations.{field}; conservative CRM match/fill"
            if field
            else "excluded"
        )
    if filename == "Profile.csv":
        field = {
            "First Name": "full_name",
            "Last Name": "full_name",
            "Headline": "headline",
            "Geo Location": "location",
            "Summary": "summary",
            "Websites": "website",
        }.get(column)
        return (
            f"profile_facts.{field} (proposed)"
            if field
            else "professional source text"
            if column in LINKEDIN_PROFILE_COLUMNS
            else "excluded"
        )
    fact, columns = LINKEDIN_TABLES.get(filename, (None, ()))
    if column not in columns:
        return "excluded"
    return (
        f"profile_facts.{fact} (proposed); original column label in value"
        if fact
        else "attributed professional source text"
    )


def linkedin_inventory(directory: Path) -> list[dict[str, object]]:
    """Account for every column without reading excluded message/account bodies."""
    inventory = []
    for path in sorted(directory.rglob("*.csv")):
        filename = path.relative_to(directory).as_posix()
        allowed = (
            LINKEDIN_CONTACT_COLUMNS
            if filename == "Connections.csv"
            else (
                LINKEDIN_PROFILE_COLUMNS
                if filename == "Profile.csv"
                else LINKEDIN_TABLES.get(filename, (None, ()))[1]
            )
        )
        with path.open(encoding="utf-8-sig", newline="") as source:
            reader = csv.reader(source)
            headers = next(reader, [])
            if filename == "Connections.csv":
                while headers and headers[:2] != ["First Name", "Last Name"]:
                    headers = next(reader, [])
                    # LinkedIn places an empty separator between preamble and header.
                    while not headers:
                        headers = next(reader, None)
                        if headers is None:
                            break
        inventory.append(
            {
                "file": filename,
                "columns": [
                    {
                        "position": i,
                        "name": name,
                        "disposition": "mapped" if name in allowed else "excluded",
                        "destination": linkedin_destination(filename, name),
                    }
                    for i, name in enumerate(headers or [], 1)
                ],
                "disposition": "contacts"
                if filename == "Connections.csv"
                else "professional-profile"
                if allowed
                else "excluded",
            }
        )
    return inventory


def notion_tables(content: str) -> list[list[dict[str, str]]]:
    tables = []
    for table in re.findall(r"<table\b[^>]*>(.*?)</table>", content, re.DOTALL):
        rows = [
            [
                plain(cell)
                for cell in re.findall(r"<td\b[^>]*>(.*?)</td>", row, re.DOTALL)
            ]
            for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", table, re.DOTALL)
        ]
        if not rows or any(len(row) != len(rows[0]) for row in rows):
            raise ValueError("Malformed Notion table; refusing partial extraction")
        tables.append([dict(zip(rows[0], row, strict=True)) for row in rows[1:]])
    return tables


class WorkspaceImport:
    """One import transaction with conservative identity matching and provenance."""

    def __init__(self, session: Session, actor_id: UUID):
        self.session = session
        self.actor_id = actor_id
        self.request_id = uuid5(actor_id, "notion-linkedin-import-v1")
        self.counts: Counter[str] = Counter()
        self.issues: list[dict[str, str]] = []
        self.sources: list[dict[str, str]] = []
        self.rows: list[dict[str, str]] = []
        self.column_mapping: list[dict[str, object]] = []
        self.companies: dict[str, list[Company]] = defaultdict(list)
        self.contacts: list[Contact] = list(
            session.scalars(select(Contact).where(Contact.owner_id == actor_id))
        )
        self.contact_urls: dict[str, list[Contact]] = defaultdict(list)
        self.contact_emails: dict[str, list[Contact]] = defaultdict(list)
        self.contact_names: dict[tuple[str, UUID | None], list[Contact]] = defaultdict(
            list
        )
        self.jobs = {
            canonical_url(job.source_url): job
            for job in session.scalars(select(Job).where(Job.owner_id == actor_id))
            if job.source_url
        }
        for company in session.scalars(
            select(Company).where(Company.owner_id == actor_id)
        ):
            self.companies[normalized(company.name)].append(company)
        for contact in self.contacts:
            self.index_contact(contact)

    def stable_id(self, kind: str, identity: str) -> UUID:
        return uuid5(self.actor_id, f"source-import:v1:{kind}:{identity}")

    def issue(self, locator: str, reason: str) -> None:
        self.issues.append({"locator": locator, "reason": reason})
        self.counts["issues"] += 1

    def index_contact(self, contact: Contact) -> None:
        if contact.linkedin_url:
            group = self.contact_urls[canonical_url(contact.linkedin_url)]
            if contact not in group:
                group.append(contact)
        if contact.email:
            group = self.contact_emails[normalized(contact.email)]
            if contact not in group:
                group.append(contact)
        group = self.contact_names[normalized(contact.name), contact.company_id]
        if contact not in group:
            group.append(contact)

    def source(self, title: str, provider: str, locator: str, content: str) -> str:
        digest = hashlib.sha256(content.encode()).hexdigest()
        artifact_id = self.stable_id("source", f"{provider}:{locator}:{digest}")
        artifact = self.session.get(Artifact, artifact_id)
        if artifact is None and provider == "linkedin-export":
            artifact = self.session.scalar(
                select(Artifact)
                .join(ArtifactVersion)
                .join(SourceRecord)
                .where(
                    Artifact.owner_id == self.actor_id,
                    Artifact.title == title,
                    SourceRecord.provider == provider,
                    ArtifactVersion.payload["text"].astext == content,
                )
                .order_by(Artifact.created_at, Artifact.id)
                .limit(1)
            )
            if artifact:
                artifact_id = artifact.id
        if artifact is None:
            Artifact.draft(
                self.session,
                record_id=artifact_id,
                owner_id=self.actor_id,
                title=title,
                kind="source",
                sensitivity="private",
                text=content,
                document_type_id=None,
                request_id=self.request_id,
            )
            self.session.flush()
            self.session.add(
                SourceRecord(
                    id=self.stable_id("source-record", str(artifact_id)),
                    artifact_version_id=uuid5(artifact_id, "version:1"),
                    provider=provider,
                    account_scope=str(self.actor_id),
                    locator=locator,
                    extraction_method=(
                        "linkedin-contacts-profile-v2"
                        if provider == "linkedin-export"
                        else "local-snapshot-import-v1"
                    ),
                )
            )
            self.counts["artifacts_created"] += 1
        self.sources.append(
            {
                "provider": provider,
                "locator": locator,
                "sha256": digest,
                "artifact_id": str(artifact_id),
            }
        )
        return f"Source: {locator}\nSource artifact: {artifact_id}\nSnapshot SHA-256: {digest}"

    def create(
        self, model: Any, contract: Any, identity: str, data: dict[str, Any]
    ) -> Any:
        record_id = self.stable_id(model.__tablename__, identity)
        record = self.session.get(model, record_id)
        if record is not None:
            self.counts[model.__tablename__ + "_existing"] += 1
            return record
        # Same input contracts as manual/API creation; no guessed enum or unsafe URL values.
        values = contract.model_validate(data).model_dump(
            mode="json", exclude_none=True
        )
        for field in ("company_id", "contact_id", "job_id", "opportunity_id"):
            if field in values:
                values[field] = UUID(values[field])
        record = model(id=record_id, owner_id=self.actor_id, **values)
        self.session.add(record)
        self.session.flush()
        record_event(
            self.session,
            self.actor_id,
            self.request_id,
            f"{model.__tablename__}.imported",
            model.__tablename__,
            record_id,
            source="local-snapshot-import-v1",
        )
        self.counts[model.__tablename__ + "_created"] += 1
        return record

    def annotate(self, record: Any, field: str, note: str) -> None:
        if record.archived_at or note in (getattr(record, field) or ""):
            return
        previous = getattr(record, field) or ""
        value = f"{previous}\n\n{note}".strip()
        if len(value) > 20000:
            self.issue(
                str(record.id),
                "Additional provenance retained in source artifact; notes at capacity",
            )
            return
        record.revise({field: value}, request_id=self.request_id)
        self.counts["records_annotated"] += 1

    def company(
        self, name: str, note: str, *, annotate_existing: bool = True
    ) -> Company | None:
        name = name.strip()
        if not name:
            return None
        key = normalized(name)
        matches = self.companies[key]
        if len(matches) > 1:
            raise ValueError(
                "Ambiguous existing company identity; inspect staging before import"
            )
        if matches:
            company = matches[0]
            # Keep concise source notes on company records, not thousands of connection rows.
            if annotate_existing and note not in (company.description or ""):
                self.annotate(company, "description", note)
            return company
        company = self.create(
            Company, schemas.CompanyCreate, key, {"name": name, "description": note}
        )
        matches.append(company)
        return company

    def contact(
        self,
        *,
        name: str,
        company: Company | None,
        locator: str,
        notes: str,
        email: str = "",
        url: str = "",
        title: str = "",
        relationship: str = "new",
        annotate_existing: bool = True,
    ) -> Contact:
        url = canonical_url(url)
        email = email.strip().casefold()
        if email.startswith(("no-reply@", "noreply@", "notifications@")):
            email = ""  # Original address remains in the source/notes, not a person's email field.
        if email:
            try:
                schemas.ContactCreate(name=name, email=email)
            except ValidationError:
                self.issue(
                    locator,
                    "Invalid email retained in source; contact imported without email",
                )
                email = ""
        matches = self.contact_urls.get(url, []) if url else []
        if not matches and email:
            matches = [
                c
                for c in self.contact_emails.get(email, [])
                if normalized(c.name) == normalized(name)
            ]
        if not matches and company:
            matches = [
                c
                for c in self.contact_names.get((normalized(name), company.id), [])
                if (
                    not url
                    or not c.linkedin_url
                    or canonical_url(c.linkedin_url) == url
                )
                and (not email or not c.email or normalized(c.email) == email)
            ]
        if len(matches) == 1:
            contact = matches[0]
            if annotate_existing:
                self.annotate(contact, "notes", notes)
            changes = {}
            for key, value in {
                "email": email,
                "linkedin_url": url,
                "title": title,
            }.items():
                if value and not getattr(contact, key):
                    changes[key] = value
            if changes and not contact.archived_at:
                contact.revise(changes, request_id=self.request_id)
                self.index_contact(contact)
            self.counts["contacts_matched"] += 1
        else:
            if len(matches) > 1:
                self.issue(
                    locator,
                    "Ambiguous contact match; preserved as a separate source identity",
                )
            identity = (
                url
                or f"{normalized(name)}:{email}:{company.id if company else locator}"
            )
            contact = self.create(
                Contact,
                schemas.ContactCreate,
                identity,
                {
                    "name": name,
                    "company_id": company.id if company else None,
                    "email": email or None,
                    "linkedin_url": url or None,
                    "title": title or None,
                    "relationship": relationship,
                    "notes": notes,
                },
            )
            if contact not in self.contacts:
                self.contacts.append(contact)
                self.index_contact(contact)
        self.rows.append({"source": locator, "kind": "contact", "id": str(contact.id)})
        return contact

    def linkedin(self, directory: Path) -> None:
        self.column_mapping = linkedin_inventory(directory)
        path = directory / "Connections.csv"
        if path.exists():
            rows = csv_rows(path)
            projected = io.StringIO()
            writer = csv.DictWriter(
                projected, LINKEDIN_CONTACT_COLUMNS, extrasaction="ignore"
            )
            writer.writeheader()
            writer.writerows(rows)
            content = projected.getvalue()
            digest = hashlib.sha256(content.encode()).hexdigest()
            locator = f"linkedin-export:Connections.csv#sha256={digest}"
            source = self.source(
                "LinkedIn — connections snapshot", "linkedin-export", locator, content
            )
            version_id = uuid5(UUID(self.sources[-1]["artifact_id"]), "version:1")
            self.counts["linkedin_connection_rows"] = len(rows)
            for number, row in enumerate(rows, 1):
                row_locator = f"{locator}&data-row={number}"
                name = " ".join(
                    filter(None, [row.get("First Name"), row.get("Last Name")])
                )
                if not name:
                    self.counts["empty_connections_skipped"] += 1
                    self.rows.append(
                        {"source": row_locator, "kind": "empty-connection", "id": ""}
                    )
                    continue
                company = self.company(
                    row.get("Company", ""),
                    "Employer label from LinkedIn connection export; current employment unverified.\n"
                    + source,
                    annotate_existing=False,
                )
                raw_url = row.get("URL", "")
                try:
                    canonical_url(raw_url)
                except ValueError:
                    self.issue(
                        row_locator,
                        "Invalid URL retained in source; contact imported without URL",
                    )
                    raw_url = ""
                contact = self.contact(
                    name=name,
                    company=company,
                    locator=row_locator,
                    email=row.get("Email Address", ""),
                    url=raw_url,
                    title=row.get("Position", ""),
                    relationship="connected",
                    annotate_existing=False,
                    notes=f"LinkedIn connection since {row.get('Connected On') or 'unknown date'}. "
                    f"Export observation; not outreach permission or confirmed current employment.\n{source}",
                )
                ContactObservation.capture_linkedin(
                    self.session,
                    contact=contact,
                    source_version_id=version_id,
                    source_row=number,
                    row=row,
                    request_id=self.request_id,
                )
                self.counts["linkedin_connections_mapped"] += 1
        # Saved jobs, company follows, conversations, invitations and account data
        # are outside the confirmed contacts/professional-profile import.
        self.career(directory)

    def profile_fact(
        self,
        field: FactField,
        value: str,
        source_version_id: UUID,
        excerpt: str,
        locator: str,
        career_entry: CareerEntry | None = None,
    ) -> None:
        if not value.strip():
            return
        if len(value) > 4000 or len(excerpt) > 4000:
            self.issue(
                locator,
                "Professional entry exceeds fact length; full text retained in source for review",
            )
            return
        # Same source/value replays exactly, including after a local folder move.
        # Editing, rejecting or approving a proposal must never be undone by re-import.
        record_id = self.stable_id(
            "linkedin-fact", f"{source_version_id}:{field}:{normalized(value)}"
        )
        if self.session.get(ProfileFact, record_id):
            return
        ProfileFact.propose(
            self.session,
            record_id=record_id,
            owner_id=self.actor_id,
            field=field,
            value=career_entry.encode() if career_entry else value,
            context=(
                None
                if career_entry
                else f"LinkedIn export · {locator}. Original date precision retained; blank end dates are unknown."
                + (
                    " Recommendation text is attributed to its source author."
                    if field == "recommendation"
                    else ""
                )
            ),
            source_version_id=source_version_id,
            source_excerpt=excerpt,
            valid_until=None,
            agent_proposal=False,
            request_id=self.request_id,
        )
        self.counts["profile_facts_created"] += 1

    def career(self, directory: Path) -> None:
        path = directory / "Profile.csv"
        profile_rows = csv_rows(path) if path.exists() else []
        profile_row = profile_rows[0] if profile_rows else {}
        source = ""
        if profile_rows:
            content = "\n\n".join(
                linkedin_row_text(row, LINKEDIN_PROFILE_COLUMNS) for row in profile_rows
            )
            source = self.source(
                "LinkedIn — career profile",
                "linkedin-export",
                "linkedin-export:Profile.csv",
                content,
            )
            version_id = uuid5(UUID(self.sources[-1]["artifact_id"]), "version:1")
            for row in profile_rows:
                for field, value, excerpt in (
                    (
                        "full_name",
                        " ".join(
                            filter(None, (row.get("First Name"), row.get("Last Name")))
                        ),
                        linkedin_row_text(row, ("First Name", "Last Name")),
                    ),
                    ("headline", row.get("Headline", ""), row.get("Headline", "")),
                    (
                        "location",
                        row.get("Geo Location", ""),
                        row.get("Geo Location", ""),
                    ),
                    ("summary", row.get("Summary", ""), row.get("Summary", "")),
                ):
                    self.profile_fact(field, value, version_id, excerpt, "Profile.csv")
                for website in re.findall(
                    r"https?://[^\s,;)\]]+", row.get("Websites", "")
                ):
                    self.profile_fact(
                        "website", website, version_id, website, "Profile.csv"
                    )
        for filename, (field, columns) in LINKEDIN_TABLES.items():
            path = directory / filename
            if not path.exists():
                continue
            rows = csv_rows(path)
            self.counts[f"linkedin_{path.stem}_rows"] = len(rows)
            if not rows:
                continue
            excerpts = [linkedin_row_text(row, columns) for row in rows]
            content = "\n\n".join(
                f"Data row {number}\n{excerpt}"
                for number, excerpt in enumerate(excerpts, 1)
            )
            self.source(
                f"LinkedIn — {path.stem}",
                "linkedin-export",
                f"linkedin-export:{filename}",
                content,
            )
            version_id = uuid5(UUID(self.sources[-1]["artifact_id"]), "version:1")
            if field:
                for number, (row, excerpt) in enumerate(
                    zip(rows, excerpts, strict=True), 1
                ):
                    if not any(row.get(column) for column in columns):
                        continue
                    value = row.get(columns[0], "") if len(columns) == 1 else excerpt
                    self.profile_fact(
                        field,
                        value,
                        version_id,
                        excerpt,
                        f"{filename}, data row {number}",
                        career_entry=linkedin_career(field, row),
                    )
        if not profile_rows:
            return
        profile = self.session.get(CandidateProfile, self.actor_id)
        if profile is None:
            profile = CandidateProfile(actor_id=self.actor_id)
            self.session.add(profile)
            self.session.flush()
        changes = {}
        for field, value in {
            "display_name": " ".join(
                filter(
                    None, [profile_row.get("First Name"), profile_row.get("Last Name")]
                )
            ),
            "headline": profile_row.get("Headline", ""),
            "location": profile_row.get("Geo Location", ""),
        }.items():
            if value and getattr(profile, field) in {"", "My workspace"}:
                changes[field] = value
        preferences = dict(profile.preferences)
        if "linkedin_import" not in preferences:
            preferences["linkedin_import"] = {
                "provenance": source,
                "status": "Imported career context; not approved application facts",
            }
            changes["preferences"] = preferences
        if changes:
            profile.revise(changes, request_id=self.request_id)
            self.counts["profiles_updated"] += 1

    def notion(self, path: Path) -> None:
        snapshot = json.loads(path.read_text())
        leads, registry = snapshot["leads"], snapshot["contacts"]
        for page in [leads, registry]:
            if page.get("truncated") or not page["text"].rstrip().endswith("</page>"):
                raise ValueError("Incomplete Notion snapshot")
        tables = notion_tables(leads["text"])
        history, companies = tables
        priority = notion_tables(registry["text"])[1]
        source = self.source(
            "Notion — leads and historical interactions",
            "notion-snapshot",
            leads["url"],
            leads["text"],
        )
        context = (
            "Saved Notion snapshot; current status unverified. Page edited: "
            + leads["page_last_edited_at"]
        )
        for number, row in enumerate(history, 1):
            locator = f"{leads['url']}#table=1&row={number}"
            note = f"Historical interaction: {row['Date & Platform']}\nFocus: {row['Role & Focus']}\n"
            note += f"{row['Notes & Technical Problem Context']}\n{context}\n{source}\n{locator}"
            company = self.company(row["Company / Organization"], note)
            people = []
            for entry in row["Attendees & Contacts"].split(","):
                match = re.search(r"\(([^()\s]+@[^()\s]+)\)", entry)
                email = match[1] if match else ""
                name = re.sub(r"\([^()]*@[^()]*\)", "", entry).strip()
                if name:
                    people.append(
                        self.contact(
                            name=name,
                            company=company,
                            locator=locator,
                            email=email,
                            notes=f"Reported attendee: {entry.strip()}\n{note}",
                        )
                    )
            self.create(
                Opportunity,
                schemas.OpportunityCreate,
                locator,
                {
                    "company_id": company.id,
                    "contact_id": people[0].id if people else None,
                    "title": f"Revisit: {row['Role & Focus']}",
                    "stage": "researching",
                    "notes": note,
                },
            )
        for number, row in enumerate(companies, 1):
            locator = f"{leads['url']}#table=2&row={number}"
            note = f"Company target from Notion. Reported company stage: {row['Primary Status / Stage']}.\n"
            note += f"Focus: {row['Core Focus']}\nFounders as listed: {row['Founder(s) Listed']}\n{context}\n{source}\n{locator}"
            company = self.company(row["Company"], note)
            self.create(
                Opportunity,
                schemas.OpportunityCreate,
                locator,
                {
                    "company_id": company.id,
                    "title": f"Explore: {company.name}",
                    "stage": "researching",
                    "notes": note,
                },
            )
            for name in row["Founder(s) Listed"].split(";"):
                if normalized(name) not in {
                    "",
                    "stealth",
                    "unknown",
                    "n/a",
                    "—",
                    "not listed",
                }:
                    self.contact(
                        name=name.strip(),
                        company=company,
                        locator=locator,
                        title="Founder (Notion source; unverified)",
                        notes=note,
                    )
        source = self.source(
            "Notion — priority contact registry",
            "notion-snapshot",
            registry["url"],
            registry["text"],
        )
        for number, row in enumerate(priority, 1):
            locator = f"{registry['url']}#table=2&row={number}"
            context = row["Relationship / context"]
            candidates = [part.strip() for part in context.split("/")]
            company = next(
                (
                    self.companies[normalized(name)][0]
                    for name in candidates
                    if len(self.companies.get(normalized(name), [])) == 1
                ),
                None,
            )
            if (
                company is None
                and len(candidates) == 2
                and candidates[0] == "Recruiter"
                and " " not in candidates[1]
            ):
                company = self.company(
                    candidates[1],
                    "Company explicitly named in Notion contact registry.\n" + source,
                )
            note = f"Context: {context}\nSignal: {row['Current opportunity signal']}\n"
            note += f"Suggested next action (not performed): {row['Recommended next action']}\n{source}\n{locator}"
            person = self.contact(
                name=row["Contact"], company=company, locator=locator, notes=note
            )
            self.create(
                Task,
                schemas.TaskCreate,
                f"review-priority:{locator}",
                {
                    "title": f"Review imported lead: {person.name}",
                    "priority": 2,
                    "rationale": f"Validate this imported lead's current status before acting.\n{note}",
                },
            )
        self.counts.update(
            notion_history_rows=len(history),
            notion_company_targets=len(companies),
            notion_priority_rows=len(priority),
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actor", required=True, type=UUID)
    parser.add_argument(
        "--linkedin",
        type=Path,
        help="Extracted LinkedIn export directory; contacts and professional profile only",
    )
    parser.add_argument("--notion", type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.linkedin and not args.notion:
        parser.error("Choose --linkedin and/or --notion")
    if args.linkedin and not args.linkedin.is_dir():
        parser.error("--linkedin must point to the extracted export directory")
    engine = create_database_engine(Settings().database_url)
    with Session(engine) as session:
        actor = session.get(Actor, args.actor)
        if (
            actor is None
            or not actor.active
            or actor.kind != "human"
            or not actor.auth_subject
        ):
            raise ValueError(
                "Import requires an existing, active authenticated human actor"
            )
        # Serialize imports for this owner without blocking ordinary CRM reads.
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": f"source-import:{actor.id}"},
        )
        importer = WorkspaceImport(session, args.actor)
        if args.linkedin:
            importer.linkedin(args.linkedin.resolve())
        if args.notion:
            importer.notion(args.notion.resolve())
        session.flush()
        report = {
            "mode": "applied" if args.apply else "dry-run",
            "actor_id": str(args.actor),
            "at": datetime.now(UTC).isoformat(),
            "counts": dict(importer.counts),
            "issues": importer.issues,
            "sources": importer.sources,
            "rows": importer.rows,
            "column_mapping": importer.column_mapping,
        }
        if args.apply:
            session.commit()
        else:
            session.rollback()
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        args.report.chmod(0o600)
        print(
            json.dumps(
                {
                    "mode": report["mode"],
                    "counts": report["counts"],
                    "report": str(args.report),
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
