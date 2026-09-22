# engineering.md — Delivery and verification

**Parent:** [Tech Spec](tech-spec.md). **Revision:** 2026-09-21-r13. **State:** connected workspace, importer, full-page sections and contextual CRM inspection and appearance controls implemented locally; prior hardening is partly implemented and remains tracked below. Deep Agents on LangGraph, durable checkpoints, persistent conversations, job-lead discovery/evidence/drafts, local document ingestion and reviewed candidate facts are implemented locally. OpenAI, Gemini, Mistral and Cohere are selectable per profile. The user authorized autonomous implementation of the remaining workflows. This file owns delivery work, not an additional specification.

## Build objective

The current agent interview defines a first release of Copilot-style application assistance with user Next/Submit, outreach approved and sent through Command Center, and research scripts producing documents. Deep Agents on LangGraph is selected for an always-on backend; scripts run automatically in isolated task workspaces. Composio is central for Gmail, Google Calendar, Linear and Notion; external changes require review and Slack follows later. [Product Spec](../product/product-spec.md#first-agent-release--confirmed-interview-direction) owns the accepted boundary. The [technical draft](tech-spec.md#first-agent-release-architecture-draft) defines data ownership, module/async/Celery boundaries, skills/memory/handoff and MCP/token behavior. Continue one usable workflow at a time. Application preparation, browser v2 resume uploads, reviewed scoped memory and durable token/tool streaming are implemented locally. Current checks pass: 193 backend tests, 4 frontend unit tests, 9 companion browser tests, 29 workspace browser tests, contracts/style/types and the production build. The migration round trip includes existing partial-fill outcomes; downgrade preserves them as outcome unknown. Synthetic provider fixtures exercise actual streaming, steering and cancellation without paid calls. The local deployment still runs schema 0007_profile_facts; the test schema is 0011_reviewed_memory. Native control-pattern fixtures do not establish full live coverage of the five ATS targets. Next are reviewed external actions, isolated scripts/PDF exports and spending/recovery controls. Paid model quality and live employer flows remain unverified.

### Test and eval tooling

Confirmed tooling lives in [Tech Spec](tech-spec.md#testing-mocking-and-agent-evaluations): pytest test authoring/runner, pytest-mock for mocks/spies, DeepEval for agent-quality evals. Backend pytest/pytest-mock exists. DeepEval and any pytest-based consolidation of the existing TypeScript UI suites are planned, not delivered by this documentation update. Keep existing regression coverage working during transition.

Before building the new agent slice, define deterministic pytest cases for each domain/security/recovery boundary, identify model/provider mocks, and map DeepEval cases to the three confirmed workflows. Review eval dataset/version ownership, metric definitions, judge/model configuration, thresholds, cost and offline/paid CI separation; numeric choices remain open. Acceptance combines hard pytest correctness gates and independent quality results. Never install a second speculative runner or claim eval quality from mocked output.

### Agent release verification draft

The following is proposed verification work for the new architecture, not passing-test evidence or an approved implementation task list. Reuse the current PostgreSQL, MCP and synthetic browser test infrastructure. Test the business outcome and failure boundary, not framework internals or prompt wording.

| Area | Required evidence before the relevant slice is accepted |
| --- | --- |
| Schema and ownership | Actor-scoped references; immutable source/output versions; profile proposal versus approved fact; task state separate from run state; stale revisions rejected |
| Harness compatibility | Pin compatible Deep Agents/LangGraph/checkpointer/provider versions; prove existing MCP/domain tools through a real worker with mocked model; preserve current capability and receipt guarantees |
| Async tools | Concurrent tool calls retain distinct invocation/idempotency identities; sessions and event loops are not shared incorrectly; provider I/O holds no domain transaction |
| Queue and recovery | Duplicate message, lost enqueue, worker death, timeout, expired lease, stale completion, restart and broker redelivery; verify bounded attempts and no duplicate external effect |
| Questions and checkpoints | Pause releases worker capacity; restart preserves the exact question; duplicate/stale answer is rejected; parallel subagent interrupts resume only the addressed branch; crash between saver and ledger commits is reconciled |
| Conversation continuity | Lead and specialist messages retain the selected task/opportunity scope after refresh/restart; unrelated work stays separate; two tabs cannot start concurrent root writers for one checkpoint; visible messages preserve author/sequence/artifact references |
| Active-work steering | New instructions persist immediately and are applied at a safe boundary; messages racing completion are consumed once in the same session; restart preserves received/applied position; changed drafts require fresh approval; completed or ambiguous external effects are not erased |
| Approved actions | Reviewed payload/account/version matches execution; edit/revoke/expiry/target drift stops dispatch; ambiguous Gmail/event/task/page writes enter reconciliation; cancellation during provider I/O never claims rollback |
| Skills and memory | Effective prompt validates before enqueue; revision-pinned progressive skills survive resume; scoped retrieval reaches relevant active notes; unapproved/rejected proposals never become reusable memory; editing invalidates prior proposal review; revocation removes future retrieval; legacy notes preserve provenance; memory cannot grant permissions or override profile facts |
| Handoffs and tokens | Parent supplies bounded context and enforceable scope; specialist returns artifact/evidence references; offloaded output survives resume; compaction preserves constraints and missing questions; shared budget holds under parallel work |
| Spending controls | Monthly/per-task reservations hold under concurrent specialists and retries; partial results survive exhaustion; late/unknown provider usage is explicit; no automatic purchase/top-up; no numeric budget inferred from accepting the policy |
| Browser experience | Greenhouse, Lever, Ashby, Workday and iCIMS each require synthetic fixtures for agreed fields/uploads; preserve existing values and edits made during generation; explicit replacement rejects changed targets; control-aware emptiness, dynamic fields, stale page, disconnect/reconnect and partial fill; no Next/Submit from the agent in this release |
| Research sandbox | Selected inputs only, bounded execution, cancellation/timeout, no provider secrets, artifact collection and restart/cleanup; generated document retains source provenance |
| Research deliverables | Editable cited documents use shared immutable versions; source links survive editing/export; PDF corresponds to the selected version; Notion publication binds that version/target; failed export/publication preserves the local document |
| Provider contracts | Explicit Composio action/account filters; schema/version changes; expired connections, rate limits and partial failures. Mock contracts first; record live-provider verification separately |
| Dashboard/system of record | Refresh/restart/reconnect reconstructs visible messages, delegation, artifacts, questions, reviews and receipts; counts match rows; actor isolation; paginated activity; stale external snapshots labelled; no dashboard-only completed state |
| Single-server operations | Existing Docker topology survives process/server restart with durable records and artifact bytes; prove restore from backup, bounded worker/resource contention and operator recovery; document host, TLS, secrets and update/rollback procedure before deployment |

Proposed sequence for review: prove Deep Agents/checkpoint/MCP compatibility; establish durable sessions/questions/context and facts; deliver one complete reviewed outreach path using on-request relevant Gmail searches in one account; add the requested Calendar/Linear/Notion actions through the same reviewed-action contract; deliver extension-generated filling/uploads; deliver isolated scripts and research documents. Each slice includes its persisted activity and dashboard/inspector projection, rather than postponing visibility to a final observability phase. This orders first-useful slices without removing named capabilities. Budget, browser field coverage and hosting decisions may change the sequence. The runtime/conversation slice is verified: 89 backend tests in make check and 13 workspace browser tests after UI fixes. Remaining slices retain the review and verification boundaries above.

Browser platform acceptance matrix (required by AR-16; no new platform verification performed in this interview):

| Platform | First-release requirement | Evidence still needed |
| --- | --- | --- |
| Greenhouse | Required | Representative forms, supported controls, resume upload and per-page continuation |
| Lever | Required | Representative forms, supported controls, resume upload and per-page continuation |
| Ashby | Required | Representative forms, supported controls, resume upload and per-page continuation |
| Workday | Required | Representative employer form variants, supported controls, resume upload and per-page continuation |
| iCIMS | Required | Representative employer form variants, supported controls, resume upload and per-page continuation |

All five retain the same shared profile/answer/approval contracts and manual Next/Submit boundary. An incremental build order does not remove a platform from the release requirement. Track unsupported variants and manual completion explicitly; no universal form-support claim follows from a platform name.

### Agent benchmark plan draft

**Status: proposed plan for review, not an executed benchmark.** AR-23 accepts hard spending caps and defers dollar values until this plan is reviewed. No paid model/provider/sandbox run is authorized by accepting the budgeting mechanics. Use synthetic profiles, resumes, email threads and application forms; the user's selected real resume is a production input, not a committed fixture.

Evaluate the selected Deep Agents architecture against the three required workflows. Do not turn this into an open-ended competition between frameworks after AR-15 selected the harness. Compare model/configuration/context choices only where they could improve a defined outcome. Pin fixture, prompt/skill, model, tool/schema, harness and pricing revisions for each measured run.

| Scenario | Quality gate | Measurements |
| --- | --- | --- |
| Form assistance on each required platform | Known facts filled correctly; unsupported facts become grouped questions; existing values/racing edits preserved; explicit replacement targets the correct value; selected resume/version used; no Next/Submit | Correct/incorrect/omitted fields, unsupported widgets, source-grounding failures, time to first useful fill and full result, model/tool tokens/calls, human intervention |
| Contextual outreach | Relevant allowed thread/context selected from one account; typed draft retains sender/recipient/thread/attachments; statements grounded; exact reviewed version controls execution | Retrieval relevance, draft-quality rubric, unsupported claims, context volume, latency and estimated/observed cost |
| Company/interview research | Saved editable artifact with usable source citations; separate fact/inference/unknown; optional script output matches its inputs; no loss on publication failure | Coverage and freshness rubric, citation correctness, script success and resource use, time to saved draft, artifact size and cost |
| Recovery and concurrency | No cross-task/actor context leak; duplicate delivery/resume does not duplicate effects; stale workers are fenced; review/memory/budget boundaries hold | Recovery time, duplicate effects, lost questions/events/artifacts, worst reserved/actual spend under concurrency |

Stage A, after implementation of the relevant slice: run pytest-authored deterministic domain, worker and MCP tests plus browser regression fixtures locally with paid model/provider boundaries mocked. Exercise the failure cases in the verification map. Record measured local latency separately from model/network latency; mocks cannot establish output quality or live provider compatibility. The benchmark must fail on unauthorized effects, unsupported personal claims in fixture-grounded answers, loss of user edits or cross-owner access, rather than averaging these failures into a quality score.

Stage B, before any paid trial: build a costed run sheet with selected model/configuration candidates, scenario/sample counts, maximum input/output tokens, tool-call and retry ceilings, sandbox startup/runtime limits, current provider prices, expected cost range and a hard total experiment limit. Use provider token counting/usage where available and conservative bounds for unknowns. Review this concrete plan and set its dollar allowance before running it. Do not estimate a monthly bill from an invented number of daily applications or research jobs.

Stage C, only after that trial allowance is supplied: run the DeepEval suite on a small fixed synthetic set, retain structured outputs and usage, and manually assess the grounding/style/citation rubrics. Separate deterministic failures from model-quality failures and classify slow steps (queue, context lookup, model, tool, sandbox, user wait). Report individual results and observed range; a small sample does not justify a production p95 claim. Repeating a run uses its own planned allowance and preserves earlier outcomes rather than silently retrying until a favorable sample appears.

Stage D: propose per-task caps and a monthly cap using measured cost ranges, retry/headroom assumptions and the user's expected workload. Explain which tasks would pause under the proposal. Numeric caps are then explicit configuration with the chosen billing period/timezone, not hidden defaults in prompts. Repeat the relevant benchmark when a model, prompt/skill, tool catalog, retrieval strategy or sandbox changes materially; avoid rerunning unrelated scenarios without a reason.

The benchmark report should pair outcome quality with cost and latency. Token reduction only counts as an improvement when evidence coverage and task correctness remain acceptable. Paid trial results still do not establish real authenticated coverage of every employer form; each named platform needs its own declared verification evidence.

The broader objective remains the autonomous loop: title/URL/CSV and reviewed Notion leads → discovery/qualification → source-backed material and tailored answers → browser fill/upload/submission → confirmation or reconciliation → follow-up. The roadmap below describes that later full workflow; automatic submission is not a gate for the newly selected first Copilot release.

## Full workflow roadmap

This is the broader autonomous-workflow sequence, not the build plan for the new agent release or a list of entirely unbuilt components. Current maintenance work is [accepted workspace hardening](#accepted-workspace-hardening). Reuse implemented foundations before extending them. The initial Composio app set belongs to current agent planning; full synchronization scope remains separate from enabling selected app actions.

| Stage | Work package | Exit evidence |
| --- | --- | --- |
| E-00 Decisions | Set target, connection, campaign, answer, outreach and budget rules; choose initial site/account scope | Product answers and accepted scope, with unresolved items explicit |
| E-01 Browser extension | Build on the paired manual-fill companion; prove requested AgentBrowser orchestration with a synthetic multipage application fixture | Resume upload, tailored fields, redirects, interruption, one observed submission and supported invocation/completion contract |
| E-02 Foundation | Reuse API/web/worker, Clerk, migrations, structured artifacts, ledger and audit; add file-byte storage and recovery contracts when needed | Existing foundation checks plus isolated backup/restore demonstration before claiming recovery support |
| E-03 Entry and seed | Reuse the operator CSV/cached-Notion importer; add title/URL capture and portal staging/review | Reviewable mapping/provenance, conflicts, replay and preserved later edits; operator import alone is not a portal workflow |
| E-04 Discovery | Defined target search; legitimacy/fit/connection reasons; research and budgeted optional enrichment | Accepted/rejected/unknown examples with sources and clear quota/failure handling |
| E-05 Materials | Candidate facts/answer library, artifact/document versions, writer/review, package assembly | Tailored supported output, missing-fact cases, immutable version references |
| E-06 Execution | Campaign authorization, browser runner, events/receipts, stop and unknown-outcome reconciliation | Controlled end-to-end automatic application without duplicate replay |
| E-07 Pilot/recovery | Bounded configured real-site pilot and failures; monitor intervention, coverage and outcome | Account/site/material scope verified, exceptions actionable, restore cannot replay submissions |
| E-08 Expansion | More sources/portals, full archive support, Google sync, broader follow-up and later relationships | New capabilities retain the same contracts and regression evidence |

Some foundation work can accompany the spike; do not promise site coverage before checking it. No dates or effort estimates are assigned until the product rules and feasibility boundary settle.

## Ticket and contract requirements

Every implementation ticket names the user outcome, P requirement IDs, prerequisites, exact files/modules, migrations/indexes/constraints, API/tool schema, state transitions, permissions, failure/retry rules, synthetic fixtures and acceptance scenarios. Identify operational rollback/restore separately from a migration downgrade. Record selected package/runtime versions and reasons in the accepted technical decision log.

Follow [Tech Spec](tech-spec.md) for the selected stack, model/controller boundary, immutable artifact lifecycle and separation of business tasks from execution leases. Redis/Celery already exists. Do not introduce a replacement runtime, persistence layer or auth provider through a cleanup task.

Implemented layout: `apps/api/src/command_center/{api,core,db,integrations,agents}`, `apps/api/migrations`, synthetic `apps/api/tests`, connected `apps/web`, `apps/extension`, versioned `agents/`, and root Compose/Makefile/scripts. The operator import lives in `scripts/import_workspace.py`. Add directories only for concrete behavior.

The worker, companion, agent runtime and CRM interface are implemented. General artifact byte storage and autonomous campaign/application execution are later slices. Preserve the pictures in `mockups/`; the current UI's accepted interaction fixes and approved simplification are recorded in [Design Spec](../design/design-spec.md).

## Verification matrix

| Scenario | Required observation |
| --- | --- |
| Entry modes | Title, URL, CSV and Notion seed representations produce correct typed work and provenance |
| Identity collision | Same name cannot merge people; conflicting strong identifiers remain reviewable |
| Malformed/repeated source | Unknown schema/rows are accounted for; replay does not duplicate records; later edits survive |
| Qualification | Hard exclusions cannot be compensated by a score; legitimacy and connection uncertainty remain separate |
| Truthful answer | Narrative is grounded; absent personal facts are surfaced; no invented experience/eligibility/pay values |
| Version drift | New document/fact/package invalidates inappropriate prior approval; history remains exact |
| Stale worker | Reclaimed lease rejects stale completion; unique work/business keys handle replay |
| Browser/extension | One component owns form writes; unsupported extension or redirect produces a defined fallback/exception |
| Submission crash | Intent without confirmed result becomes reconciliation; no blind second click/submission |
| Permission/injection | Wrong actor/account, expired/revoked scope and malicious source instructions cannot grant authority |
| Provider exhaustion | No-match, denied, rate-limited, exhausted and failed are distinguishable; budgets stop spend |
| Backup restore | DB plus artifacts verify in isolation; execution stays disabled and consumed grants stay consumed |
| UX | Keyboard paths, evidence, missing inputs, progress, partial results and recovery are usable |

Run meaningful unit, contract, integration and browser checks appropriate to the implemented slice. Use synthetic contacts, resumes, mail, exports and portal fixtures. Future live pilots are separate from committed test fixtures.

Root [README](../../README.md#checks-and-migrations) owns runnable commands. Current `make check` includes Ruff/format/mypy, PostgreSQL pytest, frontend lint/typecheck and the production Next build. It now also runs non-watching Vitest component tests. `make check` also runs `test:browser` for the companion; `test:workspace` remains an explicit check of real UI components in an isolated synthetic Vite fixture. The fixture mocks Next routing, Clerk and the API; real authenticated workspace coverage remains T8.

## Operations and delivery evidence

Document startup, health/readiness, migration/upgrade, backup/restore, connector revoke/re-pair and browser halt/reconcile procedures. Monitor queue age, lease health, failed/paused work, disk/backup state, provider usage and application outcomes using redacted IDs rather than raw personal content.

Before handing off an implementation, record changed files, schema/API additions, commands/results, fixture demonstration, deliberate deferrals and remaining risks. Use the root [AGENTS.md](../../AGENTS.md) for coding-tool and workspace instructions. Keep session handoff notes local and untracked.

## Delivery evidence

Dated evidence, with historical checks distinguished from this implementation pass:

| Work | Recorded validation on 2026-09-21 | Limits |
| --- | --- | --- |
| Connected workspace | 46 backend tests; lint/types/build; schema drift; Docker startup; real MCP/HTTP execution with mocked model; 3 companion browser tests; synthetic desktop/mobile inspection | Paid OpenAI/Composio execution was not tested; no autonomous application or outreach |
| Frontend engineering review | Four synthetic component/helper probes reproduced draft loss, retargeted reviews, identity-independent cache reuse and duplicate writes after manual retry; production manifest inspected | Defect evidence, not passing regression coverage; no live Clerk account switch or latency/heap benchmark |
| UI simplification and appearance (current pass) | `make check`: 50 backend + 4 frontend unit tests, lint/types/production build; 6 synthetic workspace browser tests; desktop/mobile visual inspection | Browser tests mock Next/Clerk/API; not a live-provider or exhaustive accessibility pass. All eight mode/accent combinations pass primary/body/muted text contrast checks. |
| Operator importer and batch company labels | `make check` passed with 50 backend tests; synthetic import/replay/owner-isolation and >100-company label cases; applied/replay reports and browser/API verification retained privately | Local cached sources, not live Notion synchronization; private source/report details are excluded here |

Raw prior evidence is under ignored `.local/qa/` and `.local/imports/`. Logs and images can contain private data; do not commit them. No Supabase or production deployment is claimed. Record current-session checks in local, untracked handoff notes.

## What already exists

Reuse Clerk forwarding, the shared API client, TanStack Query, official shadcn/AI Elements, actor-owned API queries, request receipts, row revisions and bounded list endpoints. Existing Activity/Records pagination supplies the Memory pattern. The accepted changes below need no new application runtime or storage architecture; Vitest/RTL/jsdom are approved development test dependencies only.

## Accepted workspace hardening

All nine remedies below were accepted in the earlier 2026-09-21 engineering review: T1–T5 individually; T6–T9 under the user's instruction to take all remaining recommendations. The approved outcomes remain unchanged. The UI work implemented the T7 test foundation, the record-editor portion of T1 and the identity/cache boundary in T3. Artifact review targeting, profile draft behavior, retained write intents, secondary panels and Memory pagination still need their listed remedies. Local implementation is not release approval.

The prior detailed review and synthetic QA plan remain at `~/.gstack/projects/command-center/*-eng-review-20260921-64621.md` and `*-eng-review-test-plan-20260921-64621.md`. This committed document owns the current task list; those private files preserve historical evidence, not a competing plan.

## Implementation Tasks

Each task derives from an accepted finding. Estimates are rough planning estimates, not measured runtime. P1 fixes block release; P2 work should land with the same implementation effort. The subsequent user-approved UI implementation is included in the status notes below.

- [ ] **T1 (P1, human: 3–5h / Codex: 30–50min)** — Preserve record/profile drafts and original revisions. Source: finding 1. Files: `record-detail.tsx`, `record-editor.tsx`, `settings.tsx` and their G1 tests. Verify dirty refetch, 409, reload/discard and pending-save races. **Partial:** record editor now pins the opening baseline and retains edits made during save; two maintained tests cover these cases. Profile behavior and remaining G1 cases are pending.
- [ ] **T2 (P1, human: 2–3h / Codex: 20–35min)** — Pin artifact review content, reason and submitted version. Source: finding 2. Files: `record-detail.tsx` and G2 tests. Verify v2 arrival never retargets v1 approval.
- [ ] **T3 (P1, human: 3–5h / Codex: 30–60min)** — Scope private workspace/cache state to authenticated identity. Source: finding 3. Files: `providers.tsx`, `app/layout.tsx`, workspace layout if needed, G3/G8 tests. Verify same-user reuse, sign-out, actor switch and late-response isolation. **Partial:** identity-keyed QueryClient/subtree, retirement and unresolved-auth withholding are implemented; two maintained tests cover unresolved identity and A→B with a late query. Remaining G3/G8 cases are pending.
- [ ] **T4 (P2, human: 3–5h / Codex: 30–50min)** — Retain unambiguous keys for receipt-backed write intents. Source: finding 4. Files: `lib/api.ts`, a small retained-key helper, applicable workspace mutation callers and G4 tests. Verify one server result after lost response plus manual retry, new keys for changed intents and confirmed-success reset.
- [ ] **T5 (P2, human: 2–3h / Codex: 20–35min)** — Add complete states and local retry to review/step/command panels. Source: finding 5. Files: `record-detail.tsx`, `agents.tsx`, `browser.tsx`, reusable primitives if needed, G5 tests. Verify each panel independently through empty/error/stale/recovery.
- [ ] **T6 (P2, human: 1–2h / Codex: 15–25min)** — Paginate memory management. Source: finding 6. Files: `memory.tsx`, G6 tests. Verify note 101 and last-item archive offset repair.
- [x] **T7 (P2, human: 2–4h / Codex: 25–45min)** — Establish frontend behavior-test infrastructure and integrate it into checks. Source: finding 7. Files: `apps/web/package.json`, lockfile, `vitest.config.ts`, test setup, `src/**/*.test.{ts,tsx}`, `Makefile`. Verify independent Vitest/Playwright discovery, non-watching execution, and failing repros becoming passing tests alongside T1–T6.
- [ ] **T8 (P2, human: 3–5h / Codex: 35–60min)** — Test the authenticated forwarding boundary and critical real-provider journeys. Source: finding 8. Files: route-handler test, `tests/workspace-auth.spec.ts`, `tests/workspace-edit.spec.ts`, isolated test fixture/setup documentation and Playwright config as needed. Verify rejected requests never reach upstream, credentials remain server-side, and real synthetic A/B sessions cannot retain each other's workspace.
- [ ] **T9 (P2, human: 2–4h / Codex: 25–45min)** — Split ordinary screens from conditional rich rendering. Source: finding 9. Files: section page/client dispatcher, `activity.tsx`, extracted ActivityList, `record-detail.tsx`, `agent-response.tsx`, `agents.tsx`, G9 browser test. Verify production chunk/network reduction, on-demand feature recovery and unchanged safe rendering.

- [x] **T10 (P2, human: 1–2d / Codex: 1–2h)** — Context-preserving CRM workspace. Source: direct user direction D1 and approved preview. Files: context pane, shell, records/detail, overview and workspace browser tests. Preserve parent selection/search/tab state, bounded nested history, local create/edit, errors, responsive layout and focus.
- [x] **T11 (P2, human: 3–5h / Codex: 30–60min)** — Browser-local appearance. Source: direct user request D2. Files: Appearance/provider, layout/CSS, downloaded Kibo switcher, shadcn Popover and workspace tests. Verify Light/Dark/System, four accents, storage/device changes and readable contrast.

Final implementation verification: non-watching frontend unit tests, Playwright against the appropriate target, and `make check`. Configuration-dependent real-provider omissions must remain distinct from passes.

## Test coverage and failure modes

Two systemic test gaps were originally found: frontend state/API-client behavior (finding 7) and the Next.js/authenticated integration boundary (finding 8). The nine scenario families below organize their requirements, including performance remedy 9. They are not nine additional findings. No line/branch coverage percentage was measured; passing backend and extension tests do not establish custom workspace coverage.

```text
Clerk state
  +-- unresolved/signed out --> private workspace withheld             [G3, G8]
  +-- resolved identity ----> identity-owned QueryClient + UI subtree
       +-- same identity --> reuse cache; ordinary navigation           [G3]
       +-- changed identity --> retire old subtree/cache/late responses [G3, G8]
       |
       +-- record/profile editor: draft + baseline revision             [G1]
       |    +-- refetch --> preserve draft and baseline
       |    +-- submit --> retained operation --> 409: keep draft
       |    +-- success --> reset baseline without erasing newer input
       |
       +-- artifact: pinned version + decision + reason                 [G2]
       |    +-- newer version --> notify, require deliberate switch
       |    +-- submit --> pinned version ID --> immutable review
       |
       +-- write intent --> method/target/body + retained request key    [G4]
       |    +-- lost response/manual retry --> same key
       |    +-- changed intent/confirmed success --> new operation
       |    +-- api() --> Next forward --> owned FastAPI --> receipt     [G7, G8]
       |
       +-- history panels --> loading / empty / success / error         [G5]
       |    +-- refresh failure --> retain data + visible stale warning
       |    +-- retry --> only this query --> recovery
       |
       +-- memory page --> offset + total --> next/edit/archive         [G6]
       |    +-- last item removed --> clamp offset --> reachable page
       |
       +-- ordinary screen --> lightweight content                      [G9]
            +-- rich content requested --> lazy chunk
                 +-- success --> safe renderer
                 +-- failure --> clear recovery; preserve surrounding UI

Existing tested contracts (not substitutes for the missing client tests):
  [***] FastAPI same-key replay, changed-payload and stale-version 409
  [***] FastAPI actor ownership and cross-owner link rejection
  [ **] FastAPI version-specific review history
  [***] Extension fill once, changed-field and navigation rejection
Legend: *** behavior + edge/error; ** happy behavior. G1/G3 now have initial maintained component tests; G2/G4–G9 still need
their specified coverage. Historical G1–G4 diagnostic evidence remains valid history.
```

| Family | Test placement and required assertions |
|---|---|
| G1 Draft lifecycle | `src/components/workspace/record-editor.test.tsx`, `settings.test.tsx`: initial data, field validation, dirty refetch, original expected_version, 409 retaining input, explicit reload/discard, save success and newer edits made during a pending save. Reuse the record reproduction as a failing test before fixing it. |
| G2 Reviewed version | `record-detail.test.tsx`: v2 arriving during v1 review cannot change displayed/submitted target; explicit switch resets or isolates the reason; missing pinned version disables submission with an explanation; failed/successful review stays attached to its target. |
| G3 Identity ownership | `src/components/providers.test.tsx`: unresolved auth, same-user navigation, A→B, sign-out→sign-in, equal revisions across actors, delayed old queries and mutation callbacks cannot affect B. Avoid shared module-global clients. |
| G4 Operation and API client | `src/lib/api.test.ts`, retained-key helper tests: successful GET/write, validation and 401 errors, one automatic retry for transport/5xx, abort, malformed response; committed-but-lost response followed by manual retry uses the same key, rapid duplicate clicks, changed method/body/target, unambiguous signatures and fresh key after success/new intentional action. Unmount/sign-out retires local intent; persistence across navigation is not promised. |
| G5 Secondary panels | `record-detail.test.tsx`, `agents.test.tsx`, `browser.test.tsx`: each panel gets pending, empty-200, initial 500/timeout, cached results plus failed refresh, visible stale state and local retry recovery. Unrelated data remains usable. |
| G6 Memory navigation | `memory.test.tsx`: 0/1/100/101 notes, totals and offsets, note 101 reachable/editable, previous/next, archive last item of final page and failed-page retry; rapid page changes cannot display a mismatched page. |
| G7 Forwarding | `src/app/api/backend/[...path]/route.test.ts` in Node: missing user/token, allowed/rejected origin, invalid path, multi-byte body-size boundary, forwarded method/query/body/request key, server-only credentials, no-store response, redirect rejection, upstream status/request ID and timeout. Rejected requests must never reach upstream. Match the existing 40-second timeout using controlled timers, not a real wait. |
| G8 Authenticated journey | `tests/workspace-auth.spec.ts`, `tests/workspace-edit.spec.ts`: real development Clerk sign-in and identity transitions; create/edit/refetch/conflict/recover, review v1 while v2 arrives, ambiguous-response retry creates one result. Use two synthetic actors and isolated data; no production auth bypass. Confirm both UI and API ownership. |
| G9 Conditional rendering | `tests/workspace-bundle.spec.ts` against a production build: ordinary screen excludes renderer chunks; artifact/agent feature loads them on demand; loading and chunk-failure recovery; safe Markdown, code, math and diagrams. Record cold-transfer comparison rather than assert hashed chunk names. |

These are regression-prevention requirements for existing defects documented before the initial commit, not regressions introduced by this documentation cleanup. Git now has the `66eddc1` baseline. No prompt, model policy or tool definition changes are proposed, so no new LLM quality eval is required. Existing backend mocked-model/MCP tests remain relevant.

## Failure modes

Current handling and tests are distinguished from the accepted plan. Six failure families were originally critical. The new identity boundary supplies G3 handling and initial tests, leaving five families with unhandled silent outcomes somewhere in their scope; G1 remains open for profile drafts. Full real-provider confidence still depends on G8.

| Path | Realistic failure | Current maintained test | Current handling / visibility | Accepted protection |
|---|---|---|---|---|
| G1 draft | Refetch discards input | Record baseline/race tests now exist; profile test pending | Records protected; profile remains silent — **critical** | Stable draft/baseline, explicit conflict/reload UI, G1 |
| G2 review | New version receives an old reason | No | None; silent — **critical** | Pinned immutable target and explicit switching, G2 |
| G3 identity | Old actor's cached content survives transition | Two component tests now cover withholding and A→B late response | Identity boundary implemented; real-provider paths unverified | Identity-owned subtree, retirement and late-response isolation, G3/G8 |
| G4 retry | Committed write repeated after response loss | Backend same-key test only | Error appears, but manual retry gets a new key and duplicate result is unmarked — **critical** | Retained request identity and receipt-backed replay, G4 |
| G5 panel | History fails to load or refresh | No | Missing panel states; blank/stale outcome is silent — **critical** | Local error/stale status and retry, G5 |
| G6 memory | Note 101 cannot be reached | No frontend pagination test | Truncation unmarked; no navigation — **critical** | Pagination, totals, offset repair, G6 |
| G7 forwarder | Missing auth, invalid input, timeout or redirect | No direct Next test | Existing explicit 4xx/503 and no-store response; not silent | Lock down current behavior and token boundary, G7 |
| G8 integration | Provider transition differs from the synthetic probe | No real Clerk E2E here | Server protection exists; client risk captured by G3 | Real development-provider test, isolated A/B actors |
| G9 lazy boundary (planned) | Chunk load fails after opening rich content | New path, not implemented | Must be explicit in the implementation | Loading + clear recovery boundary, surrounding state retained, G9 |

Inline diagram comments belong only at the identity lifecycle boundary and retained-operation helper if their transitions are not clear from code. Keep detailed diagrams in the tests/review plan. No existing inline ASCII diagrams require repair; no backend model state machine changes are proposed.

## Implementation order

Sequential implementation, no parallelization opportunity: the accepted tasks share the workspace components, identity boundary and mutation helper. Order: T7 test foundation → T3 identity → T4 operation keys → T1 drafts → T2 reviews → T5 panel states → T6 memory → T8 integration → T9 production bundle verification. Each remedy includes its tests. UI implementation remained sequential in this workspace; no parallel agents were used.

The user approved D1 and requested D2, so T10/T11 are implemented over existing owned API contracts. Their inspector URLs use native history integrated with Next hooks; frame count is bounded, parent content stays mounted, and smaller screens use Radix focus containment. The synthetic browser suite covers this presentation boundary. The record editor and identity provider fixes are dependencies of reliable context retention and remain separately tracked under T1/T3.

## NOT in scope

- Completing every prior hardening task in the UI slice: status is explicit above; pending work is not claimed as shipped.
- Product decisions Q5–Q10 and autonomous submission/outreach: remain in Product Spec.
- A runtime migration, generic service/repository layer or replacement component system: reuse the selected implementation.
- Full backend/security/performance re-audit and paid-provider execution: prior evidence has explicit limits.
- Notion publication, production deployment and private source-data changes: this is local documentation and UI work.

No new deferred TODOs were proposed; all accepted implementation work is above. No separate TODOS.md is needed. New navigation and appearance paths have maintained synthetic checks; broader auth and mutation risk remains as listed. LLM prompts/tools are unchanged, so no new eval scope is required.

## Review findings — consolidation

- Architecture: one documentation finding, confidence 10/10. The old “Worker, companion, agent runtime, CRM operations ... are later slices” contradicted the implemented modules and migration history. Reconciled status and the current data-flow diagram; selected architecture unchanged.
- Code quality: one documentation finding, confidence 10/10. Approved T1–T9 lived in a chronological handoff/private artifact while the delivery plan still described the foundation. Centralized the existing tasks here and made other documents link to their owner.
- Tests: one documentation finding, confidence 10/10. `Makefile` has `check: lint test` followed by the production build; `apps/web/package.json` originally only had `test:browser`. T7 now adds Vitest and a separate synthetic workspace browser target. G1/G3 coverage started; real-provider and remaining mutation coverage remain open.
- Performance: no new issue found in the consolidation. Retain T9 and its production-request measurement requirement. Historical manifest byte counts are dependency sizes, not measured transfer or latency gains.

Suppressed findings: no new speculative code findings. Previously unverified provider-connect replay and real Clerk account-switch behavior remain unverified; do not promote them to a demonstrated live exploit. Five prior failure families still have unhandled silent outcomes in their remaining scope, as mapped above. T3 has handling and initial component coverage, but real Clerk transitions remain unverified.

## JobPilot reuse assessment

Read-only comparison against neighboring `../jobpilot`, commit `68a72c71`, on 2026-09-21. Inspected its architecture, package manifests, theme/provider, workspace tabs/attention strip, application evidence/history, resume consistency helpers, tailoring contracts and license. The checked-in `docs/images/dashboard.png` is a terminal report, not proof of the current web UI. No JobPilot services were started and no source or user data was copied.

| Idea | Source in JobPilot | Fit here / disposition |
| --- | --- | --- |
| One workspace with local tabs and URL state | `apps/web/src/components/features/workspace/workspace-view.tsx` | Adopt the continuity principle in T10. Reuse our Next/TanStack/shadcn components; do not import MUI. |
| Surface only work that needs attention | `workspace/dashboard/attention-strip.tsx` | Use a restrained tasks-first overview now. A dedicated review queue needs an owned API contract; do not fabricate counts. |
| Exact evidence for each application | `applications/submission-details.tsx`, `application-detail.tsx` | Strong future design: show the actual artifact version used, posting snapshot and activity beside the opportunity. Current artifacts already have one immutable lifecycle; do not introduce separate mutable resume tables. Submission evidence awaits the application slice. |
| Check profile/resume discrepancies | `apps/api/src/modules/resume/consistency.ts` and its tests | Candidate for adapting pure validation rules and synthetic cases into Python models when structured candidate facts land. Normalize carefully for international contact data; do not copy the current US-phone heuristic as universal truth. |
| Reuse a suitable variant and record truthful edits | `plugin/skills/tailor-resume/SKILL.md`, `resume/variants/tailor-variant.ts` | Useful future drafting policy. Retain immutable version review and our authority rules. Imported prompt instructions are reference material, not execution permission. |
| Single workspace event subscription | `workspace-view.tsx`, shared SSE contracts | Consider only after measured polling cost or freshness requirements justify an API event contract. Current bounded polling remains. |

**Recommendation:** retain Command Center and selectively adapt these ideas. JobPilot is not a drop-in frontend or API package: its web uses MUI 9, its backend uses Bun/Elysia/Prisma with separate shared contracts/auth, and local agents use a .NET PTY host with Claude Code/Codex. Direct use beside this app would require explicit identity mapping, record ownership, idempotent synchronization and one execution owner. Replacing this app would also be a data/runtime migration. Neither is needed for the requested UI.

The inspected JobPilot root license is MIT; any future substantial source copy must preserve its notice, and nested assets/skills require their own license check. Current reuse is conceptual only. No new integration task is accepted or deferred silently; this assessment supplies options for the future product slice.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
| --- | --- | --- | --- | --- | --- |
| Engineering | `/plan-eng-review` + approved UI implementation | Contract consolidation, architecture, tests, performance | 1 current + historical review | ISSUES OPEN | Three documentation inconsistencies reconciled; T7/T10/T11 implemented; T1/T3 partial; five remaining critical failure families |
| Design | `/plan-design-review` + D1/D2 | Persistent context, fewer actions, appearance | 1 current + historical review | CLEAN DESIGN PLAN | Design contract 4/10 → 8/10; directions resolved |
| Outside | Configured plan-review provider | Independent challenge | 0 completed | DISABLED | No outside or substitute-agent coverage |

**VERDICT:** The approved UI slice and documentation are locally reviewable and tested. Remaining engineering hardening means the full workspace is NOT CLEARED for release.

**NO UNRESOLVED DECISIONS** for this slice. Pending implementation and Product Spec Q5–Q10 remain explicit; the JobPilot recommendation is an assessment, not an approved migration.

## Quick Tech Debt Wins

Prerequisite cleanup for the next agent architecture, implemented in the existing runtime:

- **Environment ownership:** root `.env.example` is the single template; `make env-sync` migrates compatible legacy web settings and generates a minimal web projection. Conflicts fail without overwriting values or logging secrets. Compose uses explicit per-service settings; `make env-check` detects drift.
- **Browser contracts:** Python owns HTTP and versioned extension message schemas. `make contracts` generates API types and ahead-of-time extension validators. Popup/API responses and content-script messages are checked before use; `make contracts-check` rejects drift.
- **Readiness:** PostgreSQL executes an authenticated query; Redis must return PONG. Host and container workers/beat wait for database, Redis, API and configured mock health URLs. The test-only `mock-web` Compose service has a healthcheck; Playwright independently starts and waits for the same synthetic server. Research services remain in the existing external stack.
- **Agent boundaries:** coding-assistant instructions stay in `AGENTS.md`, executive directives in `agents/directives/`, and execution settings in `agents/profiles.toml`. Runs pin both directives and skills, and validate their combined instruction size before enqueue.

Validation: `make check` includes generated-contract drift, backend style/types/tests, frontend lint/types/unit tests, synthetic extension browser tests and the production build. These checks do not establish paid-provider execution or new autonomy readiness.

### Navigation clarification validation

The sidebar now uses ordinary section routes; contextual body record actions retain their inspector behavior. Eight synthetic workspace browser checks pass, including full-page section navigation at 1600px and 390px, nested body-record context, mobile focus return and appearance. These update the existing TypeScript Playwright suite; they do not claim a pytest browser migration or live Clerk verification. Design Spec DS-01–DS-04 owns acceptance.
