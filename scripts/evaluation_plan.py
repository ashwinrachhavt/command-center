"""Write a costed proposal without loading model credentials or making provider calls."""

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    sys.path.insert(0, str(ROOT / "apps" / "api"))
    from evals.contracts import METRICS, Plan
    from evals.dataset import load_suite

    suite = load_suite()
    proposal = Plan.model_validate(
        {
            "schema_version": 1,
            "suite_sha256": suite.fingerprint(),
            "judge": {"provider": "openai", "model": "gpt-5.4-mini-2026-03-17"},
            "price": {
                "input_micro_usd_per_million": 750000,
                "output_micro_usd_per_million": 4500000,
                "source_url": "https://developers.openai.com/api/docs/models/gpt-5.4-mini",
                "verified_at": "2026-09-22T00:00:00Z",
            },
            # Proposed review values, never permission to execute a paid benchmark.
            "thresholds": {"grounding": 1, "relevance": 0.8, "completion": 0.8},
            "max_input_tokens": 32768,
            "max_output_tokens": 2048,
            "max_calls": len(suite.cases) * len(METRICS),
            "max_cost_micro_usd": 0,
        }
    )
    parent = ROOT / ".local" / "evals" / "plans"
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = parent / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid4().hex}.json"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as output:
        json.dump(proposal.model_dump(mode="json"), output, indent=2)
        output.write("\n")
    print(f"Proposal: {path.relative_to(ROOT)}")
    print(
        f"{len(suite.cases)} cases, {proposal.max_calls} judge calls, no automatic retries."
    )
    print(
        f"Conservative judge-call bound: USD {proposal.upper_bound() / 1_000_000:.6f}."
    )
    print(
        "Allowance remains USD 0. Review prices, thresholds and an allowance before execution."
    )
    print(
        "Recorded-output generation costs are separate; this command made no model calls."
    )


if __name__ == "__main__":
    main()
