"""Public posting identities never merge different jobs or bypass owned preparation scope."""

from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session
from test_application_continuation import capture_page
from test_application_preparations import client as client
from test_application_preparations import post, prepare, shared_page

from command_center.api.application_preparations import (
    PreparationCreate,
    preparation_request_payload,
)
from command_center.db.artifacts import ArtifactVersion
from command_center.db.job_identity import observed_identity, posting_identity

JOB_ID = "12345678-1234-5678-abcd-1234567890ab"
GH = "https://job-boards.greenhouse.io/synthetic/jobs/123"
LEVER = f"https://jobs.lever.co/synthetic/{JOB_ID}"
ASHBY = f"https://jobs.ashbyhq.com/synthetic/{JOB_ID}"
WORKDAY = "https://synthetic.wd5.myworkdayjobs.com/en-US/External/job/Remote/Engineer_R123"
ICIMS = "https://careers-synthetic.icims.com/jobs/123"


@pytest.mark.parametrize(
    "url,platform,organization,identifier,canonical",
    [
        (GH + "?source=tracking#form", "greenhouse", "synthetic", "123", GH),
        ("https://boards.greenhouse.io/synthetic/jobs/123/", "greenhouse", "synthetic", "123", GH),
        (
            "https://boards.greenhouse.io/embed/job_app?for=synthetic&token=123&email=private",
            "greenhouse",
            "synthetic",
            "123",
            GH,
        ),
        (LEVER + "/apply?email=private", "lever", "synthetic", JOB_ID, LEVER),
        (
            LEVER.replace("jobs.lever", "jobs.eu.lever") + "/apply",
            "lever",
            "synthetic",
            JOB_ID,
            LEVER.replace("jobs.lever", "jobs.eu.lever"),
        ),
        (ASHBY + "/application", "ashby", "synthetic", JOB_ID, ASHBY),
        (
            WORKDAY + "/apply/autofillWithResume",
            "workday",
            "synthetic.wd5.myworkdayjobs.com@External",
            "R123",
            WORKDAY,
        ),
        (
            ICIMS + "/engineer/job?session=private",
            "icims",
            "careers-synthetic.icims.com",
            "123",
            ICIMS,
        ),
        (
            GH.replace("synthetic", "Synthetic%2Dteam"),
            "greenhouse",
            "Synthetic-team",
            "123",
            GH.replace("synthetic", "Synthetic-team"),
        ),
        (LEVER.replace(JOB_ID, JOB_ID.upper()), "lever", "synthetic", JOB_ID, LEVER),
    ],
)
def test_posting_url_normalization(url, platform, organization, identifier, canonical):
    result = posting_identity(url)
    assert result == {
        "platform": platform,
        "organization": organization,
        "posting_id": identifier,
        "canonical_url": canonical,
    }
    assert "?" not in result["canonical_url"] and "#" not in result["canonical_url"]
    assert "private" not in str(result)


@pytest.mark.parametrize(
    "url",
    [
        "http://job-boards.greenhouse.io/synthetic/jobs/123",
        "https://job-boards.greenhouse.io.evil.test/synthetic/jobs/123",
        "https://user:password@job-boards.greenhouse.io/synthetic/jobs/123",
        "https://job-boards.greenhouse.io:8443/synthetic/jobs/123",
        "https://job-boards.greenhouse.io/synthetic//jobs/123",
        "https://job-boards.greenhouse.io/synthetic%2Fother/jobs/123",
        "https://job-boards.greenhouse.io/synthetic%252Fother/jobs/123",
        "https://job-boards.greenhouse.io/synthetic/jobs/123/unknown",
        "https://boards.greenhouse.io/embed/job_app?for=a&for=b&token=123",
        "https://boards.greenhouse.io/embed/job_app?for=a&token=123&token=123",
        "https://boards.greenhouse.io/embed/job_app?for=a&token=123%2F4",
        "https://boards.greenhouse.io/embed/job_app?for=a&token=",
        LEVER + "/unknown",
        ASHBY + "/application/other",
        WORKDAY.replace("_R123", ""),
        WORKDAY + "/unrecognized",
        "https://jobs.example.test/apply?gh_jid=123",
        "https://localhost/jobs/123",
        "https://127.0.0.1/jobs/123",
        "https://careers-synthetic.icims.com/jobs/not-a-number",
        "https://careers-synthetic.icims.com/jobs/123/..",
        GH + "\n",
        "https://job-boards.greenhouse.io/" + "a" * 201 + "/jobs/123",
        GH + "?" + "a" * 4100,
    ],
)
def test_unsupported_or_ambiguous_url_has_no_identity(url):
    assert posting_identity(url) is None


def test_observed_identity_is_bound_to_capture_and_canonical_contract():
    identity = posting_identity(GH)
    assert observed_identity("https://boards.greenhouse.io/embed/job_app", identity) == identity
    assert observed_identity("https://boards.greenhouse.io/%65mbed/job%5Fapp", identity) == identity
    with pytest.raises(ValueError, match="captured page"):
        observed_identity("https://boards.greenhouse.io/embed/job_app//", identity)
    with pytest.raises(ValueError, match="captured page"):
        observed_identity("https://jobs.example.test/apply", identity)
    with pytest.raises(ValueError, match="captured page"):
        observed_identity(GH.replace("/123", "/456"), identity)
    with pytest.raises(ValueError, match="canonical"):
        observed_identity(GH, {**identity, "canonical_url": GH + "?private=secret"})


