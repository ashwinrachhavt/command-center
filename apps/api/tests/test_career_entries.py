"""Career history preserves source precision and never guesses missing dates."""

import json

import pytest

from command_center.db.career import (
    CareerEntry,
    decode_career,
    linkedin_career,
    linkedin_career_suggestion,
)
from command_center.db.profile_facts import ProfileFact


def experience(**changes):
    return {
        "schema_key": "career.v1",
        "kind": "experience",
        "organization": "Synthetic Orbit",
        "role": "Engineer",
        "start_date": "2020",
    } | changes


def test_career_dates_keep_precision_and_unknown_end_dates():
    entry = CareerEntry.model_validate(experience())
    assert entry.start_date == "2020"
    assert entry.end_date is None and entry.current is None
    assert decode_career(entry.encode()) == entry
    assert CareerEntry.model_validate(experience(end_date="2020-02")).end_date == "2020-02"
    assert CareerEntry.model_validate(experience(start_date="2024-02-29"))
    # An overlapping partial interval is not proof of an impossible order.
    assert CareerEntry.model_validate(experience(start_date="2020-12", end_date="2020"))


@pytest.mark.parametrize(
    "changes",
    [
        {"organization": " "},
        {"start_date": "2023-02-29"},
        {"start_date": "2020-13"},
        {"start_date": "0000"},
        {"start_date": "2021", "end_date": "2020"},
        {"current": True, "end_date": "2022"},
        {"current": "false"},
        {"degree": "BSc"},
        {"kind": "education", "role": "Student"},
        {"description": "x" * 2001},
        {"unrecognized": "must not be silently discarded"},
    ],
)
def test_invalid_career_entries_are_rejected(changes):
    with pytest.raises(ValueError):
        CareerEntry.model_validate(experience(**changes))


def test_structured_values_respect_fact_kind_and_context():
    value = CareerEntry.model_validate(experience()).encode()
    ProfileFact._validate_content("experience", value, None)
    with pytest.raises(ValueError, match="field"):
        ProfileFact._validate_content("education", value, None)
    with pytest.raises(ValueError, match="context"):
        ProfileFact._validate_content("experience", value, "Only for a particular application")
    for malformed in [
        '{"schema_key":"career.v1",',
        json.dumps(experience(schema_key="career.v2")),
    ]:
        with pytest.raises(ValueError):
            ProfileFact._validate_content("experience", malformed, None)
    assert decode_career("Worked as an engineer") is None
    assert decode_career('{"unrelated": "old text"}') is None


def test_linkedin_mapping_does_not_drop_unknown_or_ambiguous_source_values():
    row = {
        "Company Name": "Synthetic Orbit",
        "Title": "Engineer",
        "Description": "Designed synthetic systems.\nKept source paragraphs.",
        "Location": "Remote",
        "Started On": "September 2020",
        "Finished On": "",
    }
    entry = linkedin_career("experience", row)
    assert entry and entry.start_date == "2020-09"
    assert entry.current is None and entry.end_date is None
    assert entry.description == row["Description"]
    current = linkedin_career("experience", row | {"Finished On": "Present"})
    assert current and current.current is True
    # Unsupported values stay in the legacy fact and original source for manual mapping.
    assert linkedin_career("experience", row | {"Started On": "Spring 2020"}) is None
    assert linkedin_career("experience", row | {"Finished On": "2018"}) is None
    education = linkedin_career(
        "education",
        {
            "School Name": "Synthetic College",
            "Start Date": "2015",
            "End Date": "2019",
            "Degree Name": "BSc",
            "Notes": "Synthetic notes",
            "Activities": "Robotics",
        },
    )
    assert education and education.organization == "Synthetic College"
    assert education.degree == "BSc" and education.current is None
    assert "Synthetic notes" in education.description and "Robotics" in education.description


def test_legacy_suggestions_require_unambiguous_linkedin_fields():
    value = (
        "Company Name: Synthetic Orbit\nTitle: Engineer\nDescription: First line\nSecond line\n"
        "Location: Remote\nStarted On: 2020\nFinished On: "
    )
    context = "LinkedIn export · Positions.csv"
    suggestion = linkedin_career_suggestion("experience", value, context)
    assert suggestion and suggestion.description == "First line\nSecond line"
    assert linkedin_career_suggestion("experience", value.rstrip(), context) == suggestion
    assert linkedin_career_suggestion("experience", value, None) is None
    assert linkedin_career_suggestion("education", value, context) is None
    assert (
        linkedin_career_suggestion(
            "experience", value.replace("Second line", "Title: other role"), context
        )
        is None
    )
