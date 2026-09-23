"""Grouped autofill never mixes approved entries or invents date precision."""

from uuid import uuid4

import pytest

from command_center.api.browser_contracts import FormField
from command_center.db.application_preparations import initial_answers
from command_center.db.browser import validate_temporal_answer
from command_center.db.career import CareerEntry
from command_center.db.profile_facts import ProfileFact, ProfileFactRevision


def approved(kind="experience", **changes):
    entry = CareerEntry.model_validate(
        {
            "kind": kind,
            "organization": "Synthetic Orbit",
            "start_date": "2020-09",
        }
        | changes
    )
    fact = ProfileFact(id=uuid4(), owner_id=uuid4(), field=kind)
    revision = ProfileFactRevision(id=uuid4(), fact_id=fact.id, version=1, value=entry.encode())
    fact.active_revision_id = revision.id
    return fact, revision


def field(index, component, *, group=0, kind="experience", **changes):
    return {
        "id": f"f{index}",
        "label": component,
        "type": "text",
        "value_state": "empty",
        "options": [],
        "history": {
            "group_id": f"h{group}",
            "kind": kind,
            "position": group,
            "label": f"Work experience {group + 1}",
            "component": component,
            "order": "newest_first",
        },
    } | changes


def test_each_repeated_section_uses_one_exact_approved_revision():
    recent = approved(
        organization="Synthetic Recent", role="Engineer", location="Remote", current=True
    )
    old = approved(
        organization="Synthetic Earlier", role="Analyst", start_date="2016", end_date="2019"
    )
    fields = [
        field(0, "organization"),
        field(1, "role"),
        field(2, "start_year"),
        field(3, "organization", group=1),
        field(4, "role", group=1),
    ]
    answers = initial_answers(fields, [old, recent], None)
    assert [answer["value"] for answer in answers] == [
        "Synthetic Recent",
        "Engineer",
        "2020",
        "Synthetic Earlier",
        "Analyst",
    ]
    assert all(answer["evidence"][0]["revision_id"] == str(recent[1].id) for answer in answers[:3])
    assert all(answer["evidence"][0]["revision_id"] == str(old[1].id) for answer in answers[3:])


def test_existing_group_and_ambiguous_dates_never_fall_back_to_unrelated_scalars():
    scalar = ProfileFact(id=uuid4(), owner_id=uuid4(), field="location")
    scalar_revision = ProfileFactRevision(id=uuid4(), fact_id=scalar.id, version=1, value="My home")
    fields = [field(0, "organization", value_state="present"), field(1, "location")]
    answers = initial_answers(fields, [approved(), (scalar, scalar_revision)], None)
    assert all(answer["status"] == "preserved" and answer["value"] is None for answer in answers)
    ambiguous = initial_answers(
        [field(0, "organization"), field(1, "location")],
        [approved(), approved(start_date="2020")],
        None,
    )
    assert all(
        answer["status"] == "needs_input" and answer["value"] is None for answer in ambiguous
    )
    assert (
        initial_answers([field(0, "location")], [(scalar, scalar_revision)], None)[0]["value"]
        is None
    )


def test_dates_use_only_known_precision_and_unique_displayed_month_labels():
    month = field(
        0,
        "start_month",
        type="select",
        options=["0", "8"],
        option_labels={"0": "January", "8": "September"},
    )
    date = field(1, "start_date")
    date["history"]["date_format"] = "mm/yyyy"
    unknown = field(2, "end_month")
    current = field(3, "current", type="checkbox", options=["true", "false"])
    answers = initial_answers([month, date, unknown, current], [approved()], None)
    assert [answer["value"] for answer in answers] == ["8", "09/2020", None, None]
    date["history"]["date_format"] = "yyyy-mm-dd"
    assert initial_answers([date], [approved()], None)[0]["value"] is None
    assert initial_answers([month], [approved(start_date="2020")], None)[0]["value"] is None


def test_duplicate_components_mixed_group_kinds_and_missing_entries_require_review():
    fields = [field(0, "organization"), field(1, "organization")]
    assert all(answer["value"] is None for answer in initial_answers(fields, [approved()], None))
    fields[1]["history"].update(kind="education", component="degree")
    assert all(answer["value"] is None for answer in initial_answers(fields, [approved()], None))
    assert (
        initial_answers([field(0, "organization", group=2)], [approved()], None)[0]["value"] is None
    )


def test_explicit_oldest_first_order_and_single_undated_entry():
    entry = approved(start_date=None, degree="BSc", kind="education")
    assert (
        initial_answers([field(0, "degree", kind="education")], [entry], None)[0]["value"] == "BSc"
    )
    fields = [field(0, "organization")]
    fields[0]["history"]["order"] = "oldest_first"
    answer = initial_answers(
        fields, [approved(), approved(organization="Oldest", start_date="2010")], None
    )[0]
    assert answer["value"] == "Oldest"


@pytest.mark.parametrize(
    "kind,good,bad,minimum,step",
    [
        ("month", "2020-09", "2020-10", "2020-01", "2"),
        ("date", "2024-02-29", "2024-03-01", "2024-02-27", "2"),
    ],
)
def test_calendar_control_precision_range_and_step(kind, good, bad, minimum, step):
    descriptor = field(
        0,
        "start_date",
        type=kind,
        temporal_constraints={
            "minimum": minimum,
            "maximum": None,
            "step": step,
            "step_base": minimum,
        },
    )
    FormField.model_validate(descriptor)
    validate_temporal_answer(descriptor, good)
    for value in (bad, "2020", "2023-02-29", "0000-01"):
        with pytest.raises(ValueError):
            validate_temporal_answer(descriptor, value)
    assert initial_answers([descriptor], [approved(start_date=good)], None)[0]["value"] == good
    with pytest.raises(ValueError):
        FormField.model_validate(descriptor | {"temporal_constraints": None})


def test_native_calendar_never_completes_a_partial_date_or_infers_current():
    descriptor = field(
        0,
        "start_date",
        type="date",
        temporal_constraints={
            "minimum": None,
            "maximum": None,
            "step": "1",
            "step_base": "1970-01-01",
        },
    )
    assert initial_answers([descriptor], [approved()], None)[0]["value"] is None
