"""Typed career entries inside the existing immutable profile-fact lifecycle."""

import calendar
import json
import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CareerKind = Literal["experience", "education"]


def date_interval(value: str) -> tuple[date, date]:
    """Retain partial dates; compare only the interval their precision establishes."""
    if not re.fullmatch(r"\d{4}(?:-\d{2}(?:-\d{2})?)?", value):
        raise ValueError("Use YYYY, YYYY-MM or YYYY-MM-DD for career dates")
    parts = [int(part) for part in value.split("-")]
    year = parts[0]
    month = parts[1] if len(parts) > 1 else 1
    day = parts[2] if len(parts) > 2 else 1
    earliest = date(year, month, day)
    last_month = month if len(parts) > 1 else 12
    last_day = day if len(parts) > 2 else calendar.monthrange(year, last_month)[1]
    return earliest, date(year, last_month, last_day)


class CareerEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_key: Literal["career.v1"] = "career.v1"
    kind: CareerKind
    organization: str = Field(min_length=1, max_length=200)
    role: str | None = Field(default=None, max_length=200)
    degree: str | None = Field(default=None, max_length=200)
    field_of_study: str | None = Field(default=None, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    start_date: str | None = None
    end_date: str | None = None
    current: bool | None = None
    description: str = Field(default="", max_length=2000)

    @field_validator("organization", "role", "degree", "field_of_study", "location")
    @classmethod
    def nonblank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Use null for an unknown field; organization cannot be blank")
        return value

    @field_validator("start_date", "end_date")
    @classmethod
    def partial_date(cls, value: str | None) -> str | None:
        if value is not None:
            date_interval(value)
        return value

    @model_validator(mode="after")
    def coherent_entry(self) -> "CareerEntry":
        if self.kind == "experience" and (
            self.degree is not None or self.field_of_study is not None
        ):
            raise ValueError("Employment entries cannot contain education fields")
        if self.kind == "education" and self.role is not None:
            raise ValueError("Education entries cannot contain an employment role")
        if self.current is True and self.end_date is not None:
            raise ValueError("A current entry cannot have an end date")
        if (
            self.start_date
            and self.end_date
            and date_interval(self.start_date)[0] > date_interval(self.end_date)[1]
        ):
            raise ValueError("Start date must not be after end date")
        return self

    def encode(self) -> str:
        value = self.model_dump_json(exclude_none=True)
        if len(value) > 4000:
            raise ValueError("Career entry must fit within 4000 characters")
        return value


def decode_career(value: str) -> CareerEntry | None:
    """Legacy prose stays prose; invalid reserved career encodings fail closed."""
    try:
        payload = json.loads(value)
    except ValueError:
        if re.search(r'"schema_key"\s*:\s*"career\.', value):
            raise ValueError("Invalid structured career entry") from None
        return None
    if not isinstance(payload, dict):
        return None
    schema = payload.get("schema_key")
    if not isinstance(schema, str) or not schema.startswith("career."):
        return None
    return CareerEntry.model_validate(payload)


def linkedin_date(value: str) -> str | None:
    value = value.strip()
    if not value:
        return None
    # English month names are explicit, independent of the host locale.
    months = (
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
    )
    match = re.fullmatch(r"([A-Za-z]+) (\d{4})", value)
    if match:
        month_name, year = match.groups()
        for month, name in enumerate(months, 1):
            if month_name.lower() in (name, name[:3]):
                value = f"{year}-{month:02d}"
                break
    date_interval(value)
    return value


def linkedin_career(field: str, row: dict[str, str]) -> CareerEntry | None:
    """Map known CSV columns or retain the complete legacy value when mapping is uncertain."""
    if field not in {"experience", "education"}:
        return None
    employment = field == "experience"
    end = row.get("Finished On" if employment else "End Date", "").strip()
    present = end.casefold() == "present"
    description = (
        row.get("Description", "")
        if employment
        else "\n\n".join(
            f"{name}: {row[name]}" for name in ("Notes", "Activities") if row.get(name)
        )
    )
    try:
        entry = CareerEntry(
            kind="experience" if employment else "education",
            organization=row.get("Company Name" if employment else "School Name", ""),
            role=(row.get("Title") or None) if employment else None,
            degree=(row.get("Degree Name") or None) if not employment else None,
            location=(row.get("Location") or None) if employment else None,
            start_date=linkedin_date(row.get("Started On" if employment else "Start Date", "")),
            end_date=None if present else linkedin_date(end),
            current=True if present else None,
            description=description,
        )
        entry.encode()
        return entry
    except ValueError:
        return None


def linkedin_career_suggestion(field: str, value: str, context: str | None) -> CareerEntry | None:
    """Suggest mappings only for unambiguous legacy importer output; never approve it."""
    if not context or not context.startswith("LinkedIn export · "):
        return None
    columns = {
        "experience": (
            "Company Name",
            "Title",
            "Description",
            "Location",
            "Started On",
            "Finished On",
        ),
        "education": (
            "School Name",
            "Start Date",
            "End Date",
            "Notes",
            "Degree Name",
            "Activities",
        ),
    }.get(field)
    if columns is None:
        return None
    pattern = r"^(" + "|".join(re.escape(name) for name in columns) + r"):(?: |(?=$))"
    matches = list(re.finditer(pattern, value, re.MULTILINE))
    if tuple(match[1] for match in matches) != columns or matches[0].start() != 0:
        return None
    row = {
        match[1]: value[match.end() : matches[index + 1].start() - 1]
        if index + 1 < len(matches)
        else value[match.end() :]
        for index, match in enumerate(matches)
    }
    return linkedin_career(field, row)
