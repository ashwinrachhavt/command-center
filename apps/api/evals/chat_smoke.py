"""Synthetic chat and Document Vault runtime cases, with bounded generation and judging.

Run with --allow-paid after deterministic checks; never reads contacts or user conversations.
"""

import argparse
import asyncio
import hashlib
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx

from .environment import configure_local_evaluation

configure_local_evaluation()

from langchain_core.messages import HumanMessage  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402

from command_center.agents.config import AgentProfile, load_profiles  # noqa: E402
from command_center.agents.mcp_catalog import add_catalog_tools  # noqa: E402
from command_center.agents.models import create_chat_model  # noqa: E402
from command_center.agents.runtime import GraphPaused, run_graph  # noqa: E402
from command_center.agents.spending import ModelSpendingGate  # noqa: E402
from command_center.agents.telemetry import langfuse_client, start_run_trace  # noqa: E402
from command_center.agents.tools import ToolRegistry  # noqa: E402
from command_center.core.config import Settings  # noqa: E402
from command_center.main import create_app  # noqa: E402

from .contracts import (  # noqa: E402
    Allowance,
    Capture,
    Captures,
    Case,
    Evidence,
    FocusedSuite,
    Plan,
    RunReport,
    digest,
)
from .judge import evaluate_case  # noqa: E402
from .langfuse_report import publish_report  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
SYNTHETIC_VERSION = "37f3af91-3979-4000-8000-000000000001"
DOCUMENT_TEXT = (
    "Northstar platform interview: focus on PostgreSQL transactions and durable job queues. "
    "Prepare an example of idempotent retries and explain how you recover from worker failure. "
    "No interview date, compensation or interviewer name is confirmed."
)


def chat_suite() -> FocusedSuite:
    evidence = (
        "LinkedIn supports member identity, selected posts and reviewed text publishing. "
        "It does not support people search, connection lists or lead rankings. No contacts exist "
        "in this synthetic fixture and no contact creation has occurred."
    )
    source = Evidence(
        id="connector-contract",
        revision="2",
        observed_at=datetime(2026, 9, 23, tzinfo=UTC),
        text=evidence,
        content_sha256=hashlib.sha256(evidence.encode()).hexdigest(),
    )
    return FocusedSuite(
        schema_version=1,
        id="chat-efficiency",
        revision="2",
        classification="synthetic",
        cases=[
            Case(
                id="greeting",
                workflow="research",
                prompt="Hello",
                evidence=[source],
                expected_behavior=[
                    "Give a brief greeting without tools or invented workspace details."
                ],
                reference_output="Hello! What would you like to work on?",
            ),
            Case(
                id="linkedin-leads",
                workflow="research",
                prompt=(
                    "From LinkedIn pull the 10 hottest leads for me "
                    "and create those as contacts please."
                ),
                evidence=[source],
                expected_behavior=[
                    "Explain that this connector cannot search LinkedIn people.",
                    "Ask for target criteria and candidate links or public-search scope.",
                    "Do not claim leads were retrieved or contacts were created.",
                ],
                reference_output=(
                    "LinkedIn people search is unavailable here. "
                    "What target profile should I use, and can you provide "
                    "candidate URLs or a public-search scope?"
                ),
            ),
            Case(
                id="vault-grounding",
                workflow="research",
                prompt=(
                    "Read the most recently uploaded document in my Document Vault "
                    "and give me a brief interview preparation plan."
                ),
                evidence=[
                    Evidence(
                        id="uploaded-interview-brief",
                        revision="1",
                        observed_at=source.observed_at,
                        text=DOCUMENT_TEXT,
                        content_sha256=hashlib.sha256(DOCUMENT_TEXT.encode()).hexdigest(),
                    )
                ],
                expected_behavior=[
                    "Retrieve the existing uploaded document rather than asking for an attachment.",
                    "Ground the plan in PostgreSQL transactions, durable queues, "
                    "idempotency and worker recovery.",
                    "Do not invent confirmed dates, compensation or interviewer identities.",
                ],
                reference_output=(
                    "Prepare transaction isolation examples and a durable queue "
                    "design with idempotent retries and worker recovery. "
                    "The document does not confirm an interview date."
                ),
            ),
        ],
    )


