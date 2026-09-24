# Jev Use Cases in Command Center

**Status update, 2026-09-24:** this is a broad idea catalog, not an implementation inventory. The [source audit and ranked opportunities](../tech/jev-audit.md) supersede the historical phase order below. Optional capability routing and opt-in document decisions are implemented locally. The dedicated document worker supports `document-type.v3` classification and explicit research/agent checks for one extracted document, followed by human type review and separately configured display-title rename review. These advisory checks do not implement generic browser/tool guards or authorize execution. The three canonical specs own behavior, technical contracts and UX; [Engineering](../tech/engineering.md#spaces-and-document-decisions--local-implementation-2026-09-24) records delivery evidence.

## Decision-model role

Jev should be used when Command Center needs a bounded semantic judgment that application code can combine with deterministic controls. It is not a general chat model, planner, or autonomous executor.

The governing pattern is:

```text
application state + typed atomic questions
        |
        v
Jev choice / score / probability distributions
        |
        v
deterministic thresholds + policy + state validation
        |
        v
allow / replan / ask user / review / block
```

## Catalog

Rows describe potential uses, including broader workflows beyond the implemented per-document checks. The current document slice covers type, evidence, commitment/follow-up/deadline signals and optional relevance, evidence role, claim support, output quality, policy concern and action matching. It does not sweep inboxes, gate every tool call or execute browser actions.

| Area | Typed decision | Minimum state | Code-owned outcome |
|---|---|---|---|
| Tool selection | Is the selected tool relevant to the objective? | User request, plan step, proposed tool, tool catalog | Allow tool, replan, or ask user |
| Tool arguments | Do arguments honor user constraints and policy? | Request, arguments, relevant context, policy | Execute, repair, or block |
| Write-effect detection | Is there a semantic warning beyond the known tool effect? | Host-classified tool, arguments, target | Additional warning only; code owns read/write classification |
| Approval routing | Is there an additional reason to ask for review? | Proposed action and bounded evidence | Can escalate; cannot remove required approval |
| Plan-step verification | Does the next plan step advance the stated goal? | Objective, plan, current state | Continue, replan, or clarify |
| Agent trace verification | Was a tool-use step appropriate in context? | Observation, chosen action, result | Continue, repair, terminate, escalate |
| Completion verification | Did the workflow achieve its exact objective? | Goal, before/after state, postcondition | Complete, retry, or surface failure |
| Research quality gate | Does a draft answer answer the original question? | Prompt, sources, draft | Deliver, revise, retrieve, ask user |
| Citation grounding | Are material claims supported by sources? | Claim list, source excerpts, draft | Accept, qualify, remove, escalate |
| Evidence sufficiency | Is retrieved evidence enough to answer? | Query, chunks, contradictions | Generate, retrieve more, abstain |
| Extraction verification | Is a structured field grounded in source text? | Document, extracted value, supporting span | Accept, mark uncertain, review |
| Contradiction detection | Does new evidence conflict with records? | Source, prior facts, revision history | Flag conflict and route to review |
| Profile fact proposal | Should a candidate fact be promoted for review? | Document/source, proposed fact, current revision | Propose, merge, discard |
| Document classification | Which eligible catalog type describes the text? | Exact extraction, catalog descriptions, weak filename evidence | Propose type or unknown/mixed; human acceptance changes metadata |
| Configured document renaming | Can accepted metadata render the naming template? | Accepted type, upload date, stable ID, policy revision | Code renders a preview and creates a separate rename task; no Jev text generation |
| Lead qualification | Is a lead aligned with criteria? | Job/company evidence, preferences, policy | Prioritize, watch, reject, review |
| Outreach safety | Does draft outreach conform to campaign policy? | Recipient, relationship context, draft, constraints | Keep draft, revise, review, block |
| Application answer fit | Does an approved response fit the exact question? | Field label/help, approved facts, answer | Fill, review, leave blank |
| Browser field matching | Which visible control matches the objective? | Normalized DOM, labels, finite candidates | Fill only validated field |
| Browser option selection | Which exact allowed option is appropriate? | Field context, option set, approved facts | Select, ask user, review |
| Browser action choice | Which safe next primitive is appropriate? | Page state, objective, candidates | Click, fill, select, upload, scroll, stop |
| Browser danger detection | Is a candidate a high-consequence action? | Control semantics, page context, objective | Block automation and review |
| Sensitive-field routing | Is a question legal, demographic, compensation, or identity-sensitive? | Label, help text, page context | Require explicit review |
| Calendar verification | Does event payload match the request? | Request, event details, calendar context | Review, revise, block |
| Gmail verification | Do recipient, body, and attachments match intent? | Request, exact draft, recipients, attachments | Review, revise, block |
| Notion/Linear guard | Does update target the correct record/state? | Record context, proposed payload, account permissions | Review, execute, reject |
| Spending justification | Is a proposed model/tool call warranted? | Task class, expected benefit, cost, budget | Reserve, cheaper fallback, ask |
| Escalation routing | Should uncertainty go to human, specialist, or retry? | Probabilities, risk, workflow status, cost | Route by policy |
| Review prioritization | Which items deserve scarce human attention first? | Ambiguity, materiality, evidence gap, risk | Rank queue deterministically |
| Failure explanation | Is there a semantic mismatch beyond a known error? | Sanitized error and bounded task evidence | Explain or suggest replan; known transport retry eligibility stays in code |
| Memory retrieval gate | Is retrieved memory relevant and authorized for this run? | Request, memories, work scope | Include, exclude, confirm |
| Privacy minimization | Is each data field necessary for a decision? | Proposed state, data labels, question | Redact, minimize, block |
| Evaluation labeling | Does output pass a scenario-specific rubric? | Fixture, expected policy, observed output | Repeatable offline signal |
| Regression monitoring | Has decision quality drifted after a change? | Held-out cases, logs, observed outcomes | Alert, rollback, recalibrate |

## Detailed workflow patterns

### Tool-call semantic guard

**Problem:** Schema-valid tool calls can be semantically wrong. A read-only request can yield a write tool; a tool may be relevant but the arguments violate the user's constraints.

**Questions:**

- Is this tool relevant to the objective?
- Do the arguments match user intent?
- Does the call introduce an external effect?
- Does policy require explicit review?
- How operationally risky is the step?

**Outcome:** Use hard thresholds and deterministic policy to allow, replan, ask, review, or block.

### Research and RAG gate

**Problem:** An agent can produce fluent text from insufficient or conflicting evidence.

**Questions:**

- Are retrieved sources relevant?
- Are they sufficient for the requested claim?
- Do the sources conflict?
- Does the answer contain unsupported material claims?
- Should the system deliver, revise, retrieve more, ask a user, or request review?

**Outcome:** Answer only when evidence and policy clear threshold. Otherwise abstain or continue research.

### Extraction–verification cascade

**Problem:** A flexible extractor can create plausible but incorrect structured fields.

**Flow:**

```text
Document or page
   |
   v
Extractor proposes structured values
   |
   v
Jev verifies grounding, ambiguity, and contradictions
   |
   v
Code accepts safe values or routes uncertain values to review
```

**Examples:** invoice total, company name, due date, resume employment date, form answer, contact identity, lead location.

### Human-review prioritization

**Problem:** Not every uncertain item deserves equal human attention.

**Signals:** semantic ambiguity, conflict with historical data, missing evidence, external impact, monetary/material consequence, and sensitive-data classification.

**Outcome:** Compute a deterministic queue priority from Jev signals and hard business factors. Keep the scoring formula in code so it is inspectable and adjustable.

### Browser micro-loop

**Problem:** General LLM browser loops are often slow and can choose valid-looking but incorrect controls.

**Jev role:** choose one permitted action and one candidate element from a current finite set; estimate whether a target exists, whether it matches intent, and whether review is needed.

**Code role:** create candidates, validate fresh page/frame identity, enforce allowlists, execute permitted actions, and verify the resulting visible state.

### Reviewed integration actions

**Problem:** A draft Gmail, Calendar, Linear, or Notion action may be structurally valid but target the wrong account, record, recipient, or outcome.

**Jev role:** semantic intent, payload-policy fit, likely irreversibility, sensitivity, and review necessity.

**Code role:** account ownership, exact immutable revision binding, source and attachment verification, permission checks, idempotency, receipts, queue execution, and audit.

### Safe memory use

**Problem:** Memory can be stale, irrelevant, outside the current work scope, or too sensitive to use automatically.

**Jev role:** relevance and semantic applicability of a candidate memory to the immediate request.

**Code role:** authorization, expiration, source provenance, user/workspace scope, redaction, and final inclusion policy.

## Prioritization for Command Center

The following phases are historical proposals. Use the [2026-09-24 audit](../tech/jev-audit.md#prioritized-opportunity-map) and [current Engineering delivery](../tech/engineering.md#spaces-and-document-decisions--local-implementation-2026-09-24) for current priorities. In every phase, model signals may add review; they cannot waive a deterministic review requirement.

### Phase 0: offline evaluation

Build fixtures from existing synthetic browser, reviewed-action, conversation, and research cases. Record expected outcomes before putting Jev in a live workflow.

### Phase 1: shadow-mode browser ranking

Evaluate browser target/action choices without changing execution. This yields labeled traces for candidate quality, selection accuracy, abstention quality, and postcondition success.

### Phase 2: pre-tool read-only guard

Gate Deep Agent read-only tool selection and argument alignment. Replan on low confidence; do not block workflows without a recovery path.

### Phase 3: post-run evidence and completion guard

Check research outputs and browser completion claims before marking a run complete or delivering results.

### Phase 4: action review routing

Use Jev to improve whether an action enters the existing reviewed-action queue. Do not let it directly execute writes.

### Phase 5: bounded low-risk enforcement

After evaluation, enable enforcement only for well-tested, reversible, bounded action classes. Keep sensitive, financial, legal, submission, send, publish, and deletion operations behind explicit human review.

## Evaluation and calibration

Confidence is not a permission slip. Calibrate thresholds using Command Center's own held-out cases. Track:

- Precision, recall, and false-positive/false-negative cost by use case
- Abstention rate and recovery success
- Human-review agreement and override rate
- Postcondition success for browser actions
- Read/write classification error
- Tool-call semantic mismatch detection rate
- Latency and cost per decision
- Performance by provider, workflow, website, integration, and policy version
- Drift after Jev model changes, prompts/questions changes, browser changes, or UI markup changes

## Non-negotiable guardrails

- No side effect solely because a model confidence is high.
- No bypass of reviewed actions, immutable revisions, account verification, spending limits, receipts, or audit logs.
- No browser-side TypeSafe API key.
- No raw secret or unnecessary sensitive-data transmission.
- No autonomous Next, Submit, Send, Purchase, Delete, legal acceptance, or sensitive-answer action.
- No evaluation claim without fixture-level evidence and outcome tracking.
