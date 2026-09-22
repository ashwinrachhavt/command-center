from __future__ import annotations

import hashlib
import json
import math
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Nonempty = Annotated[str, Field(min_length=1, max_length=200)]
METRICS = ("grounding", "relevance", "completion")


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Evidence(Contract):
    id: Nonempty
    revision: Nonempty
    observed_at: datetime
    text: str = Field(min_length=1, max_length=12000)
    content_sha256: Digest

    @model_validator(mode="after")
    def exact_content(self) -> Evidence:
        if self.content_sha256 != hashlib.sha256(self.text.encode()).hexdigest():
            raise ValueError("Evidence content does not match its recorded digest")
        if self.observed_at.tzinfo is None:
            raise ValueError("Evidence observation requires a timezone")
        return self


class Case(Contract):
    id: Nonempty
    workflow: Literal["application", "outreach", "research"]
    platform: Literal["greenhouse", "lever", "ashby", "workday", "icims"] | None = None
    prompt: str = Field(min_length=1, max_length=12000)
    evidence: list[Evidence] = Field(min_length=1, max_length=10)
    expected_behavior: list[str] = Field(min_length=1, max_length=20)
    reference_output: str = Field(min_length=1, max_length=12000)

    def input_digest(self) -> str:
        return digest(self.model_dump(mode="json", exclude={"reference_output"}))


class Suite(Contract):
    schema_version: Literal[1]
    id: Nonempty
    revision: Nonempty
    classification: Literal["synthetic"]
    cases: list[Case] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def complete_matrix(self) -> Suite:
        if len({case.id for case in self.cases}) != len(self.cases):
            raise ValueError("Case IDs must be unique")
        if {case.workflow for case in self.cases} != {"application", "outreach", "research"}:
            raise ValueError("All three first-release workflows are required")
        platforms = {case.platform for case in self.cases if case.workflow == "application"}
        if platforms != {"greenhouse", "lever", "ashby", "workday", "icims"}:
            raise ValueError("All five application platforms are required")
        return self

    def fingerprint(self) -> str:
        return digest(self.model_dump(mode="json"))


class ModelIdentity(Contract):
    provider: Literal["openai", "gemini", "mistral", "cohere"]
    model: Nonempty


class Capture(Contract):
    case_id: Nonempty
    input_sha256: Digest
    actual_output: str = Field(min_length=1, max_length=24000)
    model: ModelIdentity
    prompt_sha256: Digest
    tools_sha256: Digest
    harness_revision: Nonempty
    source_revision: Nonempty
    elapsed_ms: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class Captures(Contract):
    schema_version: Literal[1]
    classification: Literal["synthetic"]
    origin: Literal["recorded_model", "reference_fixture"]
    suite_sha256: Digest
    cases: list[Capture] = Field(min_length=1, max_length=100)

    def bind(self, suite: Suite, *, require_model: bool = True) -> dict[str, Capture]:
        if require_model and self.origin != "recorded_model":
            raise ValueError("Reference fixtures cannot establish model quality")
        if self.suite_sha256 != suite.fingerprint():
            raise ValueError("Captures belong to a different fixture revision")
        indexed = {capture.case_id: capture for capture in self.cases}
        if len(indexed) != len(self.cases) or set(indexed) != {case.id for case in suite.cases}:
            raise ValueError("Captures must cover every case exactly once")
        for case in suite.cases:
            if indexed[case.id].input_sha256 != case.input_digest():
                raise ValueError(f"Capture input changed for {case.id}")
        return indexed


class Price(Contract):
    input_micro_usd_per_million: int = Field(gt=0)
    output_micro_usd_per_million: int = Field(gt=0)
    source_url: str = Field(pattern=r"^https://", max_length=1000)
    verified_at: datetime

    def cost(self, inputs: int, outputs: int) -> int:
        numerator = (
            inputs * self.input_micro_usd_per_million + outputs * self.output_micro_usd_per_million
        )
        return (numerator + 999_999) // 1_000_000


