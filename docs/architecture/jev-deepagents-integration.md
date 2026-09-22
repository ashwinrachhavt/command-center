# Jev as a Decision Layer for Command Center Deep Agents

## Purpose

Jev refers to TypeSafe AI's System One decision model. It is not a conversational assistant, named in-product persona, LangGraph replacement, or autonomous agent framework. Jev evaluates bounded, typed questions over supplied application state and returns machine-actionable choices, scores, probabilities, and confidence.

Command Center should use Jev as a semantic verifier and policy-aware routing layer around its LangGraph/Deep Agents. Deep Agents retain responsibility for open-ended planning, research, drafting, specialist delegation, and proposing tool calls. Deterministic application code retains responsibility for permissions, schemas, policy thresholds, budgets, audit records, idempotency, retries, external side effects, and escalation.

## Architecture

```text
User request
   |
   v
LangGraph / Deep Agent
   |-- plans and reasons
   |-- selects tools
   |-- proposes tool arguments
   `-- produces research, drafts, or action proposals
   |
   v
Deterministic validation
   |-- schema, ownership, permissions
   |-- budget reservation
   |-- idempotency, freshness, revision checks
   `-- account and source-version fences
   |
   v
Jev decision gate
   |-- semantic relevance
   |-- policy fit
   |-- evidence sufficiency
   |-- side-effect risk
   `-- human-review necessity
   |
   v
Deterministic policy
   |-- allow
   |-- repair / re-plan
   |-- ask user
   `-- create reviewed action
   |
   v
Existing reviewed-action and worker path
```

## Responsibilities

| Component | Responsibility |
|---|---|
| Deep Agent / LangGraph | Open-ended planning, research, drafting, tool-use proposals, specialist delegation |
| Jev | Narrow semantic judgments over a known state and finite typed questions |
| Command Center code | Policy thresholds, authorization, side effects, audit history, budgets, retries, idempotency, escalation |
| Human | Approval for consequential writes and resolution of material ambiguity |

Jev never executes tools directly, owns application state transitions, or bypasses review. It evaluates a limited decision, and code composes that result with hard controls.

## Pre-tool semantic verification

The highest-value first integration is before a Deep Agent tool call. First validate deterministic properties. Then use Jev to determine whether the call is semantically appropriate.

```python
async def decide_tool_execution(*, user_request: str, agent_plan: dict, tool_name: str, tool_args: dict, available_tools: list[dict], policy: dict) -> ToolDecision:
    structural_validation = validate_tool_call(tool_name=tool_name, tool_args=tool_args, available_tools=available_tools)
    if not structural_validation.is_valid:
        return ToolDecision.block(reason=structural_validation.error)

    jev_result = await jev.system_one(
        state={
            "user_request": user_request,
            "agent_plan": agent_plan,
            "proposed_tool_call": {"name": tool_name, "arguments": tool_args},
            "policy": policy,
        },
        questions={
            "tool_is_relevant": noul(instructions="Is the proposed tool call directly relevant to fulfilling the user's request and current plan?"),
            "arguments_match_intent": noul(instructions="Do the proposed arguments semantically respect the user's stated constraints, the plan, and the supplied policy?"),
            "has_external_effect": noul(instructions="Would this tool call create, modify, send, publish, delete, purchase, or otherwise change external state?"),
            "approval_is_required": noul(instructions="Does this proposed action require explicit human review under the provided policy?"),
            "risk": score(
                instructions="Assess the operational risk of executing this proposed tool call in the supplied context.",
                criteria=[
                    "Read-only or harmless",
                    "Reversible low-impact write",
                    "Meaningful external side effect",
                    "Irreversible, sensitive, financial, legal, or high-impact action",
                ],
            ),
        },
    )
    return compose_tool_decision(structural_validation=structural_validation, jev=jev_result, policy=policy)
```

Compose atomic answers in code rather than asking a broad question such as "Was the entire agent correct?"

