import asyncio
import json
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from pydantic import ValidationError

from .contracts import Allowance, AllowanceExceeded, Captures, Plan, RunReport
from .dataset import load_suite, reference_captures
from .judge import BoundedJudge, EvaluatorError, evaluate_case


@pytest.fixture(autouse=True)
def no_network(mocker):
    mocker.patch.object(socket.socket, "connect", side_effect=AssertionError("Offline eval check"))


@pytest.fixture
def plan():
    return Plan.model_validate(
        {
            "schema_version": 1,
            "suite_sha256": load_suite().fingerprint(),
            "judge": {"provider": "openai", "model": "synthetic-judge"},
            "price": {
                "input_micro_usd_per_million": 250000,
                "output_micro_usd_per_million": 2000000,
                "source_url": "https://fixtures.example/pricing",
                "verified_at": datetime.now(UTC),
            },
            "thresholds": {"grounding": 1, "relevance": 0.8, "completion": 0.8},
            "max_input_tokens": 32768,
            "max_output_tokens": 2048,
            "max_calls": 21,
            "max_cost_micro_usd": 300000,
        }
    )


def report(tmp_path):
    return RunReport(tmp_path, {"origin": "offline_adapter_check"})


class OfflineJudge(BaseChatModel):
    score: int = 10
    fail: bool = False
    missing_usage: bool = False

    @property
    def _llm_type(self):
        return "offline-judge"

    def _generate(self, *args, **kwargs):
        raise AssertionError("This fixture only supports schema-bound evaluation")

    def with_structured_output(self, schema, **kwargs):
        async def answer(_messages):
            if self.fail:
                raise TypeError("Synthetic provider failure")
            usage = (
                None
                if self.missing_usage
                else {
                    "input_tokens": 100,
                    "output_tokens": 30,
                    "total_tokens": 130,
                }
            )
            return {
                "raw": AIMessage(content="synthetic score", usage_metadata=usage),
                "parsed": schema(score=self.score, reason="Synthetic adapter response"),
                "parsing_error": None,
            }

        return RunnableLambda(answer)


def test_suite_requires_all_workflows_and_platforms():
    suite = load_suite()
    assert len(suite.cases) == 7
    invalid = suite.model_dump(mode="json")
    invalid["cases"] = invalid["cases"][1:]
    with pytest.raises(ValidationError, match="five application"):
        type(suite).model_validate(invalid)


def test_reference_outputs_and_stale_or_incomplete_captures_are_rejected():
    suite = load_suite()
    captures = reference_captures(suite)
    with pytest.raises(ValueError, match="cannot establish model quality"):
        captures.bind(suite)
    data = captures.model_dump(mode="json")
    data["origin"] = "recorded_model"
    assert len(Captures.model_validate(data).bind(suite)) == 7
    data["cases"][0]["input_sha256"] = "1" * 64
    with pytest.raises(ValueError, match="Capture input changed"):
        Captures.model_validate(data).bind(suite)
    data["cases"].pop()
    with pytest.raises(ValueError, match="every case exactly once"):
        Captures.model_validate(data).bind(suite)


def test_spending_requires_explicit_opt_in_prices_and_sufficient_allowance(plan):
    with pytest.raises(ValueError, match="allow-paid"):
        plan.validate_run(load_suite(), allow_paid=False)
    plan.validate_run(load_suite(), allow_paid=True)
    assert plan.upper_bound() == 258048
    for changes in ({"max_cost_micro_usd": 0}, {"max_cost_micro_usd": 1}, {"max_calls": 20}):
        with pytest.raises(ValueError):
            plan.model_copy(update=changes).validate_run(load_suite(), allow_paid=True)


def test_unknown_usage_retains_reservation_and_attempts_are_bounded(plan, tmp_path):
    plan = plan.model_copy(update={"max_calls": 1})
    saved = report(tmp_path)
    allowance = Allowance(plan, saved)
    identity = allowance.reserve(5000, "case", "grounding")
    assert json.loads(saved.path.read_text())["calls"][0]["state"] == "reserved"
    allowance.finish(identity, None, 10)
    call = saved.data["calls"][0]
    assert call["charged_micro_usd"] == call["reserved_micro_usd"]
    assert call["state"] == "usage_unknown"
    with pytest.raises(AllowanceExceeded):
        allowance.reserve(5000, "case", "relevance")


def test_concurrent_reservations_cannot_overdraw(plan, tmp_path):
    plan = plan.model_copy(update={"max_cost_micro_usd": plan.price.cost(5000, 2048)})
    allowance = Allowance(plan, report(tmp_path))

    def attempt(_):
        try:
            allowance.reserve(5000, "case", "grounding")
            return True
        except AllowanceExceeded:
            return False

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(attempt, range(8))) == 1


