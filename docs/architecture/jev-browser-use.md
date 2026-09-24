# Jev-Assisted Browser Use for Command Center

## Purpose

Jev can improve browser-agent speed and semantic action selection by evaluating a bounded page observation and a finite, application-constructed list of valid action candidates. It does not replace browser automation, DOM inspection, state management, or safety policy.

The correct claim is not "Jev drives a browser autonomously." It is: **Jev can make a browser micro-loop faster and more controllable when the application owns candidate construction, execution, and verification.**

## Conventional versus bounded loop

A general browser agent often repeats this loop:

```text
Screenshot / DOM / accessibility tree
        |
        v
Frontier LLM reasons in natural language
        |
        v
Tool call: click / type / scroll / navigate
        |
        v
Browser executes
        |
        `-- repeat
```

A Jev-assisted loop is narrower:

```text
Browser observation
  |-- URL, title, normalized DOM / accessibility tree
  |-- visible labels and nearby context
  |-- interactable elements only
  `-- current objective and workflow policy
        |
        v
Deterministic candidate construction
  |-- allowed actions: click, fill, select, upload, scroll, done
  |-- valid target elements
  `-- allowed values or exact options
        |
        v
Jev typed decisions
  |-- which action class?
  |-- which candidate element?
  |-- does a valid target exist?
  |-- is the action semantically aligned?
  `-- does it require review?
        |
        v
Deterministic policy
  |-- execute
  |-- fall back to a planner
  |-- ask the user
  `-- stop safely
```

The browser framework executes actions. Jev only scores/selects within the permitted action space.

## Candidate construction

The companion or browser service must build candidates before invoking Jev. A candidate should be present only when it is:

- Associated with the exact current document, frame, and URL
- Visible, enabled, and interactable
- Assigned a stable internal candidate ID
- Classified by element type and allowed action classes
- Enriched with accessible name, associated label, nearby help text, current value, selected state, and constraints
- Bound to the current page-observation version or hash
- Excluded if it belongs to a cross-origin frame, stale page, hidden region, unknown custom widget, or prohibited control class

```ts
type BrowserCandidate = {
  id: string;
  actionKinds: Array<"click" | "fill" | "select" | "upload_file" | "scroll">;
  role: string;
  accessibleName: string;
  label: string | null;
  nearbyText: string[];
  inputType: string | null;
  options?: Array<{ value: string; label: string }>;
  constraints?: { min?: number; max?: number; step?: number; required?: boolean };
  pageVersion: string;
  frameId: string;
  visible: boolean;
  enabled: boolean;
  prohibited: boolean;
};
```

## Atomic browser decisions

Do not ask one broad question such as "What should the browser do?" Ask independent, inspectable decisions.

```ts
const assessment = await jev.systemOne({
  model: "jev-latest",
  state: {
    objective,
    policy,
    page: redactedObservation,
    candidates: candidates.map(toDecisionCandidate),
  },
  questions: {
    action: choice({
      instructions: "What is the next safe browser action needed to advance the objective?",
      criteria: {
        click: "Choose only when a permitted click is the next required step.",
        fill: "Choose only when an approved text value belongs in a verified field.",
        select: "Choose only when an exact permitted option is available.",
        upload_file: "Choose only when a verified intended file field is present.",
        scroll: "Choose only when the needed target is not visible.",
        done: "Choose only when the objective is complete or requires human review.",
      },
    }),
    target: choice({
      instructions: "Which candidate is the correct target for the selected action?",
      criteria: candidateCriteria,
    }),
    target_exists: noul({
      instructions: "Does the page contain an eligible visible target that matches the objective?",
    }),
    action_matches_intent: noul({
      instructions: "Does the proposed action respect the objective and the supplied policy?",
    }),
    requires_review: noul({
      instructions: "Would executing the proposed action submit, send, publish, purchase, accept consent, or otherwise create a consequential external effect?",
    }),
  },
});
```

## Deterministic execution gate

Model confidence is never enough by itself. The candidate must still pass deterministic validation against the latest browser state.

```ts
const canExecute =
  assessment.answers.target_exists.noul >= 0.95 &&
  assessment.answers.action_matches_intent.noul >= 0.95 &&
  probabilityOfSelectedAction(assessment) >= 0.90 &&
  probabilityOfSelectedTarget(assessment) >= 0.95 &&
  selectedCandidate.pageVersion === latestObservation.version &&
  selectedCandidate.visible &&
  selectedCandidate.enabled &&
  !selectedCandidate.prohibited &&
  !isForbiddenByPolicy(assessment, selectedCandidate);

