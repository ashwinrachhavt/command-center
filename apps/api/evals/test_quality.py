import pytest

from .dataset import load_suite
from .judge import evaluate_case


@pytest.mark.parametrize("case", load_suite().cases, ids=lambda case: case.id)
def test_recorded_agent_quality(case, quality_run):
    plan, captures, model, allowance, report = quality_run
    results = evaluate_case(case, captures[case.id], model, plan, allowance, report)
    errors = [result["metric"] for result in results if result["state"] == "evaluator_error"]
    failures = [result["metric"] for result in results if result["state"] == "quality_failed"]
    assert not errors, f"Evaluator errors for {case.id}: {errors}; see {report.path}"
    assert not failures, f"Quality thresholds failed for {case.id}: {failures}; see {report.path}"
