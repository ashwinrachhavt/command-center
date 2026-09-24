"""Offline contract checks for matched runtime reporting and live spending gates."""

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

pytest.importorskip("strands_harness")
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from apps.api.evals import runtime_benchmark as benchmark  # noqa: E402
from apps.api.evals.contracts import Price, RunReport  # noqa: E402

from command_center.db.spending import SpendingDenied  # noqa: E402


def price() -> Price:
    return Price(
        input_micro_usd_per_million=1_000_000,
        output_micro_usd_per_million=2_000_000,
        source_url="https://example.test/current-prices",
        verified_at=datetime.now(UTC),
    )


def test_offline_report_covers_matched_cases_and_alternates_order(tmp_path):
    path = benchmark.main(
        [
            "--mode",
            "offline",
            "--repeats",
            "2",
            "--reasoning-effort",
            "medium",
            "--max-calls-per-run",
            "4",
            "--max-output-tokens",
            "768",
            "--report-dir",
            str(tmp_path),
        ]
    )
    report = json.loads(path.read_text())
    rows = report["results"]
    assert report["measurement"] == "scripted_offline"
    assert report["reasoning_effort"] == "medium"
    assert report["max_calls_per_run"] == 4
    assert report["max_output_tokens"] == 768
    assert report["order"] == [["deepagents", "strands"], ["strands", "deepagents"]]
    assert len(rows) == 12
    assert {(row["case_id"], row["runtime"], row["repeat"]) for row in rows} == {
        (case.id, runtime, repeat)
        for case in benchmark.cases()
        for repeat in range(2)
        for runtime in benchmark.order_for(repeat)
    }
    assert all(row["completion_check"]["passed"] for row in rows)
    assert all(row["model_calls"] == 2 and row["tool_calls"] == 1 for row in rows)
    assert all(row["model_attempts"] == 2 and row["reserved_model_calls"] is None for row in rows)
    assert all(row["input_tokens"] == 90 and row["output_tokens"] == 20 for row in rows)
    assert all(row["total_tokens"] == 110 for row in rows)
    assert all(row["cached_input_tokens"] == 10 and row["retries"] == 0 for row in rows)
    assert all(row["token_basis"] == "scripted_fixture" for row in rows)
    assert all(row["estimated_cost_micro_usd"] is None for row in rows)
    assert all(row["cost_estimate_basis"] is None for row in rows)
    assert all(row["charged_micro_usd"] is None for row in rows)
    assert all(row["time_to_first_text_ms"] is not None for row in rows)
    assert all(row["time_to_first_tool_ms"] is not None for row in rows)
    assert all(row["first_tool_latency_ms"] is not None for row in rows)
    assert all(row["duration_ms"] >= 0 for row in rows)
    assert all(len(row["case_sha256"]) == 64 for row in rows)
    assert all(len(row["config_sha256"]) == 64 for row in rows)
    assert all(len(row["source_sha256"]) == 64 for row in rows)
    assert all(len(row["output_sha256"]) == 64 for row in rows)
    for case in benchmark.cases():
        assert len({row["config_sha256"] for row in rows if row["case_id"] == case.id}) == 1
    assert report["synthetic_tokens_are_not_savings"] is True
    assert len(report["comparison_config_sha256"]) == 64
    assert all(len(value) == 64 for value in report["source_hashes"].values())
    assert report["aggregates"]["by_runtime"]["deepagents"]["completed"] == 6
    assert report["aggregates"]["by_runtime"]["strands"]["completed"] == 6
    assert all(
        row["attempted"] == row["completed"] == 2
        and row["duration_ms"]["p50"] is not None
        and row["duration_ms"]["p95"] is not None
        and row["time_to_first_text_ms"]["p50"] is not None
        for row in report["aggregates"]["by_case_runtime"]
    )
    selected = benchmark.profile_for(
        benchmark.cases()[0],
        "openai",
        "gpt-5-mini",
        reasoning_effort="medium",
        max_calls_per_run=4,
        max_output_tokens=768,
    )
    assert (selected.reasoning_effort, selected.max_steps, selected.max_output_tokens) == (
        "medium",
        4,
        768,
    )
    assert (
        benchmark.cases()[0].response["items"][0]["version_id"]
        != benchmark.cases()[2].arguments["version_id"]
    )