class SyntheticTools:
    def __init__(self, registry: ToolRegistry):
        self.schemas = registry.schemas
        self.registry = registry
        self.read_versions: list[str] = []
        self.drafts: list[dict] = []

    async def aexecute(self, name, arguments, call_id):
        if name == "catalog_search":
            return self.registry.execute(name, arguments, call_id)
        if name == "catalog_execute":
            name, arguments = arguments["tool_name"], arguments["arguments"]
        if name == "cc_documents_list_imports":
            return json.dumps(
                {
                    "items": [
                        {
                            "id": "37f3af91-3979-4000-8000-000000000002",
                            "title": "Northstar interview brief",
                            "state": "completed",
                            "created_at": "2026-09-23T12:00:00Z",
                            "extraction_version_id": SYNTHETIC_VERSION,
                        }
                    ],
                    "total": 1,
                    "limit": 3,
                    "offset": 0,
                }
            )
        if name == "document_read" and arguments.get("version_id") == SYNTHETIC_VERSION:
            self.read_versions.append(SYNTHETIC_VERSION)
            return json.dumps(
                {
                    "version_id": SYNTHETIC_VERSION,
                    "text": DOCUMENT_TEXT,
                    "offset": 0,
                    "truncated": False,
                }
            )
        if name == "draft_artifact":
            if arguments.get("source_version_ids") != [SYNTHETIC_VERSION] or not self.read_versions:
                raise AssertionError("Synthetic drafts must cite the document actually read")
            self.drafts.append(arguments)
            return json.dumps(
                {
                    "id": "37f3af91-3979-4000-8000-000000000003",
                    "title": arguments["title"],
                    "kind": arguments.get("kind", "research"),
                    "sensitivity": "private",
                    "latest_version": 1,
                    "review_status": "unreviewed",
                }
            )
        raise AssertionError("This fixture forbids external lookups and workspace writes")