```python
def compose_tool_decision(*, structural_validation: ToolValidation, jev: JevResult, policy: ToolPolicy) -> ToolDecision:
    relevant = jev.answers["tool_is_relevant"].noul
    intent_match = jev.answers["arguments_match_intent"].noul
    has_effect = jev.answers["has_external_effect"].noul
    needs_approval = jev.answers["approval_is_required"].noul
    risk = jev.answers["risk"].score

    if relevant < 0.92 or intent_match < 0.95:
        return ToolDecision.replan(reason="semantic mismatch or insufficient certainty", evidence=jev)
    if has_effect >= 0.70 or needs_approval >= 0.70 or risk >= 2.0:
        return ToolDecision.review(reason="side effect or policy-sensitive action", evidence=jev)
    return ToolDecision.allow(reason="read-only, relevant, policy-compatible action", evidence=jev)
```

Thresholds are examples only. Calibrate them from held-out Command Center cases and set them through policy, not prompt text.

## Post-run quality verification

Use Jev after a Deep Agent finishes research, produces an artifact, or proposes an action.

```python
questions = {
    "answers_the_question": noul(instructions="Does `draft_answer` directly answer `user_request`?"),
    "evidence_is_sufficient": noul(instructions="Do `sources` provide enough support for the material claims in `draft_answer`?"),
    "contains_unsupported_claims": noul(instructions="Does `draft_answer` assert a material factual claim that is not supported by the provided sources?"),
    "next_step": choice(
        instructions="What is the correct workflow outcome?",
        criteria={
            "deliver": "The answer is adequate to return to the user.",
            "revise": "The answer needs targeted revision or more evidence.",
            "ask_user": "The task cannot proceed without a user clarification.",
            "human_review": "The content is too consequential or uncertain to deliver automatically.",
        },
    ),
}
```

## Reviewed action routing

For Gmail, Calendar, Linear, Notion, browser writes, and other external effects, Jev may recommend the route into a reviewed action. Existing checks remain mandatory: account ownership, source-version binding, exact payload and attachment revision, idempotency, receipts, spending capacity, worker claim fencing, and explicit review.

## Example: prevent read/write confusion

User request: "Find my next three calendar openings next week." A Deep Agent proposes `calendar.create_event`. The call may be syntactically valid, but it violates the user's read-only intent. Jev receives the request, proposed call, and available read/write tools. If relevance or requested-effect preservation fall below policy thresholds, code returns the action to the planner with a concrete correction: use a read-only calendar listing capability.

## Proposed implementation boundary

```text
apps/api/src/command_center/
├── agents/
│   ├── runtime.py
│   ├── tools.py
│   ├── worker.py
│   └── decisioning/
│       ├── __init__.py
│       ├── typesafe_jev.py       # API or SDK adapter only
│       ├── contracts.py          # typed input/output models
│       ├── policies.py           # pure deterministic threshold composition
│       ├── tool_guard.py         # pre-tool semantic verification
│       ├── output_guard.py       # post-run quality/evidence checks
│       └── observability.py      # decision and outcome telemetry
├── api/
│   └── agent_events.py
└── evals/
    └── jev/
        ├── tool_guard_cases.jsonl
        ├── output_guard_cases.jsonl
        └── calibration_report.py
```

Keep the TypeSafe client server-side. Do not put API credentials in the browser extension, API route handlers, Celery task definitions, integration adapters, or reviewed-action executor.

## First implementation PR

Start with "Add Jev semantic guardrails for Deep Agent tool calls."

- Implement a `DecisionModel` protocol and server-side TypeSafe adapter.
- Define typed decisions for tool relevance, intent alignment, external effect, human-review need, and operational risk.
- Compose those signals through pure deterministic `allow`, `replan`, `ask_user`, `review`, or `block` policy.
- Integrate at one existing tool-dispatch boundary.
- Persist redacted decision events with question IDs, distributions, threshold version, model metadata, latency, and final outcome.
- Test with a fake decision model and offline fixtures.
- Run in shadow mode first; measure agreement with human and existing-policy outcomes before enforcement.

## Non-goals

- Replacing LangGraph or Deep Agents
- Letting Jev execute tools or writes directly
- Treating confidence as a replacement for product policy
- Sending unrestricted document or browser contents to an external model
- Using Jev as a generic chat, planning, code-generation, or long-horizon reasoning model