def test_extra_tool_call_fails_exact_completion_even_with_expected_answer(mocker):
    case = benchmark.cases()[0]

    async def extra_call(profile, prompt, tools, checkpoint, **kwargs):
        await tools.aexecute(case.tool_name, case.arguments, "expected")
        await tools.aexecute("document_read", {"version_id": benchmark.SOURCE_VERSION}, "extra")
        await checkpoint({"steps": 1, "usage": {}, "tools": []})
        return case.expected_output

    mocker.patch.object(benchmark, "run_graph", side_effect=extra_call)
    row = asyncio.run(
        benchmark.run_case(
            case,
            "deepagents",
            0,
            mode="offline",
            provider="openai",
            model_name="gpt-5-mini",
            reasoning_effort=None,
            max_calls_per_run=6,
            max_output_tokens=512,
            price=None,
            budget=None,
        )
    )
    assert row["completion_check"] == {
        "passed": False,
        "exact_output": True,
        "exact_tool_call": False,
    }
    assert row["tool_calls"] == 2


def test_failed_run_retains_known_usage_cost_and_static_reason(mocker):
    case = benchmark.cases()[2]

    async def partial_failure(profile, prompt, tools, checkpoint, **kwargs):
        await checkpoint(
            {
                "steps": 2,
                "usage": {"input_tokens": 40, "output_tokens": 10, "cached_input_tokens": 5},
                "tools": [],
            }
        )
        raise benchmark.ExecutionStopped("benchmark_spend_cap")

    mocker.patch.object(benchmark, "run_graph", side_effect=partial_failure)
    row = asyncio.run(
        benchmark.run_case(
            case,
            "deepagents",
            0,
            mode="offline",
            provider="openai",
            model_name="gpt-5-mini",
            reasoning_effort=None,
            max_calls_per_run=6,
            max_output_tokens=512,
            price=price(),
            budget=None,
        )
    )
    assert row["error_code"] == "benchmark_spend_cap"
    assert row["model_attempts"] == 2 and row["model_calls"] == 0
    assert row["total_tokens"] == 50 and row["cached_input_tokens"] == 5
    assert row["estimated_cost_micro_usd"] == 60
    assert row["cost_estimate_basis"] == (
        "supplied_price_all_input_at_standard_rate_cache_discount_excluded"
    )


def test_denied_reservation_is_an_attempt_without_a_provider_call(tmp_path, mocker):
    case = benchmark.cases()[2]
    report = RunReport(tmp_path, {})
    budget = benchmark.BenchmarkBudget(
        price(),
        report,
        cap_micro_usd=1,
        max_calls=6,
        max_input_tokens=100,
        max_output_tokens=512,
    )

    async def denied(profile, prompt, tools, checkpoint, **kwargs):
        await checkpoint({"steps": 1, "usage": {}, "tools": []})
        await kwargs["spending"].reserve(
            uuid4(),
            role="lead",
            provider="openai",
            model="gpt-5-mini",
            input_tokens=100,
            output_tokens=512,
        )
        raise AssertionError("Provider call must not follow denied reservation")

    mocker.patch.object(benchmark, "run_graph", side_effect=denied)
    row = asyncio.run(
        benchmark.run_case(
            case,
            "deepagents",
            0,
            mode="offline",
            provider="openai",
            model_name="gpt-5-mini",
            reasoning_effort=None,
            max_calls_per_run=6,
            max_output_tokens=512,
            price=price(),
            budget=budget,
        )
    )
    assert row["error_code"] == "benchmark_spend_cap"
    assert row["model_attempts"] == 1
    assert row["model_calls"] == 0
    assert row["reserved_model_calls"] == 0
    assert report.data["calls"] == []


