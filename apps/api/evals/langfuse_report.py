"""Publish synthetic DeepEval reports and judge costs to the request's Langfuse trace."""

from typing import Any

from langfuse import Langfuse

from .contracts import RunReport


def publish_report(report: RunReport, client: Langfuse) -> dict[str, str]:
    captures = report.data.get("captures", {})
    if captures.get("classification") != "synthetic" or captures.get("origin") != "recorded_model":
        raise ValueError(
            "Only recorded synthetic model captures can be published as quality reports"
        )
    cases = {case["id"]: case for case in report.data["suite"]["cases"]}
    trace_ids = {}
    for capture in captures["cases"]:
        case_id = capture["case_id"]
        trace_id = capture.get("trace_id") or client.create_trace_id(
            seed=f"{report.directory.name}:{case_id}"
        )
        trace_ids[case_id] = trace_id
        # Evaluation observations are separate from the original generation; imported
        # captures carry usage once, while an already-traced generation isn't duplicated.
        span = client.start_observation(
            trace_context={"trace_id": trace_id},
            name="deepeval-report",
            as_type="evaluator",
            input={
                "prompt": cases[case_id]["prompt"],
                "expected_behavior": cases[case_id]["expected_behavior"],
                "evidence": cases[case_id]["evidence"],
            },
            output=capture["actual_output"],
            metadata={
                "case_id": case_id,
                "report_id": report.directory.name,
                "suite_sha256": captures["suite_sha256"],
                "origin": "recorded_model",
            },
        )
        if not capture.get("trace_id"):
            generation = span.start_observation(
                name="recorded-synthetic-output",
                as_type="generation",
                input=cases[case_id]["prompt"],
                output=capture["actual_output"],
                model=capture["model"]["model"],
                usage_details={"input": capture["input_tokens"], "output": capture["output_tokens"]}
                if capture.get("input_tokens") is not None
                and capture.get("output_tokens") is not None
                else None,
            )
            generation.end()
        for result in report.data["results"]:
            if result["case_id"] != case_id:
                continue
            metric = result["metric"]
            score_id = client.create_trace_id(seed=f"{report.directory.name}:{case_id}:{metric}")
            if result["state"] == "evaluator_error":
                client.create_score(
                    trace_id=trace_id,
                    score_id=score_id,
                    name=f"deepeval.{metric}.status",
                    data_type="CATEGORICAL",
                    value="evaluator_error",
                    comment=result.get("error_type", "Evaluator unavailable"),
                )
            else:
                client.create_score(
                    trace_id=trace_id,
                    score_id=score_id,
                    name=f"deepeval.{metric}",
                    data_type="NUMERIC",
                    value=result["score"],
                    comment=result.get("reason"),
                    metadata={
                        "threshold": result["threshold"],
                        "state": result["state"],
                        "report_id": report.directory.name,
                    },
                )
        # Judge observations live in their own trace, so request cost remains separate.
        judge_trace_id = client.create_trace_id(seed=f"{report.directory.name}:{case_id}:judge")
        for call in report.data["calls"]:
            if call["case_id"] != case_id:
                continue
            usage = call.get("usage")
            observation: Any = client.start_observation(
                trace_context={"trace_id": judge_trace_id},
                name=f"deepeval.{call['metric']}",
                as_type="generation",
                model=report.data["plan"]["judge"]["model"],
                metadata={
                    "request_trace_id": trace_id,
                    "usage_status": call["state"],
                    "reserved_micro_usd": call["reserved_micro_usd"],
                },
                usage_details={"input": usage["input_tokens"], "output": usage["output_tokens"]}
                if usage
                else None,
                cost_details={"total": call["charged_micro_usd"] / 1_000_000} if usage else None,
            )
            observation.end()
        span.end()
    client.flush()
    report.data["langfuse"] = {"state": "exported", "trace_ids": trace_ids}
    report.save()
    return trace_ids
