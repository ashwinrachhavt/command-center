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
from command_center.db.artifacts import Artifact
from command_center.db.crm import (
    CandidateProfile,
    Company,
    Contact,
    Job,
    Opportunity,
    record_event,
)
from command_center.db.evidence import SourceRecord
from command_center.db.models import Actor, Task
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
    return [
        {key: (value or "").strip() for key, value in row.items() if key is not None}
        for row in csv.DictReader(io.StringIO(content))
    ]


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
                    extraction_method="local-snapshot-import-v1",
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

    def company(self, name: str, note: str) -> Company | None:
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
            if note not in (company.description or ""):
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
        path = directory / "Connections.csv"
        source = self.source(
            "LinkedIn — connections snapshot",
            "linkedin-export",
            path.as_uri(),
            path.read_text(encoding="utf-8-sig"),
        )
        rows = csv_rows(path)
        self.counts["linkedin_connection_rows"] = len(rows)
        for number, row in enumerate(rows, 1):
            locator = f"{path.as_uri()}#data-row={number}"
            name = " ".join(filter(None, [row["First Name"], row["Last Name"]]))
            if not name:
                self.counts["empty_connections_skipped"] += 1
                self.rows.append(
                    {"source": locator, "kind": "empty-connection", "id": ""}
                )
                continue
            company = self.company(
                row["Company"],
                "Employer label from LinkedIn connection export; current employment unverified.\n"
                + source,
            )
            self.contact(
                name=name,
                company=company,
                locator=locator,
                email=row["Email Address"],
                url=row["URL"],
                title=row["Position"],
                relationship="connected",
                notes=f"LinkedIn connection since {row['Connected On'] or 'unknown date'}. "
                f"Export observation; not outreach permission or confirmed advocacy.\n{source}\n{locator}",
            )
        path = directory / "Company Follows.csv"
        source = self.source(
            "LinkedIn — followed companies",
            "linkedin-export",
            path.as_uri(),
            path.read_text(encoding="utf-8-sig"),
        )
        for row in csv_rows(path):
            self.company(
                row["Organization"],
                f"Followed on LinkedIn since {row['Followed On']}.\n{source}",
            )
            self.counts["linkedin_company_follow_rows"] += 1
        path = directory / "Jobs" / "Saved Jobs.csv"
        source = self.source(
            "LinkedIn — saved jobs",
            "linkedin-export",
            path.as_uri(),
            path.read_text(encoding="utf-8-sig"),
        )
        saved_jobs = csv_rows(path)
        self.counts["linkedin_saved_job_rows"] = len(saved_jobs)
        missing_job_rows = []
        for number, row in enumerate(saved_jobs, 1):
            company = self.company(
                row["Company Name"], "Company from LinkedIn saved jobs.\n" + source
            )
            if company is None:
                missing_job_rows.append(number)
                self.issue(
                    f"{path.as_uri()}#data-row={number}",
                    "Saved job has no company; retained in source",
                )
                continue
            url = canonical_url(row["Job Url"])
            note = (
                f"Saved on LinkedIn: {row['Saved Date']}. Availability is unverified; "
            )
            note += f"this is not an application or current interview.\n{source}\nData row: {number}"
            job = self.jobs.get(url)
            if job is None:
                job = self.create(
                    Job,
                    schemas.JobCreate,
                    url,
                    {
                        "company_id": company.id,
                        "title": row["Job Title"],
                        "source_url": url,
                        "status": "unknown",
                        "description": note,
                    },
                )
                self.jobs[url] = job
            self.create(
                Opportunity,
                schemas.OpportunityCreate,
                f"saved-job:{job.id}",
                {
                    "company_id": company.id,
                    "job_id": job.id,
                    "title": row["Job Title"],
                    "stage": "researching",
                    "notes": note,
                },
            )
            self.counts["linkedin_saved_jobs_imported"] += 1
        if missing_job_rows:
            self.create(
                Task,
                schemas.TaskCreate,
                "review-incomplete-saved-jobs",
                {
                    "title": "Review saved jobs with missing details",
                    "priority": 1,
                    "rationale": (
                        f"{len(missing_job_rows)} saved-job rows lack employer details. "
                        "They remain in the private source archive; no employer or role was invented. "
                        f"Check source URLs. Data rows: {missing_job_rows}.\n{source}"
                    ),
                },
            )
        self.career(directory)

    def career(self, directory: Path) -> None:
        profile_row = csv_rows(directory / "Profile.csv")[0]
        # Import career context, excluding DOB, home address, phones, saved answers and messages.
        public_profile = {
            key: profile_row.get(key, "")
            for key in [
                "First Name",
                "Last Name",
                "Headline",
                "Summary",
                "Industry",
                "Geo Location",
                "Websites",
            ]
        }
        source = self.source(
            "LinkedIn — career profile",
            "linkedin-export",
            (directory / "Profile.csv").as_uri(),
            json.dumps(public_profile, ensure_ascii=False, indent=2),
        )
        for filename in [
            "Profile Summary.csv",
            "Positions.csv",
            "Education.csv",
            "Skills.csv",
            "Projects.csv",
        ]:
            path = directory / filename
            if path.exists():
                self.source(
                    f"LinkedIn — {path.stem}",
                    "linkedin-export",
                    path.as_uri(),
                    path.read_text(encoding="utf-8-sig"),
                )
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
    parser.add_argument("--linkedin", required=True, type=Path)
    parser.add_argument("--notion", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
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
        importer.linkedin(args.linkedin.resolve())
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