@pytest.mark.parametrize("runtime", ["deepagents", "strands"])
def test_both_runtimes_share_deadline_and_retain_timed_out_reservation(runtime, tmp_path, mocker):
    original_validate = benchmark.AgentProfile.model_validate

    def short_duration(value):
        return original_validate(value).model_copy(update={"max_duration_seconds": 0.02})

    mocker.patch.object(benchmark.AgentProfile, "model_validate", side_effect=short_duration)

    async def stalled(profile, prompt, tools, checkpoint, **kwargs):
        await checkpoint({"steps": 1, "usage": {}, "tools": []})
        await kwargs["spending"].reserve(
            uuid4(),
            role="lead",
            provider="openai",
            model="gpt-5-mini",
            input_tokens=100,
            output_tokens=512,
        )
        await asyncio.sleep(1)
        raise AssertionError("The benchmark deadline must stop this run")

    mocker.patch.object(benchmark, "run_graph", side_effect=stalled)
    mocker.patch.object(benchmark, "run_strands", side_effect=stalled)
    report = RunReport(tmp_path, {})
    budget = benchmark.BenchmarkBudget(
        price(),
        report,
        cap_micro_usd=2000,
        max_calls=6,
        max_input_tokens=100,
        max_output_tokens=512,
    )
    row = asyncio.run(
        benchmark.run_case(
            benchmark.cases()[2],
            runtime,
            0,
            mode="offline",
            provider="openai",
            model_name="gpt-5-mini",
            reasoning_effort=None,
            max_calls_per_run=6,
            max_output_tokens=512,
            price=price(),
            budget=budget,
        )
    )
    assert row["error_code"] == "benchmark_timeout"
    assert row["completion_check"]["passed"] is False
    assert row["model_attempts"] == 1 and row["model_calls"] == 0
    assert row["reserved_model_calls"] == 1
    assert row["charged_micro_usd"] == 1124
    assert report.data["calls"][0]["state"] == "usage_unknown"


@pytest.mark.parametrize("exception", [ValueError, TimeoutError])
def test_model_construction_failure_produces_a_result_row(mocker, exception):
    mocker.patch.object(benchmark, "create_chat_model", side_effect=exception("synthetic setup"))
    row = asyncio.run(
        benchmark.run_case(
            benchmark.cases()[2],
            "strands",
            0,
            mode="live",
            provider="openai",
            model_name="gpt-5-mini",
            reasoning_effort=None,
            max_calls_per_run=6,
            max_output_tokens=512,
            price=None,
            budget=None,
        )
    )
    assert row["error_code"] == exception.__name__
    assert row["completion_check"]["passed"] is False
    assert row["model_attempts"] == 0
    assert row["model_calls"] is None
    assert row["reserved_model_calls"] is None


@pytest.mark.parametrize("runtime", ["deepagents", "strands"])
def test_inner_timeout_is_distinct_from_the_benchmark_deadline(mocker, runtime):
    async def timed_out(*args, **kwargs):
        raise TimeoutError("Synthetic inner timeout")

    mocker.patch.object(benchmark, "run_graph", side_effect=timed_out)
    mocker.patch.object(benchmark, "run_strands", side_effect=timed_out)
    row = asyncio.run(
        benchmark.run_case(
            benchmark.cases()[2],
            runtime,
            0,
            mode="offline",
            provider="openai",
            model_name="gpt-5-mini",
            reasoning_effort=None,
            max_calls_per_run=6,
            max_output_tokens=512,
            price=None,
            budget=None,
        )
    )
    assert row["error_code"] == "TimeoutError"
    assert not row["completion_check"]["passed"]


def test_aggregate_missing_first_feedback_is_null():
    aggregate = benchmark.aggregate_results(
        [
            {
                "case_id": "research",
                "runtime": "deepagents",
                "completion_check": {"passed": False},
                "duration_ms": 9,
                "time_to_first_text_ms": None,
                "time_to_first_tool_ms": None,
                "first_tool_latency_ms": None,
            }
        ]
    )
    research = next(
        row
        for row in aggregate["by_case_runtime"]
        if row["case_id"] == "research" and row["runtime"] == "deepagents"
    )
    assert research["attempted"] == 1 and research["completed"] == 0
    assert research["duration_ms"] == {"p50": 9, "p95": 9}
    assert research["time_to_first_text_ms"] == {"p50": None, "p95": None}


def test_reasoning_effort_requires_a_model_that_receives_it():
    with pytest.raises(ValueError, match="supported OpenAI reasoning model"):
        benchmark.profile_for(
            benchmark.cases()[0],
            "gemini",
            "gemini-2.5-flash",
            reasoning_effort="medium",
            max_calls_per_run=6,
            max_output_tokens=512,
        )