if (!canExecute || assessment.answers.requires_review.noul >= 0.70) {
  return routeToReviewOrRecovery(assessment);
}

await executeVerifiedCandidate(selectedCandidate);
```

The values above are examples, not production thresholds. Select them using held-out fixtures and observed false-positive cost.

## Post-action verification

Every mutation needs a deterministic postcondition. A high-confidence selection proves neither that the click landed nor that the application accepted the change.

```ts
await executeVerifiedCandidate(selectedCandidate);
const after = await observePage();

if (!verifyExpectedPostcondition({ objective, selectedCandidate, after })) {
  return {
    status: "failed",
    reason: "browser action did not produce the expected visible state",
  };
}
```

Examples:

- After a resume upload, the correct field visibly contains the expected file name.
- After a select action, the page exposes the expected selected option.
- After a field fill, the current document contains the approved value in the verified field.
- After a read-only navigation, the expected page section or result set is visible.

## Command Center use cases

### 1. Field matching

Given a normalized page and approved data, select the field actually corresponding to the objective. Example: choose "Resume/CV" rather than "Cover letter," "Portfolio," or an unrelated upload field.

### 2. Exact option selection

Choose an allowed option from a finite verified dropdown list. Code still verifies that the option is currently present and selected afterward.

### 3. Safe read-only navigation

Select among permitted tabs, filters, accordions, or search controls to find information without modifying external state.

### 4. Completion detection

Evaluate whether a page state satisfies a narrowly defined objective, then independently verify visible postconditions.

### 5. Danger detection

Identify a candidate likely to submit, send, publish, purchase, accept a legal statement, or otherwise create an external effect. Route such a step to explicit review.

### 6. Ambiguity routing

When candidates are close or no option has sufficient confidence, stop rather than guessing. Ask the Deep Agent for recovery, request user clarification, or fall back to manual control.

## Job-application constraints

Jev can help identify form fields and choose among verified options, but Command Center must not autonomously:

- Submit an application
- Click Next when it has external workflow consequences
- Accept legal terms, attestations, or consent
- Answer demographic, disability, veteran-status, compensation, work-authorization, or identity-sensitive questions without explicit user review
- Upload an unreviewed document
- Handle CAPTCHA or anti-bot challenges
- Traverse or mutate unknown cross-origin frames

## Two-tier Deep Agent architecture

```text
Deep Agent / LangGraph
  |-- owns the high-level objective and plan
  |-- produces approved form content
  |-- handles ambiguity, recovery, research, and clarification
  `-- receives structured observations and failures
            |
            v
Jev browser micro-loop
  |-- chooses one permitted action from a finite set
  |-- selects one current candidate control
  |-- scores semantic fit and review necessity
  `-- returns probabilities and confidence
            |
            v
Browser companion
  |-- validates freshness, frame identity, and policy
  |-- executes only permitted operations
  |-- captures a new observation and verifies postconditions
  `-- records an auditable trace
```

## Security and privacy

- Keep the TypeSafe API key server-side. Do not enable browser-side client configuration that exposes it to page users.
- Send the minimum redacted observation required for the decision.
- Exclude secrets, credentials, unrelated page content, uploaded-file bytes, and sensitive profile facts unless the narrow decision cannot be made without them.
- Record a candidate-set hash and redacted decision state rather than raw sensitive content where possible.
- Bind execution to short-lived server-approved commands and exact observation versions.

## First PR: shadow mode

Start with `feat(browser): add Jev-backed candidate ranking in shadow mode`.

- Construct safe candidate actions from current browser observations.
- Call Jev server-side to rank candidate action/target combinations.
- Preserve the existing browser behavior; do not let Jev control execution initially.
- Log distributions, selected candidates, candidate-set hash, page identity, policy outcome, latency, and observed result.
- Evaluate against existing synthetic application fixtures.
- Compare Jev recommendations to current behavior and manual review before enabling enforcement.
- Graduate only bounded read-only operations and low-risk `fill`, `select`, or `upload` classes after measured success.
- Keep Next, Submit, Send, purchase, legal, and sensitive flows behind explicit review.

## Metrics

Track:

- Candidate-set quality: whether the correct control was represented
- Selection accuracy by action and website/ATS class
- False positive rate for wrong-field, wrong-option, and unintended-write selection
- Abstention and fallback rate
- Postcondition success rate
- Latency per decision and full browser step
- Human-review agreement and reviewer override rate
- Distribution drift after model, prompt, browser companion, or site markup changes