@pytest.mark.parametrize("score,expected", [(10, "passed"), (2, "quality_failed")])
def test_real_deepeval_metrics_record_per_case_scores(plan, tmp_path, score, expected):
    suite = load_suite()
    case = suite.cases[0]
    saved = report(tmp_path)
    result = evaluate_case(
        case,
        reference_captures(suite).cases[0],
        OfflineJudge(score=score),
        plan,
        Allowance(plan, saved),
        saved,
    )
    assert [item["state"] for item in result] == [expected] * 3
    assert len(saved.data["calls"]) == 3
    assert all(call["state"] == "settled" for call in saved.data["calls"])
    assert saved.path.stat().st_mode & 0o777 == 0o600


def test_provider_error_is_not_a_quality_failure_or_hidden_retry(plan, tmp_path):
    saved = report(tmp_path)
    judge = BoundedJudge(OfflineJudge(fail=True), Allowance(plan, saved), "case", "grounding")
    from pydantic import BaseModel

    class Score(BaseModel):
        score: int
        reason: str

    with pytest.raises(EvaluatorError, match="TypeError"):
        asyncio.run(judge.a_generate("Judge synthetic content", Score))
    assert len(saved.data["calls"]) == 1
    assert saved.data["calls"][0]["state"] == "usage_unknown"


def test_bound_exceedance_blocks_further_calls_and_reports_usage(plan, tmp_path):
    saved = report(tmp_path)
    allowance = Allowance(plan, saved)
    identity = allowance.reserve(5000, "case", "grounding")
    with pytest.raises(AllowanceExceeded, match="Provider usage"):
        allowance.finish(identity, {"input_tokens": 6000, "output_tokens": 10}, 10)
    assert saved.data["calls"][0]["state"] == "bound_exceeded"
    with pytest.raises(AllowanceExceeded, match="review before"):
        allowance.reserve(5000, "case", "relevance")


def test_reports_never_overwrite_prior_attempts(tmp_path):
    first, second = report(tmp_path), report(tmp_path)
    assert first.path != second.path
    assert first.path.exists() and second.path.exists()


def test_deepeval_reports_provider_errors_separately(plan, tmp_path):
    suite = load_suite()
    saved = report(tmp_path)
    results = evaluate_case(
        suite.cases[0],
        reference_captures(suite).cases[0],
        OfflineJudge(fail=True),
        plan,
        Allowance(plan, saved),
        saved,
    )
    assert all(item["state"] == "evaluator_error" and "score" not in item for item in results)
    assert len(saved.data["calls"]) == 3
    assert all(call["state"] == "usage_unknown" for call in saved.data["calls"])


@pytest.mark.parametrize("failure", ["checks_failed", "timeout", "unavailable", "judge_setup"])
def test_failed_setup_preserves_report_without_paid_calls(plan, tmp_path, mocker, failure):
    from types import SimpleNamespace

    from command_center.core.config import Settings

    from . import conftest

    captures = reference_captures(load_suite()).model_dump(mode="json")
    captures["origin"] = "recorded_model"
    plan_path, capture_path = tmp_path / "plan.json", tmp_path / "captures.json"
    plan_path.write_text(plan.model_dump_json())
    capture_path.write_text(json.dumps(captures))
    options = {
        "--eval-plan": str(plan_path),
        "--eval-captures": str(capture_path),
        "--allow-paid": True,
    }
    config = SimpleNamespace(getoption=lambda key, default=None: options.get(key, default))
    mocker.patch.object(conftest, "ROOT", tmp_path)
    gate = mocker.patch.object(
        conftest.subprocess,
        "run",
        return_value=SimpleNamespace(returncode=1 if failure == "checks_failed" else 0),
    )
    if failure == "timeout":
        gate.side_effect = subprocess.TimeoutExpired(["make", "check"], 1200)
    elif failure == "unavailable":
        gate.side_effect = FileNotFoundError("Synthetic missing runner")
    factory = mocker.patch("command_center.agents.models.create_chat_model")
    factory.side_effect = ValueError("Synthetic missing credentials")
    mocker.patch(
        "command_center.core.config.Settings",
        return_value=Settings(
            _env_file=None,
            api_token="synthetic-evaluation-token-with-at-least-32-characters",
            database_url="postgresql+psycopg://test:test-only@database.example.test/command_center_test",
        ),
    )
    with pytest.raises(pytest.fail.Exception, match="before any judge call"):
        next(conftest.quality_run.__wrapped__(config))
    if failure == "judge_setup":
        factory.assert_called_once()
    else:
        factory.assert_not_called()
    saved = json.loads(next((tmp_path / ".local" / "evals").glob("*/report.json")).read_text())
    expected_state = {
        "checks_failed": "correctness_failed",
        "timeout": "correctness_error",
        "unavailable": "correctness_error",
        "judge_setup": "evaluator_error",
    }[failure]
    assert saved["state"] == expected_state and saved["calls"] == []