def test_additive_identity_does_not_change_old_retry_payload():
    baseline = preparation_request_payload(PreparationCreate())
    assert "job_identity" not in baseline
    assert preparation_request_payload(PreparationCreate(job_identity=None)) == baseline
    assert preparation_request_payload(PreparationCreate(job_identity=posting_identity(GH)))[
        "job_identity"
    ] == posting_identity(GH)


@pytest.mark.parametrize(
    "url,suffix",
    [
        (LEVER, "/apply"),
        (ASHBY, "/application"),
        (WORKDAY, "/apply/autofillWithResume"),
        (ICIMS, "/engineer/job"),
    ],
)
def test_recognized_same_job_continues_without_new_page_confirmation(client, engine, url, suffix):
    initial, headers = shared_page(client)
    first_page = capture_page(client, initial, headers, url)
    first = prepare(client, first_page)
    assert first["job_identity"] == posting_identity(url)
    with Session(engine) as db:
        original_payload = deepcopy(db.get(ArtifactVersion, UUID(first["version_id"])).payload)
    second_page = capture_page(client, initial, headers, url + suffix)
    key = uuid4()
    body = {"continue_preparation_id": first["id"]}
    path = f"browser/device/snapshots/{second_page['id']}/preparations"
    second = post(client, path, body, headers=headers, key=key)
    assert second.status_code == 201, second.text
    assert post(client, path, body, headers=headers, key=key).json() == second.json()
    assert second.json()["task_id"] == first["task_id"]
    assert second.json()["job_identity"] == first["job_identity"]
    applications = client.get("/api/v1/applications").json()
    assert applications["total"] == 1
    assert applications["items"][0]["job_identity"] == first["job_identity"]
    assert applications["items"][0]["preparation_count"] == 2
    history = client.get(f"/api/v1/applications/{first['task_id']}/packages").json()["items"]
    assert history[0]["continuation_mode"] == "same_job"
    assert history[0]["job_identity"] == first["job_identity"]
    with Session(engine) as db:
        assert db.get(ArtifactVersion, UUID(first["version_id"])).payload == original_payload


@pytest.mark.parametrize("explicit", [False, True])
def test_different_job_cannot_join_even_with_explicit_confirmation(client, explicit):
    initial, headers = shared_page(client)
    first = prepare(client, capture_page(client, initial, headers, GH))
    different = capture_page(client, initial, headers, GH.replace("/123", "/456"))
    response = post(
        client,
        f"browser/snapshots/{different['id']}/preparations",
        {"continue_preparation_id": first["id"], "continue_on_new_page": explicit},
    )
    assert response.status_code == 409, response.text
    assert "different job" in response.json()["detail"]
    assert client.get("/api/v1/applications").json()["total"] == 1
    new = prepare(client, different)
    assert new["task_id"] != first["task_id"]


def test_query_identified_embeds_keep_safe_identity_and_reject_other_posting(client):
    initial, headers = shared_page(client)
    embed = capture_page(client, initial, headers, "https://boards.greenhouse.io/embed/job_app")
    first = prepare(client, embed, job_identity=posting_identity(GH))
    other = capture_page(client, initial, headers, embed["page_url"])
    changed = post(
        client,
        f"browser/snapshots/{other['id']}/preparations",
        {
            "continue_preparation_id": first["id"],
            "continue_on_new_page": True,
            "job_identity": posting_identity(GH.replace("/123", "/456")),
        },
    )
    assert changed.status_code == 409, changed.text
    assert first["job_identity"]["canonical_url"] == GH
    assert "?" not in first["job_identity"]["canonical_url"]


def test_unknown_confirmed_page_retains_identity_and_known_return_is_checked(client):
    initial, headers = shared_page(client)
    first = prepare(client, capture_page(client, initial, headers, GH))
    unknown = capture_page(client, initial, headers, "https://forms.example.test/experience")
    no_choice = post(
        client,
        f"browser/snapshots/{unknown['id']}/preparations",
        {"continue_preparation_id": first["id"]},
    )
    assert no_choice.status_code == 409
    middle = prepare(
        client, unknown, continue_preparation_id=first["id"], continue_on_new_page=True
    )
    assert middle["job_identity"] == first["job_identity"]
    returned = capture_page(client, initial, headers, GH.replace("/123", "/456"))
    wrong = post(
        client,
        f"browser/snapshots/{returned['id']}/preparations",
        {"continue_preparation_id": middle["id"], "continue_on_new_page": True},
    )
    assert wrong.status_code == 409


def test_identity_does_not_bypass_device_or_source_scope(client):
    initial, headers = shared_page(client)
    first = prepare(client, capture_page(client, initial, headers, LEVER))
    another_device, other_headers = shared_page(client)
    same_job = capture_page(client, another_device, other_headers, LEVER + "/apply")
    response = post(
        client,
        f"browser/device/snapshots/{same_job['id']}/preparations",
        {"continue_preparation_id": first["id"]},
        headers=other_headers,
    )
    assert response.status_code == 404
    wrong_source = post(
        client,
        f"browser/snapshots/{initial['id']}/preparations",
        {"job_identity": posting_identity(GH)},
    )
    assert wrong_source.status_code == 422, wrong_source.text
    invalid = post(
        client,
        f"browser/snapshots/{initial['id']}/preparations",
        {"job_identity": {**posting_identity(GH), "posting_id": "456"}},
    )
    assert invalid.status_code == 422