class Plan(Contract):
    schema_version: Literal[1]
    suite_sha256: Digest
    judge: ModelIdentity
    price: Price
    thresholds: dict[Literal["grounding", "relevance", "completion"], float]
    max_input_tokens: int = Field(ge=4096, le=200000)
    max_output_tokens: int = Field(ge=256, le=8000)
    max_calls: int = Field(ge=1, le=300)
    max_cost_micro_usd: int = Field(ge=0)

    @model_validator(mode="after")
    def explicit_thresholds(self) -> Plan:
        if set(self.thresholds) != set(METRICS):
            raise ValueError("Each metric requires an explicit threshold")
        if any(
            not math.isfinite(value) or not 0 < value <= 1 for value in self.thresholds.values()
        ):
            raise ValueError("Thresholds must be finite and in (0, 1]")
        if self.price.verified_at.tzinfo is None:
            raise ValueError("Pricing verification requires a timezone")
        return self

    def upper_bound(self) -> int:
        return self.max_calls * self.price.cost(self.max_input_tokens, self.max_output_tokens)

    def validate_run(self, suite: Suite, *, allow_paid: bool) -> None:
        if self.suite_sha256 != suite.fingerprint():
            raise ValueError("Plan belongs to a different fixture revision")
        if self.max_calls != len(suite.cases) * len(METRICS):
            raise ValueError("Plan must budget one call for every case and metric")
        if not allow_paid or self.max_cost_micro_usd <= 0:
            raise ValueError("A reviewed positive allowance and --allow-paid are required")
        if self.max_cost_micro_usd < self.upper_bound():
            raise ValueError("Allowance is below the conservative run bound")
        age = datetime.now(UTC) - self.price.verified_at
        if age.total_seconds() < -300 or age.days > 30:
            raise ValueError("Verify current pricing before running this plan")


class AllowanceExceeded(RuntimeError):
    pass


class RunReport:
    """A fresh private report per attempt; reservations are saved before provider I/O."""

    def __init__(self, parent: Path, metadata: dict[str, Any]):
        self.directory = parent / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid4().hex}"
        self.directory.mkdir(parents=True, mode=0o700)
        self.path = self.directory / "report.json"
        self.lock = threading.RLock()
        self.data: dict[str, Any] = {**metadata, "calls": [], "results": []}
        self.save()

    def save(self) -> None:
        with self.lock:
            temporary = self.directory / "report.tmp"
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, "w") as stream:
                json.dump(self.data, stream, indent=2, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.path)

    def result(self, result: dict[str, Any]) -> None:
        with self.lock:
            self.data["results"].append(result)
            self.save()


class Allowance:
    def __init__(self, plan: Plan, report: RunReport):
        self.plan, self.report = plan, report

    def reserve(self, input_bound: int, case_id: str, metric: str) -> str:
        with self.report.lock:
            calls = self.report.data["calls"]
            if any(call["state"] == "bound_exceeded" for call in calls):
                raise AllowanceExceeded("A provider exceeded its bound; review before another call")
            if (
                input_bound < 0
                or input_bound > self.plan.max_input_tokens
                or len(calls) >= self.plan.max_calls
            ):
                raise AllowanceExceeded("Judge input or call allowance exceeded")
            reserved = self.plan.price.cost(input_bound, self.plan.max_output_tokens)
            if (
                sum(call["charged_micro_usd"] for call in calls) + reserved
                > self.plan.max_cost_micro_usd
            ):
                raise AllowanceExceeded("Judge spending allowance exceeded")
            identity = uuid4().hex
            calls.append(
                {
                    "id": identity,
                    "case_id": case_id,
                    "metric": metric,
                    "state": "reserved",
                    "input_bound": input_bound,
                    "output_bound": self.plan.max_output_tokens,
                    "reserved_micro_usd": reserved,
                    "charged_micro_usd": reserved,
                }
            )
            self.report.save()
            return identity

    def finish(self, identity: str, usage: dict[str, Any] | None, elapsed_ms: int) -> None:
        with self.report.lock:
            call = next(item for item in self.report.data["calls"] if item["id"] == identity)
            if call["state"] != "reserved":
                raise ValueError("A judge attempt can only be settled once")
            call["elapsed_ms"] = elapsed_ms
            if (
                usage
                and all(
                    type(usage.get(key)) is int and usage[key] >= 0
                    for key in ("input_tokens", "output_tokens")
                )
                and usage["input_tokens"] + usage["output_tokens"] > 0
            ):
                call.update(state="settled", usage=usage)
                call["charged_micro_usd"] = self.plan.price.cost(
                    usage["input_tokens"], usage["output_tokens"]
                )
                exceeded = (
                    usage["input_tokens"] > call["input_bound"]
                    or usage["output_tokens"] > call["output_bound"]
                )
                if exceeded:
                    call["state"] = "bound_exceeded"
            else:
                call["state"] = "usage_unknown"
                exceeded = False
            self.report.save()
            if exceeded:
                raise AllowanceExceeded("Provider usage exceeded the configured local bound")