def test_budget_persists_reservation_before_call_and_retains_unknown(tmp_path):
    report = RunReport(tmp_path, {"measurement": "test"})
    budget = benchmark.BenchmarkBudget(
        price(),
        report,
        cap_micro_usd=250,
        max_calls=3,
        max_input_tokens=100,
        max_output_tokens=20,
    )

    async def exercise():
        gate = budget.gate("research", "deepagents", 0)
        first = uuid4()
        await gate.reserve(
            first,
            role="lead",
            provider="openai",
            model="synthetic",
            input_tokens=100,
            output_tokens=20,
        )
        saved = json.loads(report.path.read_text())["calls"]
        assert saved[0]["state"] == "reserved"
        assert saved[0]["charged_micro_usd"] == 140
        await gate.settle(first, 50, 5)
        assert json.loads(report.path.read_text())["calls"][0]["charged_micro_usd"] == 60

        second = uuid4()
        await gate.reserve(
            second,
            role="lead",
            provider="openai",
            model="synthetic",
            input_tokens=100,
            output_tokens=20,
        )
        await gate.unknown(second, "provider_timeout")
        calls = json.loads(report.path.read_text())["calls"]
        assert calls[1]["state"] == "usage_unknown"
        assert calls[1]["charged_micro_usd"] == 140
        with pytest.raises(SpendingDenied, match="benchmark_prior_usage_unknown"):
            await gate.reserve(
                uuid4(),
                role="lead",
                provider="openai",
                model="synthetic",
                input_tokens=1,
                output_tokens=1,
            )

    asyncio.run(exercise())


def test_budget_counts_compaction_calls_and_halts_on_missing_outcome(tmp_path):
    report = RunReport(tmp_path, {})
    budget = benchmark.BenchmarkBudget(
        price(),
        report,
        cap_micro_usd=300,
        max_calls=2,
        max_input_tokens=100,
        max_output_tokens=20,
    )

    async def exercise():
        gate = budget.gate("document", "strands", 0)
        for role in ("lead", "compaction"):
            await gate.reserve(
                uuid4(),
                role=role,
                provider="openai",
                model="synthetic",
                input_tokens=100,
                output_tokens=20,
            )
        assert [call["role"] for call in report.data["calls"]] == ["lead", "compaction"]
        with pytest.raises(SpendingDenied, match="benchmark_call_bound"):
            await gate.reserve(
                uuid4(),
                role="lead",
                provider="openai",
                model="synthetic",
                input_tokens=1,
                output_tokens=1,
            )
        budget.mark_unsettled_unknown()
        assert all(call["state"] == "usage_unknown" for call in report.data["calls"])
        assert sum(call["charged_micro_usd"] for call in report.data["calls"]) == 280

    asyncio.run(exercise())


def test_budget_denies_before_provider_call_when_cap_is_too_small(tmp_path):
    report = RunReport(tmp_path, {})
    budget = benchmark.BenchmarkBudget(
        price(),
        report,
        cap_micro_usd=139,
        max_calls=1,
        max_input_tokens=100,
        max_output_tokens=20,
    )

    async def exercise():
        with pytest.raises(SpendingDenied, match="benchmark_spend_cap"):
            await budget.gate("research", "deepagents", 0).reserve(
                uuid4(),
                role="lead",
                provider="openai",
                model="synthetic",
                input_tokens=100,
                output_tokens=20,
            )

    asyncio.run(exercise())
    assert json.loads(report.path.read_text())["calls"] == []


def test_live_requires_fresh_rates_explicit_cap_and_whole_run_bound(tmp_path):
    with pytest.raises(ValueError, match="price-file"):
        benchmark.main(["--mode", "live", "--report-dir", str(tmp_path)])
    assert not list(tmp_path.iterdir())
    with pytest.raises(ValueError, match="positive"):
        benchmark.validate_live(
            allow_paid=False,
            cap_micro_usd=1000,
            price=price(),
            repeats=1,
            max_calls_per_run=2,
            max_input_tokens=100,
            max_output_tokens=256,
        )
    stale = price().model_copy(update={"verified_at": datetime(2020, 1, 1, tzinfo=UTC)})
    with pytest.raises(ValueError, match="current model pricing"):
        benchmark.validate_live(
            allow_paid=True,
            cap_micro_usd=10000,
            price=stale,
            repeats=1,
            max_calls_per_run=2,
            max_input_tokens=100,
            max_output_tokens=256,
        )
    bound = len(benchmark.cases()) * 2 * 2 * price().cost(100, 256)
    with pytest.raises(ValueError, match="conservative"):
        benchmark.validate_live(
            allow_paid=True,
            cap_micro_usd=bound - 1,
            price=price(),
            repeats=1,
            max_calls_per_run=2,
            max_input_tokens=100,
            max_output_tokens=256,
        )
    assert (
        benchmark.validate_live(
            allow_paid=True,
            cap_micro_usd=bound,
            price=price(),
            repeats=1,
            max_calls_per_run=2,
            max_input_tokens=100,
            max_output_tokens=256,
        )
        == bound
    )