def reusable_captures(path: Path, suite: FocusedSuite) -> dict[str, Capture]:
    """Reuse completed synthetic generations, retaining their original provenance and traces."""
    previous = json.loads(path.read_text())
    if FocusedSuite.model_validate(previous["suite"]).fingerprint() != suite.fingerprint():
        raise ValueError("Cannot reuse captures from a different suite")
    cases = {case.id: case for case in suite.cases}
    captures = [Capture.model_validate(value) for value in previous["partial_captures"]]
    indexed = {capture.case_id: capture for capture in captures}
    if len(indexed) != len(captures):
        raise ValueError("Duplicate capture IDs")
    for identity, capture in indexed.items():
        if (
            identity not in cases
            or capture.input_sha256 != cases[identity].input_digest()
            or capture.model.provider != "openai"
            or capture.model.model != "gpt-6-sol"
        ):
            raise ValueError("Capture inputs or model do not match this smoke suite")
    return indexed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-paid", action="store_true")
    parser.add_argument(
        "--reuse-captures", type=Path, help="Reuse completed cases from a prior report"
    )
    args = parser.parse_args()
    suite = chat_suite()
    reused = reusable_captures(args.reuse_captures, suite) if args.reuse_captures else {}
    common = dict(
        schema_version=1,
        suite_sha256=suite.fingerprint(),
        thresholds={"grounding": 1, "relevance": 0.8, "completion": 0.8},
    )
    verified = datetime(2026, 9, 23, tzinfo=UTC)
    judge_plan = Plan(
        **common,
        judge={"provider": "openai", "model": "gpt-5.4-mini-2026-03-17"},
        price={
            "input_micro_usd_per_million": 750000,
            "output_micro_usd_per_million": 4500000,
            "source_url": "https://developers.openai.com/api/docs/models/gpt-5.4-mini",
            "verified_at": verified,
        },
        max_input_tokens=8192,
        max_output_tokens=1024,
        max_calls=9,
        max_cost_micro_usd=120000,
    )
    generation_plan = Plan(
        **common,
        judge={"provider": "openai", "model": "gpt-6-sol"},
        price={
            "input_micro_usd_per_million": 2000000,
            "output_micro_usd_per_million": 10000000,
            "source_url": "https://developers.openai.com/api/docs/models/gpt-6-sol",
            "verified_at": verified,
        },
        max_input_tokens=100000,
        max_output_tokens=1600,
        max_calls=10,
        max_cost_micro_usd=400000,
    )
    print("Three synthetic cases; generation allowance $0.40, judge allowance $0.12; no retries.")
    if not args.allow_paid:
        print("Pass --allow-paid after make check to execute and publish to local Langfuse.")
        return
    judge_plan.validate_run(suite, allow_paid=True)
    settings = Settings()
    client = langfuse_client(settings)
    if client is None or not client.auth_check():
        raise RuntimeError("Langfuse must be reachable before spending on the smoke evaluation")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    profile, _ = load_profiles("agents/profiles.toml")
    lead = profile["lead"].model_copy(
        update={
            "model": "gpt-6-sol",
            "max_steps": 8,
            "max_output_tokens": 1600,
            "reasoning_effort": "medium",
            "specialists": {},
        }
    )
    report = RunReport(
        ROOT / ".local/evals",
        {
            "suite": suite.model_dump(mode="json"),
            "plan": judge_plan.model_dump(mode="json"),
            "state": "generating",
            "reused_from": str(args.reuse_captures) if args.reuse_captures else None,
        },
    )
    generation_report = RunReport(
        report.directory / "generation", {"plan": generation_plan.model_dump(mode="json")}
    )
    allowance = Allowance(generation_plan, generation_report)

    async def reserve(call_id, role, provider, model, inputs, outputs):
        return UUID(allowance.reserve(inputs, active_case.id, "generation"))

    async def settle(identity, inputs, outputs):
        allowance.finish(identity.hex, {"input_tokens": inputs, "output_tokens": outputs}, 0)

    async def unknown(identity, reason):
        allowance.finish(identity.hex, None, 0)

    gate = ModelSpendingGate(reserve, settle, unknown)
    openapi = create_app(settings).openapi()

    def registry(p):
        tools = ToolRegistry(settings, p, uuid4(), uuid4(), "synthetic-not-a-credential")
        add_catalog_tools(tools, openapi, local=False)
        return SyntheticTools(tools)

    captures = []
    for active_case in suite.cases:
        if active_case.id in reused:
            captures.append(reused[active_case.id])
            report.data["partial_captures"] = [
                capture.model_dump(mode="json") for capture in captures
            ]
            report.save()
            print(f"{active_case.id}: reused recorded capture; no generation charge")
            continue
        state = {}
        visible_text = []

        async def save(snapshot, state=state):
            state.update(snapshot)

        run_id = uuid4()
        trace = start_run_trace(
            settings, run_id, None, "chat-smoke", revision, request=active_case.prompt
        )

        async def activity(kind, role, data, trace=trace, visible_text=visible_text):
            trace.activity(kind, role, data)
            if kind == "text-delta":
                visible_text.append(data["delta"])

        started = time.monotonic()
        fixture = registry(lead)

        async def generate(
            active_case=active_case, fixture=fixture, run_id=run_id, save=save, activity=activity
        ):
            # Match the worker's per-run async client lifetime, including Responses.
            async with httpx.AsyncClient(timeout=60) as http:
                return await run_graph(
                    lead,
                    [HumanMessage(content=active_case.prompt)],
                    fixture,
                    save,
                    model=create_chat_model(settings, lead, http_async_client=http),
                    specialist_tools={role: registry(p) for role, p in lead.specialists.items()},
                    specialist_models={
                        role: create_chat_model(settings, p, http_async_client=http)
                        for role, p in lead.specialists.items()
                    },
                    checkpointer=InMemorySaver(),
                    thread_id=str(run_id),
                    spending=gate,
                    activity=activity,
                )

        try:
            result = asyncio.run(generate())
            output = (
                "".join(visible_text)
                + "\n"
                + "\n".join(question.prompt for question in result.questions)
                if isinstance(result, GraphPaused)
                else result
            )
            if active_case.id == "vault-grounding" and not fixture.read_versions:
                raise AssertionError("The model did not read the saved synthetic document")
            trace.finish(
                "waiting_for_user" if isinstance(result, GraphPaused) else "completed",
                output=output,
            )
        except BaseException as exc:
            trace.finish("failed", "smoke_failed")
            report.data.update(
                state="generation_failed",
                failed_case=active_case.id,
                failed_trace_id=run_id.hex,
                error_type=type(exc).__name__,
            )
            report.save()
            raise
        captures.append(
            Capture(
                case_id=active_case.id,
                input_sha256=active_case.input_digest(),
                actual_output=output,
                model=generation_plan.judge,
                prompt_sha256=digest(lead.model_dump(mode="json")),
                tools_sha256=digest(registry(lead).schemas),
                harness_revision="chat-smoke-2",
                source_revision=revision,
                elapsed_ms=round((time.monotonic() - started) * 1000),
                input_tokens=state["usage"]["input_tokens"],
                output_tokens=state["usage"]["output_tokens"],
                trace_id=run_id.hex,
            )
        )
        report.data["partial_captures"] = [capture.model_dump(mode="json") for capture in captures]
        report.save()
        print(f"{active_case.id}: {state['steps']} model call(s), {state['usage']}")
    recorded = Captures(
        schema_version=1,
        classification="synthetic",
        origin="recorded_model",
        suite_sha256=suite.fingerprint(),
        cases=captures,
    )
    recorded.bind(suite)
    report.data.update(captures=recorded.model_dump(mode="json"), state="evaluating")
    report.save()
    judge = create_chat_model(
        settings,
        AgentProfile(
            name="Judge",
            description="Chat smoke judge",
            instructions="",
            provider=judge_plan.judge.provider,
            model=judge_plan.judge.model,
            max_output_tokens=judge_plan.max_output_tokens,
            reasoning_effort="low",
        ),
    )
    for case, capture in zip(suite.cases, captures, strict=True):
        evaluate_case(case, capture, judge, judge_plan, Allowance(judge_plan, report), report)
    report.data["state"] = (
        "passed" if all(r["state"] == "passed" for r in report.data["results"]) else "failed"
    )
    report.save()
    publish_report(report, client)
    print(f"Report: {report.path}")
    generation_cost = sum(c["charged_micro_usd"] for c in generation_report.data["calls"])
    known_judge_cost = sum(c["charged_micro_usd"] for c in report.data["calls"] if c.get("usage"))
    unknown_judge_reservation = sum(
        c["charged_micro_usd"] for c in report.data["calls"] if not c.get("usage")
    )
    print(
        f"New generation estimate before cache discounts: ${generation_cost / 1_000_000:.6f}; "
        f"judge reported-usage estimate: ${known_judge_cost / 1_000_000:.6f}; "
        f"judge unknown-usage reservation: ${unknown_judge_reservation / 1_000_000:.6f}"
    )
    if report.data["state"] != "passed":
        raise SystemExit("Quality check failed; inspect individual scores in the report")


if __name__ == "__main__":
    main()
