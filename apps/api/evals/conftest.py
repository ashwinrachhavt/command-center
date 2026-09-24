from __future__ import annotations

import os
import subprocess
from importlib.metadata import version
from pathlib import Path

import pytest

from .contracts import Allowance, Captures, Plan, RunReport
from .dataset import load_suite
from .environment import configure_local_evaluation

configure_local_evaluation()
ROOT = Path(__file__).resolve().parents[3]


def pytest_addoption(parser):
    parser.addoption("--eval-plan", help="Reviewed judge configuration and per-run allowance")
    parser.addoption("--eval-captures", help="Versioned synthetic outputs from actual model runs")
    parser.addoption("--allow-paid", action="store_true", help="Explicitly enable paid judge calls")
    parser.addoption(
        "--langfuse", action="store_true", help="Publish synthetic results to Langfuse"
    )


@pytest.fixture(scope="session")
def quality_run(pytestconfig):
    from command_center.agents.config import AgentProfile
    from command_center.agents.models import create_chat_model
    from command_center.core.config import Settings

    from .judge import RUBRICS

    plan_path = pytestconfig.getoption("--eval-plan")
    captures_path = pytestconfig.getoption("--eval-captures")
    if not plan_path or not captures_path:
        raise pytest.UsageError("Quality evaluation requires --eval-plan and --eval-captures")
    if os.getenv("PYTEST_XDIST_WORKER") or pytestconfig.getoption("numprocesses", default=None):
        raise pytest.UsageError("Paid quality runs use one process and one shared allowance")
    suite = load_suite()
    plan = Plan.model_validate_json(Path(plan_path).read_text())
    captures = Captures.model_validate_json(Path(captures_path).read_text())
    try:
        plan.validate_run(suite, allow_paid=pytestconfig.getoption("--allow-paid"))
        indexed = captures.bind(suite)
    except ValueError as error:
        raise pytest.UsageError(str(error)) from error
    report = RunReport(
        ROOT / ".local" / "evals",
        {
            "suite": suite.model_dump(mode="json"),
            "captures": captures.model_dump(mode="json"),
            "plan": plan.model_dump(mode="json"),
            "deepeval_version": version("deepeval"),
            "rubrics": RUBRICS,
            "state": "checking_correctness",
            "quality_scope": (
                "Recorded synthetic model outputs; no live provider or browser coverage"
            ),
        },
    )
    gate_environment = dict(os.environ)
    gate_environment.pop("UV_PROJECT_ENVIRONMENT", None)
    gate_environment.pop("PYTEST_DISABLE_PLUGIN_AUTOLOAD", None)
    try:
        descriptor = os.open(report.directory / "correctness.log", os.O_CREAT | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w") as log:
            gate = subprocess.run(
                ["make", "check"],
                cwd=ROOT,
                env=gate_environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=1200,
                check=False,
            )
    except (OSError, subprocess.TimeoutExpired) as error:
        report.data.update(state="correctness_error", error_type=type(error).__name__)
        report.save()
        pytest.fail(f"Correctness gates unavailable before any judge call; report: {report.path}")
    report.data["correctness_exit_code"] = gate.returncode
    if gate.returncode:
        report.data["state"] = "correctness_failed"
        report.save()
        pytest.fail(f"Correctness gates failed before any judge call; report: {report.path}")
    profile = AgentProfile(
        name="Evaluation judge",
        description="Explicitly budgeted synthetic-output evaluation",
        provider=plan.judge.provider,
        model=plan.judge.model,
        instructions="",
        max_output_tokens=plan.max_output_tokens,
    )
    try:
        model = create_chat_model(Settings(), profile)
    except Exception as error:
        report.data.update(state="evaluator_error", error_type=type(error).__name__)
        report.save()
        pytest.fail(f"Judge setup failed before any judge call; report: {report.path}")
    report.data["state"] = "evaluating"
    report.save()
    yield plan, indexed, model, Allowance(plan, report), report
    states = {result["state"] for result in report.data["results"]}
    report.data["state"] = (
        "evaluator_error"
        if "evaluator_error" in states
        else "quality_failed"
        if "quality_failed" in states
        else "passed"
        if len(report.data["results"]) == plan.max_calls
        else "incomplete"
    )
    report.save()
    if pytestconfig.getoption("--langfuse"):
        from command_center.agents.telemetry import langfuse_client

        from .langfuse_report import publish_report

        client = langfuse_client(Settings())
        if client is None:
            pytest.fail("Langfuse is not configured; the local report was preserved")
        publish_report(report, client)
    print(f"\nLocal evaluation report: {report.path}")
