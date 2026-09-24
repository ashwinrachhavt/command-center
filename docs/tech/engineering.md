# engineering.md — Delivery and verification

**Parent:** [Tech Spec](tech-spec.md). **Revision:** 2026-09-24-r38. **State:** connected workspace, importer, persistent conversations, application assistance, reviewed actions, scoped connected context, research/PDF jobs and spending/recovery controls are implemented locally. Workspace state, retry and loading remedies are implemented; authenticated provider QA remains deferred to the user. OpenAI, Gemini, Mistral and Cohere are selectable per profile. This file owns delivery work, not an additional specification.

**Release integration (2026-09-22):** `frontend-redesign` now includes keyword coverage, career row expansion, the daily workspace and posting identity through `ed69ac1`, with companion `0.4.5`. Earlier isolated-branch/build references below record validation checkpoints and do not describe the current checkout. Hands-on browser/provider QA remains user-led.

## Spaces and document decisions — local implementation 2026-09-24

**Current delivery:** implemented locally; local integration checks pass. No deployment or live paid-model call is claimed. The earlier Briefing and Jev planning checkpoints below remain historical evidence rather than current scope limits.

| Deliverable | Implemented behavior | Validation status |
| --- | --- | --- |
| Spaces and connected capture | Full `/spaces` page, owner-scoped title/purpose, active/archive/restore, explicit task/artifact/contact/company/opportunity links, contextual record opening and atomic task creation/linking | 8 focused PostgreSQL tests, 6 Space unit tests and 3 desktop/mobile browser scenarios pass |
| Briefing Space selection | Optional active Space with retained endpoint/version/idempotency identity; ordinary capture remains available | Capture, retry and navigation regressions included in focused coverage; first 100 active Spaces in picker, full Space list paginated |
| Document intake and policy | Unclassified uploads; owner catalog, template, timezone and external-text acknowledgement; automatic classification and rename tasks default Off | API/settings/intake regressions pass in the integrated backend, unit and browser suites |
| Bounded document decisions | Dedicated leased worker and document spending subject; 7–13 batched questions in `document-type.v3`, covering saved-text triage plus optional research and agent checks; exact source/context/catalog/question/model/policy provenance | 128 offline provider-contract tests pass; no live-provider quality or calibration claim |
| Human type and rename review | Manual type review after extraction without Jev, inspectable model proposals, exact review, separately configured rename task with Apply name / Keep current name | 37 document backend tests, 7 unit tests and 3 document browser scenarios pass, including stale-input and review boundaries |
| Schema and generated contracts | `0038_spaces`, then `0039_document_decisions`; readiness expects `0039_document_decisions` | Six migration tests pass; generated contracts and schema readiness match |

Integrated validation: `make check` passes with 964 backend tests, 405 frontend unit tests, 33 companion browser tests and 18 offline evaluation-contract tests, plus lint, types, generated contracts and the production build. The full 132-case workspace browser suite passes separately. Fixtures are synthetic; paid Jev quality and deployment remain unverified. Logs are retained in ignored `.local/spaces-doc-*` files.

Space sources and decisions remain existing artifacts/notes; nothing copies them into a competing content store. Space uploads use ordinary intake and are linked explicitly afterward. Opening or refreshing Spaces/Briefing performs no model work, connector pull or pasted-URL fetch.

The decision pack contains `sufficient_evidence`, `incompatible_purposes`, `processing_instructions`, `explicit_commitment`, `follow_up_requested` and `deadline_present`. The last three expose bounded text signals only: no automatic task creation, inferred urgency, message sending or authority. All three packs are wired through the contract, worker and UI. Add research or agent checks accepts five optional fields (4,000 characters each; 12,000 total), snapshotted privately with the source. Applicable context adds relevance/evidence role, claim support, output quality, policy concern and action matching; absent context omits those questions. Scores of 0–2 stay separate from probability/confidence, and action matching grants no authority. Current reads hide unsafe stale proposal actions while exact-decision and classification/review-history endpoints retain the record. The inspector shows typed scores, probabilities/confidence and provenance without generated reasoning. Original acquisition filenames and immutable contents survive type correction and display-title renaming.

Release follow-up: apply the pending migration chain through the normal deployment workflow, and separately evaluate semantic quality using an approved paid plan if requested. Five pinned daily outcomes, scheduled pulling, generic semantic tool gating, collection-wide text analytics and autonomous external actions remain outside this increment.

## Briefing first vertical slice — 2026-09-24

**Historical first-slice checkpoint:** implemented and verified locally; deployment and the live database migration remained pending at this checkpoint. `/` and `/briefing` expose existing daily tasks, questions/reviews, running work, outputs and activity. Assistant remains at `/agents`; root conversation query links preserve their full query when redirecting, and `/overview` stays available. Quick capture saves an unscheduled task with its first line as the bounded title and full original text in its rationale; Upload document reuses existing intake. Migration `0037_task_waiting` adds the explicit human-selected `waiting` task state and daily-task view.

| Deliverable | Required verification | Current evidence |
| --- | --- | --- |
| Briefing routing, existing queues and Assistant continuity | Synthetic frontend coverage for default/alias routes, real/empty/error states, record links and preserved conversations | 392 frontend unit tests and a 32-case workspace browser batch pass; added legacy conversation/New chat regression also passes |
| Quick capture and existing upload entry | Task text preservation, failed-save recovery, existing idempotency behavior and upload navigation | All six Briefing browser cases pass, including exact POST shape, one-row retry, task completion and upload entry |
| Waiting state, migration and generated contracts | PostgreSQL transitions/audit, human/owner isolation, daily view semantics, migration and contract checks | 42 focused PostgreSQL tests and six migration tests pass; generated contracts match |
| Read-only opening and refresh | Regression coverage that page reads do not request mail, invoke providers/models or dispatch work | Desktop/mobile fixture checks confirm saved-work reads without writes or provider/model requests; layout, console and page-error checks pass |

The full backend suite passed 791 tests; all 392 frontend unit tests passed separately. Remaining production checks passed with `make -o test check`: Python formatting/lint/types, frontend lint/types, environment and generated contracts, 33 companion browser tests, 18 offline evaluation-contract tests and the production web build. Synthetic desktop/mobile screenshots were inspected; the fixture's documented next-themes SSR-script warning is excluded from console failures. Five existing backend deprecation/transaction warnings remain. No live deployment, paid-model quality or live-provider result is claimed. Apply migration `0037_task_waiting` through the normal deployment workflow before serving the updated app.

Spaces and document decisions were outside this first slice and are now implemented in the [current increment](#spaces-and-document-decisions--local-implementation-2026-09-24). Five pinned daily outcomes, scheduled pulling and an analytics funnel remain later scope. Capture still performs no model classification or URL fetch. The confirmed rename scope remains the Vault display title, preserving the original filename.

## Jev audit and document decision slice — 2026-09-24

**Historical planning checkpoint:** the [source audit and ranked opportunities](jev-audit.md) and proposed classification/rename contracts preceded implementation. Document classification, rename settings/tasks and their UI are now covered by the [current delivery section](#spaces-and-document-decisions--local-implementation-2026-09-24). A generic semantic tool gate is not implemented by this increment.

At that planning checkpoint, the next proposed Jev slice was document classification with a separate configured rename task, following the first Briefing delivery. This supersedes the older architecture notes' recommendation to begin with a blanket pre-tool guard or browser ranking. The current capability router should be measured rather than expanded indiscriminately. Product Spec distinguishes the user's request from proposed review/default/template choices.

| Order | Deliverable | Relevant existing boundaries | Required evidence |
| --- | --- | --- | --- |
| 1 | Unclassified intake, owner policy, decision/review/rename persistence and domain methods | `db/artifacts.py`, `db/document_imports.py`, `db/models.py`, migrations | PostgreSQL ownership, atomic audit, exact versions, append compatibility, uniqueness and migration tests |
| 2 | Typed document request/response and pure signal composition | `integrations/jev.py`, separate document contract | Mock transport for each configured provider; dynamic catalog keys, missing/extra answers, finite probabilities, unknown/mixed, size limits and alias handling |
| 3 | Leased classification worker and document-job spend accounting | `documents/worker.py`, queue/dispatch, `db/spending.py` | Extraction commit survives provider failure; durable dispatch, duplicate delivery, timeout/unknown spend, cancellation, stale lease and budget-denied recovery |
| 4 | Review/apply APIs and generated client contracts | `api/documents.py`, artifact mutations, MCP policy | Human boundary, idempotent requests, expected revision conflicts, account isolation; `make contracts` |
| 5 | Vault inspector, settings and linked task interactions | `document-intake.tsx`, `document-original.tsx`, `document-tasks.tsx`, existing task/settings components | Frontend regressions for uncertainty, disabled/unavailable, stale preview, keyboard/focus, mobile overflow and settings disclosure |
| 6 | Held-out semantic evaluation and matched efficiency comparison | Synthetic fixtures, existing eval reporting and Langfuse | Per-type errors, unknown recall, calibration, correction/review rate, p50/p95, total cost and completed work versus baseline |

This historical plan did not reserve a migration number; the implemented follow-on uses `0038_spaces` and `0039_document_decisions`. Domain methods own validation/state/audit and routes own transactions. Keep network transport separate. Avoid a parallel document lifecycle or speculative decision-service framework.

The minimum synthetic scenario matrix includes: all catalog types; misleading filename; no eligible type; mixed document; blank/garbled extraction; document-instruction attack and harmless quotation; truncated evidence; malformed/partial/NaN response; changed catalog/model/questions; wrong owner; replacement original during inference/review; edited title during rename; renamed policy disabled before apply; archived file; pinned default resume incompatible with correction; duplicate dispatch/review/apply; expired lease; cancelled job; insufficient budget; provider timeout and unknown cost. Renaming off creates zero rename tasks; successful apply changes only the display title and completes only its own task.

Before interpreting quality, record labels independently of provider inputs. Revise questions on development data; select provisional thresholds on calibration data; report untouched held-out cases, including disagreements. Paid model evaluation requires its existing reviewed plan/allowance. Mocked or simulated outputs establish workflow correctness only. Automatic type acceptance or rename application is not included in the implemented release and would need separate quality/coverage acceptance criteria.

**Historical validation of the audit/documentation pass:** 18 existing Jev router tests passed using synthetic responses (`uv run --project apps/api pytest apps/api/tests/test_jev.py -q`). No live Jev request or private document/inbox processing was performed. Documentation links and whitespace are checked separately; this is not a new full `make check`, deployment or model-quality claim.

## Agent efficiency and recovery — 2026-09-24

[Research and implementation notes](agent-efficiency.md) connect primary literature to the current runtime. Host-reviewed reads gain bounded transient recovery with persisted attempt counts, shared quotas and steering/cancellation checks. MCP lookup constructs one requested tool while refreshing authorization. Stream completion flushes text immediately; reconnects classify permanent errors, honor server delay and pause offline/hidden.

Validation: the full backend suite passed 736 tests (five transaction warnings); the final focused recovery suite passed 29 cases, including two additional regressions added after full-suite collection. All 378 frontend unit tests pass with four isolated workers. The initial unrestricted frontend run produced six contention/timing failures; `vitest.config.ts` now caps concurrent workers at four without changing assertions, isolation or time limits. The bounded run took 19.48 s versus 34.67 s initially. All 33 extension browser tests, three workspace streaming scenarios, 18 offline evaluation-contract checks, generated contracts, style/types and the production web build pass. After the verified backend/frontend suites, `make -o test check` completed the remaining check targets. Raw check logs and the narrow catalog microbenchmark are ignored under `.local/agent-efficiency-*`.

The synthetic 100-tool lookup benchmark measured median construction/lookup overhead of 0.649 ms before and 0.082 ms after (200 samples per path). Registry construction, network and model time are excluded. No paid-model quality, production latency or invoice savings are claimed. Changes are in the workspace; deployed services were not rebuilt in this pass.

## Individually reviewed email delivery — 2026-09-24

The contact email flow reuses scoped outreach tasks, saved follow-up versions and exact reviewed actions. It opens the saved message in an editor, then moves directly to review. Every email requires its own approval, including cadence follow-ups. Research uses bounded saved context and local send receipts, with explicit instructions for focused public lookup and visible evidence/caveats; it does not infer replies from a send or read Gmail automatically.

Migration `0036_email_delivery` stores delivery intent and the resolved UTC due time on immutable action revisions. The shared dispatcher/claim predicate prevents early execution. Cadence accepts only a confirmed same-owner/account/recipient send, using its completion timestamp plus the chosen interval. Changed timing or content clears approval. Queued cancellation and claim are serialized by the existing action lock; an already claimed send cannot be recalled. Failed or ambiguous provider attempts retain the existing once-only/reconciliation behavior. A disconnected or deselected Gmail account fails before provider access. This is one reviewed follow-up at a time; unattended recurring sequences and automatic reply detection remain unimplemented.

Validation: `make check` passes with 706 backend tests, 370 frontend unit tests, 33 companion browser tests, 18 offline evaluation-contract checks, generated contracts, style/types and the production web build. The 14 focused workspace browser tests pass, including exact review, rescheduling, cancellation and saved-draft recovery. Two additional research-context regressions pass after the full run: confirmed receipts are distinguished from drafts, unrelated recipients are excluded, and dated saved research is reused. API, web and execution-worker images build successfully. All delivery fixtures are synthetic; no external outreach or paid-model quality evaluation was performed. Logs are ignored under `.local/email-*.log`.

The local API, web, agent/integration/execution workers and beat were updated after a private backup and idle-run checks. Schema `0036_email_delivery` is ready, API/web health return 200, and live OpenAPI exposes timing and recipient history filters. All six services use the newly built images. Waiting conversations were preserved. Scheduled delivery still requires the local services to be running.

## Gmail chat search repair — 2026-09-23

Reported inbox requests hit two separate failures: agent calls omitted the consumed human-message reference and received 403; subsequent authorized calls received 503 because Composio rejected the per-call `account` selector on a project without multi-account support. Gmail identity verification and restricted session creation had succeeded. Session execution now relies on its single pinned verified account. Agent tool schemas require non-null request provenance through both direct tools and the progressive catalog; human/local-client pulls retain their existing contract. Gmail failures receive static, specific guidance without exposing provider payloads or claiming a worker outage.

Validation: the two initial regressions failed before the fix. The final focused suite passes 70 tests covering the adapter, tool schemas, authorization, real MCP transport, reviewed actions and existing application tools. Ruff lint/formatting and configured mypy pass. An intermediate broader backend run exposed an unrelated validation-message compatibility regression; it was corrected by limiting the new guidance to Gmail and verified in the final focused suite. That broader run was stopped, so this is not a full `make check` claim. The API image builds successfully. A live request through the deployed Gmail route, using a random synthetic RFC822 message-ID query, succeeded with zero messages and a saved observation. This verifies search connectivity without reading personal email content; it does not evaluate inbox prioritization or task/strategy quality. Logs remain in ignored `.local/gmail-*.log`.

## Calm workbench usability cleanup — 2026-09-22

At this checkpoint, Home opened agent conversations with a visible desktop composer; Briefing later replaces the default and preserves Assistant. The sidebar keeps Opportunities, Tasks, Library, Document Vault, Contacts and Companies, with agent configuration and other tools below. Applications and saved roles remain accessible within Opportunities; legacy routes continue to work. Generated and authored artifacts open in a centered reading/review canvas, full width on mobile, with selected-version history, editing and export preserved.

Library includes notes, research and message drafts, with current-version review filtering and a recorded-agent-output collection. Uploaded originals and their pinned extracted content live in Document Vault over the existing immutable artifact lifecycle. A newer version never inherits an earlier approval. Agent configuration exposes existing profiles, skills, connectors and memory; workflow cards link to current capabilities. Scheduling and persistent grant editing remain outside this pass.

Companion `0.4.6` uses the active Chrome tab by default. The earlier default required a dedicated AgentBrowser/helper even for ordinary Chrome use. An explicitly saved choice is preserved. Capture failures now explain tab permissions, and setup/capture settings are easier to find. Synthetic coverage exercises default capture, file attachment, edited answers, permission denial, explicit native-reader failure and recovery. Reload the unpacked extension and refresh the application tab after updating. Authenticated ATS behavior remains unverified here.

The supplied screenshots and the user's calm-workbench choice guide the canonical Design Spec. The private self-contained design preview uses synthetic data and existing local Geist fonts; no reference images or personal workspace content were committed.

Validation: `make check` passes with 532 backend tests, 328 UI unit tests, 33 companion browser tests, 15 offline evaluation-contract tests, generated-contract checks, style/types and the production Next.js build. The broad workspace run passed 90 of 91 cases; its remaining PDF filename expectation was corrected to honor the API's download header, then all 17 document/usability cases passed. The final Library review-badge refresh passes all seven focused usability regressions, and final ESLint/diff checks pass. Desktop and 390px visual checks used synthetic data. Logs remain in ignored `.local/usability-*.log`. This pass is local and uncommitted; no deployment, paid-model call, external message or application submission was performed.

## Quick notes and performance budgets — 2026-09-23

Contacts now defaults to a 200-character connection note with compact saved context and optional bounded lookup. Enrich contact and Batch enrich explicitly request detailed research; Companies retains its sourced research workflow. The quick profile uses low reasoning, an 800-token output ceiling per call, seven model steps, eight tools, a 40k-character context ceiling and one search/capture maximum. Host checks enforce lookup quotas across checkpoint replay. Migration `0029_connection_notes` preserves the note limit independently of full research requests and refuses a downgrade that would discard those contracts.

Batch enrichment selects at most ten contacts from the current page, queues two requests concurrently and shows per-person outcomes. Retry keys survive an interrupted response; successful requests are not repeated. Changing pages or search resets selection. Structured artifacts now display saved fields instead of an empty reader, and text artifacts expose additional saved metadata. Validated numeric token-usage events survive redaction while credential-shaped fields remain hidden.

Integrated `make check` passed: 542 backend tests, 333 UI unit tests, 33 companion browser checks, 15 offline evaluation-contract checks, contracts/style/types and the production build. The full workspace browser suite passed 95 cases; all five final record-work cases also passed, including the added mobile batch-selection regression. An earlier simultaneous unit/browser run timed out in two existing Memory tests; both passed when the suites ran separately. This is deterministic/synthetic coverage, not a live provider latency, cost or output-quality benchmark.

The local API, web, agent/integration/execution workers and beat were rebuilt and restarted on schema `0029_connection_notes` after a private database backup and idle-worker checks. API readiness and web health return 200; all six services use the final built images. Live OpenAPI exposes quick-note requests and Library/Vault/review filters. Reload companion 0.4.6 to use the capture-default fix; authenticated ATS behavior remains a hands-on verification item. No paid generation or external outreach was performed.

## Build objective

The first release provides Copilot-style application assistance with user Next/Submit, outreach approved and sent through Command Center, and isolated research scripts producing documents. Deep Agents on LangGraph targets an always-on backend; Composio supplies Gmail, Google Calendar, Linear and Notion, with reviewed external changes and Slack deferred. [Product Spec](../product/product-spec.md#first-agent-release--confirmed-interview-direction) owns this boundary; [Tech Spec](tech-spec.md#first-agent-release-architecture-draft) owns architecture and context contracts. Application preparation, exact resume uploads, reviewed memory, durable token/tool streaming, scoped connected-app context, reviewed external actions, isolated scripts/PDF exports and spending/recovery controls are implemented locally. The accepted workspace remedies are implemented with synthetic regressions; their evidence and limits are recorded below. The user will perform hands-on platform/provider QA. Paid-model evaluation and selecting/deploying an always-on host remain separate release work.

### Active goal — full frontend and knowledge-work revamp

The user explicitly set the goal on 2026-09-22 and then expanded it to include everything discussed. Connected apps is the first vertical slice, not the entire completion criterion. The goal remains open until the requested retained work is implemented and verified:

- [x] Connected apps workspace and account setup/verification using existing Composio.
- [x] Complete LinkedIn contacts/professional-profile mappings with preserved provenance, user edits and reviewed facts; no historical message archive.
- [x] Shared Tiptap writing for the correspondence workflow, notes/documents and task writing; autosaved working drafts, meaningful checkpoints, recovery and exact review/send versions.
- [ ] Cohesive tasks and notes interactions informed by Alfred, using one canonical task model and contextual sources.
- [x] Document vault that preserves originals, presents previews/extractions together, supports reliable reading/search/organization and exact version editing/export.
- [ ] Frontend revamp from supplied references, appropriate shadcn/AI Elements, full-page section navigation, contextual actions, mobile/keyboard/accessibility checks.
- [x] Apollo/Hunter contact discovery with explicit imports and source evidence.
- [x] Company-specific agent enrichment and generated person-linked follow-ups over canonical tasks and saved artifacts.
- [ ] Application automation and broader Simplify parity: assisted autofill/native AgentBrowser, tracking, saved job descriptions and tailored document generation/editing/export are implemented; deterministic keyword coverage was verified at isolated ancestor `d83c6d7`. Bounded work/education row expansion is implemented in isolated `application-autofill` / companion `0.4.4`, with non-browser verification complete. Broader ATS controls, automatic job identity detection, portal reconciliation and full tenant coverage remain.
- [x] Smoother streamed responses, stable connections, bounded replay and accessible scrolling (requested during implementation).
- [ ] Explicitly requested email acquisition and reviewed reply/outreach behavior with accurate source/thread/account context; Gmail remains the inbox.

Latest priority (2026-09-22): make existing leads actionable today through saved person-linked follow-ups, LinkedIn copy/paste and optional reviewed/manual email; then Apollo/Hunter discovery, company-row agent enrichment, notes and application preparation. The user has reopened automation work for applying; scheduling policy and final-submission behavior are not yet implemented. The earlier routine deferral must not erase this new request. No LinkedIn message-body import, background Gmail sync, autonomous external sends or new runtime migration is authorized. The user requested ordinary engineering choices be handled without additional interview rounds. Goal metadata was initially created for connected apps; this subsequent user expansion governs the actual working scope and completion boundary.

### Application copilot — current pass

One-click profile/resume autofill, a persistent side panel, the real native AgentBrowser structure reader, explicit Direct browser mode, saved/replay-safe progress and fresh-capture human answer filling are implemented. Schema0023 adds explicit first/last-name/address/GitHub facts and same-page task continuations. The backend does not promote unreviewed profile proposals or generated answers into automatic truth. Browser fields remain bound to exact captures, and Next/Submit remain manual. Remaining Simplify parity is recorded in Product Spec. Verification: `make check` passed with 320 backend tests, 76 UI unit tests, 27 companion tests, 15 offline eval contracts and a production build. The subsequent incompatible-file regression passes with the 17-test application suite; the final seven one-click browser cases also cover explicit replacement of a previously filled value. Ruff, mypy and web lint/types pass (one pre-existing unused Badge warning). A real loaded extension, native AgentBrowser helper, FastAPI and PostgreSQL completed profile fill, exact file upload, preservation and a fresh-capture edited answer against an isolated synthetic fixture. No model/provider calls or submissions were made. The 390px companion has no overflow and no axe violations; only decorative command/arrow glyphs require manual contrast inspection. The copilot release was deployed on schema0023 after a private backup and successful isolated restore verification. Wider ATS tenants, paid generated-answer quality and remaining feature parity are not claimed.

### Application tracking — follow-on pass

Implemented the Applications section over a canonical task facet, human-reported status with CAS/receipts/audit, metadata-only capture history, exact saved answer/résumé access, browser deep links and editable task context. Schema0024 backfills existing preparations without inventing submitted outcomes. Full-URL local continuation prevents query-distinct jobs from sharing a task. Five new PostgreSQL regressions cover history/reopening, immutable packages, owner/human isolation, lost response retries and migration preservation; four workspace browser cases cover reloading, lost status acknowledgements, filters and mobile task editing. The companion regression adds query-distinct job separation. Validation: `make check` passes with 326 PostgreSQL tests, 76 UI unit tests, 29 companion tests, 15 offline evaluation contracts, lint/types/contracts and the production build. Eleven tracker/navigation browser checks pass. Desktop1440/mobile390 accessibility checks have zero violations and no horizontal overflow; the only desktop incomplete item is the existing synthetic account stub. Keyboard focus proceeds from the opened heading to the primary action, and no browser errors were recorded. Docker API/web/execution builds passed. The local stack is now healthy on schema0024; API, web and execution-worker match the built images, and tracker RLS is enabled. The migration followed a private backup with a successful isolated restore check. No real portal submission or provider/model calls were made.

### Application job context — current pass

Implemented first-capture job descriptions, owner-bound immutable sources, manual Tiptap editing/recovery and exact saved-description references for the application agent. Five backend regressions cover continuation/manual edits, creation retries, actor/task boundaries, source reads and migration preservation. Companion cases exercise actual structured/semantic extraction, ambiguity, size bounds and removal of form values; the mobile workspace case covers reload, checkpoints and unfinished edits. Validation: full `make check` passes with 331 PostgreSQL tests, 76 UI unit tests, 31 companion tests, 15 offline evaluation contracts, lint/types/contracts and a production build. Five application browser checks pass, including recovery, checkpoint separation, keyboard focus and mobile task editing. Desktop1440/mobile390 have no axe violations or horizontal overflow; only the existing synthetic account stub needs manual desktop inspection. Docker API/web/execution builds passed, and the private pre-migration backup restored successfully in isolation. The final images are deployed locally on schema0025; API/web health checks pass and API, web and execution-worker image IDs match the final builds. All six application services were running at that checkpoint. The following material slice extends this release.

### Application materials — current pass

Implemented tailored résumé/cover-letter requests with exact job/résumé/extraction sources and approved fact revisions, assigned-run tools with lease checks, typed immutable outputs under the existing application task, recoverable request identity, Tiptap editing and PDF export. Completed résumé PDF derivatives are selectable through the existing companion file contract. The following slice adds cover-letter attachment.

Full `make check` passes: 338 PostgreSQL tests, 76 UI unit tests, 31 companion tests, 15 offline evaluation contracts, lint/types/contracts and the production web build. Seven new backend cases include source pinning, request replay, owner/run isolation, fact revocation, completed-export file eligibility and actual worker/MCP/HTTP persistence with only model generation mocked. Two material browser checks cover lost replies/reload recovery, editing/export and mobile prerequisite state; the five existing tracker cases pass. Desktop1440/mobile390 material views have no axe violations or horizontal overflow. The existing desktop synthetic-account stub and clipped text in the contextual writer require manual inspection; screenshots were checked. Opening the writer on mobile and pressing Escape returns focus to Open draft & export. Docker API/web/execution builds passed, and schema0026 is deployed after a private backup with an isolated restore verification. All six app services are running; API/web health, material-table RLS and exact API/web/execution image IDs are verified. Paid generation quality and authenticated employer acceptance were not tested.

### Cover-letter attachment — current pass

Implemented separate companion/workspace letter selection, optional one-click attachment, one-document-per-control review and exact saved letter links in application history. Original uploads and completed letter PDFs use the owned typed file resolver. Empty compatible cover-letter fields fill automatically only after the user selects a letter; mixed-purpose fields, existing attachments and replacements stay explicit. Prepared file choices survive lost replies and reopening; later answer review recaptures the form and preserves attached files. Legacy request hashes and packages remain readable without a schema migration. Companion version0.4.1 keeps the existing permissions and native bridge.

Four new backend cases cover paired-file attachment/download/history, mismatched or swapped file rejection, explicit upload opt-in/type checks, replacement/archive checks and pre-update receipt compatibility. The companion regression applies actual verified file bytes to the content script after a lost preparation reply, then preserves the files on answer review. Workspace regression covers separate file selection and a long selected filename at390px. Full `make check` passes with 342 PostgreSQL tests, 76 UI unit tests, 32 companion tests, 15 offline evaluation contracts, lint/types/contracts and the production web build. Ten application workspace cases pass; after the mobile filename fix, all five preparation cases and eleven styled one-click companion cases pass again. The new letter test verifies exact bytes, retry identity, preserved attachments, accurate missing-question counts and mobile width. Desktop/mobile workspace checks and the390px companion controls have no axe violations or overflow; the existing synthetic account stub and decorative companion mark retain manual-inspection notes. Docker API/web/execution builds passed. All six local app services are running with the exact rebuilt images; API/web health and live OpenAPI cover-letter contracts are verified on unchanged schema0026. Extension0.4.1 is available in apps/extension; reload the unpacked extension to refresh an existing Chrome installation. Real employer acceptance and paid-model quality remain unverified.

### Structured employment and education — current pass

Implemented validated career entries inside existing versioned profile facts, additive API projections, conservative LinkedIn mapping and a recoverable structured editor with Tiptap descriptions. Existing approvals and stable import IDs remain unchanged; unknown dates/current status remain unknown. Subsequent grouped-career, multi-page continuation and isolated keyword-coverage passes are recorded below. This pass requires no SQL migration or extension update.

Validation: full `make check` passes with 359 backend tests, 76 UI unit tests, 32 companion tests, 15 offline evaluation contracts, lint/types/contracts and the production build. Twenty-two career/import tests pass again after the final date-status refinement. Fourteen initial career/document browser cases pass, followed by six final career cases covering reload, lost replies, newer typing, explicit stale-base adoption, mobile layout and keyboard focus return. Desktop1280/mobile390 have no axe violations or horizontal overflow; Radix modal focus guards/background retain an incomplete inspection note. Final lint passes with the existing unused Badge warning. Docker API/web/execution builds and the final web rebuild passed. All six local application services are running with the exact current images; API/web health and live structured-career OpenAPI contracts are verified on unchanged schema0026. No real profile entries were revised, and this release does not enable repeated ATS-group filling.

### Grouped career autofill — current pass

Companion 0.4.2 captures existing, explicitly labelled work/education sections and matches each to one approved structured fact revision. Automatic answers require unambiguous entry order and source date precision. Prefilled or edited groups remain unchanged; changed bindings stop application. Native date/month and split month/year controls retain range/step checks. Review controls include the section heading. Older capture retries omit absent new metadata, and revoked fact evidence blocks claiming a prepared fill. No SQL migration or permission changes are required. This increment did not create rows; bounded expansion is recorded below. Automatic job identity detection and broader ATS compatibility remain open.

Final non-browser validation passes: 369 backend tests, 76 UI unit tests, 15 offline evaluation contracts, Python lint/format/mypy, frontend lint/typecheck, generated contract/environment checks, extension syntax checks and the Docker production web build. Frontend types now derive BrowserField from the generated FormField contract. A regression directly seeds pre-update capture JSON and verifies retry identity. The existing unused Badge lint warning remains. API/execution/web images built successfully. All six local app services run the exact rebuilt images; API/web health and live career-group/date contracts are verified on unchanged schema0026. Reload the unpacked extension to use0.4.2. Browser testing for this increment is intentionally skipped at the user's request; prior browser results above apply to their respective earlier increments.

### Multi-page application continuation — current pass

Companion0.4.3 now offers Continue this application or Start a new application after a full-URL change. The durable choice precedes preparation/filling and survives reopening or lost replies. Exact same-page repeats retain their one-click path. Confirmed pages share the same task, conversation and original job description while keeping separate answer packages. Actor/device/opportunity/active-task checks remain enforced, and old receipt hashes remain valid. Saved capture history labels each page and the confirmation. Cross-origin continuation is an explicit user choice; automatic job identity detection and portal reconciliation remain open. No migration or new permission is required; Next/Submit remain manual.

Non-browser validation passes: 381 backend tests, 85 UI unit tests, 15 offline evaluation contracts, Python lint/format/mypy, frontend lint/types, generated contract/environment checks and extension syntax. Twelve new backend cases cover continuation boundaries, source/package preservation, history and retry compatibility. Nine jsdom cases run the actual popup state machine through separate-job choices, reopening, lost replies, exact tab/URL checks, legacy requests and keyboard focus. Browser testing remains skipped at the user's request. API/execution/web production builds pass. All six local services run the exact rebuilt images; API/web health and live continuation/history contracts are verified on unchanged schema0026. Reload the unpacked extension to use0.4.3.

### Application keyword coverage — isolated branch, verified

Implemented a deterministic literal matcher, owner-bound read-only API and Application documents coverage panel at isolated commit `d83c6d7`, now inherited by `application-autofill` in `.local/worktrees/application-keywords`. The user's stable smoke-test build remains `frontend-redesign` at `2ad39e7`, with extension `0.4.3`; this branch has not been pushed or deployed over that build. No migration, companion update, runtime restart, browser/provider call or model work is part of this pass.

The check pins the current saved job version, selected résumé file and exact completed extraction/PDF source text. It supports bounded curated detection or a normalized, deduplicated selected list; reports matched/missing terms, round-half-up coverage, source versions and truncation; and produces no score when detection finds no terms. The panel resets on source/application changes, clears an earlier report when terms change, freezes choices during checking and exposes retry/missing-source states. Coverage does not rank applicants, determine eligibility, infer qualifications or mutate facts, documents, task state or application status.

Non-browser validation is complete in isolation: 450 backend tests pass with two existing warnings, 103 UI tests pass, and all 9 targeted API tests pass again after the final mypy-narrowing assertion. Lint, backend/frontend types and generated `contracts-check` pass; `make lint` retains the existing unused `Badge` warning in `task-action-hub.tsx`. The production Next.js webpack build exits successfully using only a synthetic public Clerk key, without starting or restarting runtime services. Coverage includes deterministic matching, source ownership/version and read-only API behavior, plus UI source/reset/error states. Browser QA remains skipped at the user's request. This evidence does not claim deployment or a push over the stable smoke-test build.

### Career row expansion — isolated branch, non-browser verified

Companion `0.4.4` on `application-autofill` adds bounded employment/education rows through explicit Add controls. The branch includes keyword commit `d83c6d7`; it is not deployed over the running `frontend-redesign` build at `2ad39e7` / companion `0.4.3`. No runtime restart, migration or new permission is part of this pass.

Preparations store immutable `0..10` targets from distinct active approved unscoped career facts, using the same chronology rules as filling; ambiguous kinds and older packages yield zero. Existing values and ambiguous DOM remain manual. Retained row-operation IDs prevent duplicate additions on retries; a rerendered Add button is accepted only after a confirmed new row and a matching history kind, label and section scope; a fresh capture and same-application preparation precede filling. History-only pages can start with zero fields via local `InspectResult.history_expandable`, stripped before API submission; AgentBrowser requires a valid local Add hint for a zero-field capture. Next and Submit remain manual.

Non-browser verification passes: 463 backend tests with two existing warnings and 165 web tests across 19 files, including 46 jsdom cases executing the actual content script and 16 new popup-flow tests. `make lint` passes Ruff checks/format, mypy, ESLint and TypeScript checks, retaining one existing unused `Badge` warning. Generated `contracts-check`, content/popup `node --check` and Prettier checks pass. The production Next.js webpack build exited successfully with only a synthetic public Clerk key and no runtime restart. Browser QA is skipped at the user's request; native AgentBrowser and real-browser integration were not exercised for this increment. The running `frontend-redesign` build at `2ad39e7` / companion `0.4.3` remains unchanged. Earlier browser evidence applies only to its recorded increments. Authenticated portal coverage, broader controls and exact Simplify parity remain incomplete.

### Connected apps — first slice, implemented locally

The user clarified that “connections” means external-app setup and account management, asked to defer routines and minimize further questions, and requested adding this work to the previously paused goal. Use the supplied connected-app references directly. LinkedIn mapping, Tiptap and broader Library work remain recorded in the revamp roadmap and do not block this slice.

- Add a full-page Connected apps destination and sidebar entry. Consolidate the current split Settings connection/account controls into app cards for the supported Gmail, Google Calendar, Linear and Notion integrations. Keep server/model-provider health in Settings.
- Reuse current OAuth initiation, actor-owned account listing, explicit account refresh and Gmail outreach-account selection. Preserve retained request identities on retries and optimistic revision checks. Return OAuth to the new destination and expose a clear verification step. Navigation must not fetch email.
- Show configured, verified, unavailable and attention-needed states honestly, with account identity and verification time. Show supported read/reviewed-write behavior; do not add cosmetic permission toggles or unsupported connection-management actions.
- Validate synthetic configured/unconfigured, multiple-account, inactive-account, load/retry, mutation-retry, OAuth callback, desktop/mobile and keyboard paths. Preserve the existing `connected-accounts.test.tsx` retry regressions; extend route/rendered coverage and run appropriate lint/types/build/backend checks for changed contracts.

Verified 2026-09-22: `make check` passed with 276 backend tests, 60 frontend unit tests, 21 browser-companion checks, 15 offline eval-contract checks and production build. Seven focused workspace browser checks passed; desktop/mobile screenshots were inspected, keyboard dialog focus returns correctly, and the Connected apps accessibility scan reported no violations. API/web images were rebuilt; web port 3001 and API readiness are healthy. Synthetic OAuth routes were exercised; no real provider authorization, Gmail acquisition or external send was performed. The account refresh continues to reflect provider observations; it does not reconcile disappeared accounts or implement disconnect.

### LinkedIn mapping — implemented and imported locally

Migration `0017_linkedin_mapping` adds immutable, owner-scoped contact source rows and typed career fact proposals. The importer accounts for 48 files/278 column positions; 13 files/62 columns are in scope, and excluded values never enter the new snapshots. The verified workspace import matched 3,512 named rows to existing contacts, retained 57 unnamed rows in source evidence, created 12 sources and 130 pending facts, and reported no issues. Hashes verified that existing contacts (including notes), companies and approved fact counts are unchanged. Replay produced no new sources/facts or record edits. A private pre-import PostgreSQL backup and reports are retained locally.

The expanded `make check` passed: 281 backend tests, 60 unit tests, 21 companion tests, 15 offline eval-contract checks and production build. Sixteen focused workspace checks passed, including access beyond the first 100 career facts and contact source history on desktop/mobile. API/web and all workers were rebuilt and are running schema 0017. This import does not approve claims or authorize messaging.

### Shared writing — implementation in progress

Tiptap 3.31.3 now powers the email composer with formatting, links, lists, undo/redo, spellcheck and an isolated preview of the exact saved HTML. Unsupported legacy layouts stay editable as source. Recipients, account, attachments, source and message share a recoverable working draft. The tab-local journal is scoped by signed-in user; server revisions reject competing tabs. Unknown outcomes retain the same request and body, including proposal checkpoints across refresh. Late responses cannot erase newer typing or another editing session's journal. Acknowledged proposal revisions advance the draft's editing base without silently changing the content. Conflict resolution retains the replaced copy for recovery.

Migration `0018_writing_drafts` stores one owned working draft and one save receipt. Clearing leaves a revision tombstone. Autosaves never create artifact/action versions, approval, sends or per-keystroke audit entries. Backend JSON preserves whitespace. The latest local slice adds migration `0019_writing_recovery`: the first working copy, five-minute recovery copies during editing and a final pre-clear copy, bounded to twenty per writer. Earlier drafts loads metadata pages and only the selected body; restoring retains the replaced copy in the tab. Document editing and generic record creation/details (including task details and CRM notes) now use the same writer. A dedicated Library/Notes destination remains pending; online drafts live on the server while the tab journal covers navigation/refresh.

Gmail pulls are available through the workspace Pull email control and explicit chat requests. The agent endpoint binds the current owned user message, selected account, active lease and spending limits; the directive interprets explicit mail intent. Reads use a retained, account-pinned Composio session with only the Gmail fetch tool enabled. Opening the dialog or drafting alone cannot fetch messages. No mailbox sync or new routines were added. True thread/reply targeting remains pending. See the scoped-session contract in Tech Spec.

The first writer `make check` passed (288 backend, 73 unit, 21 companion, 15 offline eval-contract checks and production build). Nine focused browser checks pass for formatting/reload/checkpoints, two-tab recovery, mobile/keyboard, explicit mail pulls and reviewed-action boundaries. Mobile composer axe audit has zero violations/incomplete checks. The final 26 focused backend regressions pass, including account binding. API/web and all workers were rebuilt and rolled out on schema 0018; localhost:3001/health and API readiness are healthy. A private PostgreSQL backup was taken before migration. No actual provider mail reads or sends were used in verification.

Vault groundwork now pins edit bases/revisions, prevents version switching or restarting an active edit, preserves newer typing after a checkpoint, and fences late responses from cancelled editing sessions. Original bytes are shown as stored files with a pinned extraction link rather than empty text; binary versions cannot seed blank text edits. Seven focused unit tests and nine document browser checks pass. These fixes do not complete the broader vault/search/organization or durable-editor work.

### Contact follow-ups and vault recovery — implemented and running locally

Migration `0020_contact_follow_ups` links a person to message artifacts. The shared artifact lifecycle owns each immutable checkpoint; follow-ups never create delivery or approval implicitly. Contacts expose a Follow-ups tab and direct action. Writing autosaves independently of Gmail setup. Saved messages support copy, opening the LinkedIn profile, a mail-app link for supported lengths and preparing a reviewed email from the exact saved source version. Updated drafts keep prior versions and cannot alter an already prepared email. Contact and source ownership, stale revisions, replay and lineage are enforced server-side.

The vault now pages version metadata and retrieves one selected version body. The original editing base survives reload and competing artifact changes; saving a branch is explicit. Generic creation drafts retain unknown request identities across reopening and prevent editing a creation whose outcome is unresolved. Existing-record edits keep newer typing and advance to the acknowledged revision. Legacy `gmail_search` grants are no longer advertised to runtime agents; the API also rejects them.

Current focused evidence: seven writing/recovery backend tests, eight workspace/vault tests, three correspondence tests, twenty-one writer/review unit tests plus three record-editor tests, and twenty-six desktop/mobile workspace browser checks pass. Follow-up screenshots inspected at desktop/mobile sizes; axe reported zero violations and one contrast item needing manual review (muted dialog description over the solid popover background). The complete `make check` passed with 295 backend tests, 74 UI unit tests, 21 companion checks, 15 offline eval contracts and production build. API/web and all application workers were rebuilt and are healthy on schema `0020_contact_follow_ups`; web port 3001 and API readiness passed after a private pre-migration backup. This slice does not deliver a company-enrichment button, generated follow-ups, the dedicated notes workflow or autonomous applications. Contact discovery is the next slice below.

### Apollo/Hunter contact discovery — implemented and running locally

Contacts → Discover contacts and Company → Find people expose manual, bounded provider searches. Connected apps shows native provider configuration and setup. Apollo people search returns partial profiles; selecting Reveal profile makes a separate enrichment request with personal-email, phone and waterfall options disabled. Hunter domain search returns published professional email claims and reported verification status. Root `APOLLO_API_KEY` and `HUNTER_API_KEY` configure server-side adapters; no keys are sent to the browser. Neither key is currently configured locally, and no real provider request or paid credit was used during implementation.

Search/reveal operations retain durable `ConnectedRequest` claims across provider I/O. Retries reuse the same request; unresolved outcomes are not automatically replayed. Successful and empty results are saved as private source artifacts. Equivalent requests reuse results for one hour, scoped by owner, normalized request and credential revision. The latest ten saved snapshots can be revisited without a provider call. Requests are human-only; opening screens does not discover or enrich contacts.

Migration `0021_contact_discovery` preserves imported provider identity and exact source-version provenance. Explicit imports match provider identity, email or LinkedIn profile; ambiguous matches and archived contacts are rejected. Existing names, notes and other fields stay intact. A separate revision-checked Fill missing details action can add available email, title or LinkedIn URL to blank fields. Contact details retain a provider-evidence panel alongside LinkedIn import history. Revealed data remains a provider claim, not a verified personal relationship.

Verified with synthetic responses: `make check` passes (301 backend tests, 74 UI unit tests, 21 companion checks, 15 offline eval contracts and production build). Ten discovery/connected-app/follow-up browser checks pass, including accepting only an existing contact’s missing email and retaining uncertain request identity across reload/fresh retries. Desktop/mobile visuals were inspected; axe reports zero violations and a contrast item needing manual review, measured at 6.51:1 on the solid dialog background. API/web and all six application services were rebuilt and are healthy on schema `0021_contact_discovery`; web health and API readiness pass. A private pre-migration PostgreSQL backup is retained locally. Hunter email-finder/verification purchases, company enrichment, generated follow-ups and application automation are not claimed by this slice.

### Company research, generated follow-ups and streaming — implemented and running locally

Migration `0022_record_work` links CRM work to canonical Tasks and their scoped conversations. Contacts → Follow up → Draft with agent saves a person-linked draft; Company → Enrich company produces an immutable research brief and a compact row summary. Opening records does not run agents. Active work is deduplicated, unknown starts retain their request identity across reload, and the latest useful unarchived result remains visible through failed refreshes. Outputs retain exact source versions; company research requires a captured public source. Existing notes and human drafts are preserved. These actions do not send messages, pull Gmail, purchase contact data or submit applications.

The research/outreach profiles gain scoped record-context and output tools. Existing tasks, spending controls, model configuration, durable events and reviewed external actions remain authoritative. Model quality is not established by synthetic tests; no paid model run was performed.

Streaming flushes small text within an 80 ms cadence even when the provider pauses. SSE checks active output at 50 ms intervals, backs off idle reads to 250 ms, and drains full replay pages immediately. The client keeps its connection through status changes, batches text per animation frame, fences late reads when switching runs and reconciles terminal state. Replies use memoized AI Elements/Streamdown rendering with a short word fade; reduced motion disables word animations and spring scrolling. Live activity shares the conversation scroll area and respects a reader who scrolls back. Source links use a keyboard-accessible shadcn dialog with focus restoration.

Verification: `make check` passed with 307 backend tests, 76 UI unit tests, 21 companion checks, 15 offline eval contracts and the production build. Seventeen focused record-work/security tests also pass with the final profile configuration. Sixteen record-work/conversation/navigation browser checks and three streaming checks cover replay, status transitions, retained request identity, editable generated drafts, live typing, keyboard scrollback and reduced motion. Mobile company research has zero axe violations/incomplete checks and no overflow. Settled mobile streaming has zero axe violations; clipped offscreen text needs manual contrast review, with 81 text/status samples measuring at least 7.27:1. Transient word fades were assessed separately from settled text.

A private database/blob backup passed restore verification in isolated resources. Schema `0022_record_work`, API/web and all application workers are running locally; port 3001 health and API readiness pass. The existing public search/scrape smoke check returns search results and page Markdown. The local Docker Turbopack build caused resource starvation when run alongside all services; the Docker web build now uses bounded Webpack/Node workers. Host checks retain the default Next build. No paid model/provider QA, mail send or application submission was performed. The dedicated notes/library workflow and application automation remain unfinished.

### Test and eval tooling

Confirmed tooling lives in [Tech Spec](tech-spec.md#testing-mocking-and-agent-evaluations): pytest test authoring/runner, pytest-mock for mocks/spies, DeepEval for agent-quality evals. Backend pytest/pytest-mock and the isolated [DeepEval project](../../apps/api/evals/README.md) are implemented. `make check` includes offline evaluation-contract tests; paid judging is a separate command and first requires passing the ordinary correctness gates. Existing TypeScript UI regressions remain in place; no test-runner migration is claimed.

The versioned synthetic evaluation dataset covers the five named application platforms, selected-thread outreach and cited research. Recorded outputs bind exact inputs, provider/model, prompt/tool digests and source/harness revisions. Grounding, relevance and completion are scored individually; evaluator errors remain separate. `make eval-plan` creates a private, zero-allowance proposal for review. Actual output generation, accepted thresholds, judge choice and a paid allowance remain open. Acceptance combines hard pytest correctness gates and independent quality results; mocked output establishes only adapter behavior.

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

The original delivery sequence established Deep Agents/checkpoint/MCP compatibility, durable conversations and facts, requested Gmail context, reviewed connected actions, browser filling/uploads and isolated research documents. Those foundations are now implemented; current evidence is recorded below. Each remaining slice must include its persisted activity and workspace projection. The sequence does not remove named capabilities or settle browser coverage, spending amounts or hosting choices.

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

The recorded-output judge harness and its offline contract tests are implemented in `apps/api/evals/`, using a separate lockfile and environment so evaluation dependencies do not change production packages. Its current cost proposal contains seven cases and 21 judge calls with a conservative judge-only bound of USD 0.709632; the allowed spend is zero. This excludes generating the model outputs, browser execution and live provider checks. The proposed model/prices/thresholds are review inputs, not accepted production settings; see the evaluation README for exact revisions and limits.

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

| Work | Recorded validation (dates noted where different) | Limits |
| --- | --- | --- |
| Connected workspace | 46 backend tests; lint/types/build; schema drift; Docker startup; real MCP/HTTP execution with mocked model; 3 companion browser tests; synthetic desktop/mobile inspection | Paid OpenAI/Composio execution was not tested; no autonomous application or outreach |
| Frontend engineering review | Four synthetic component/helper probes reproduced draft loss, retargeted reviews, identity-independent cache reuse and duplicate writes after manual retry; production manifest inspected | Defect evidence, not passing regression coverage; no live Clerk account switch or latency/heap benchmark |
| UI simplification and appearance (current pass) | `make check`: 50 backend + 4 frontend unit tests, lint/types/production build; 6 synthetic workspace browser tests; desktop/mobile visual inspection | Browser tests mock Next/Clerk/API; not a live-provider or exhaustive accessibility pass. All eight mode/accent combinations pass primary/body/muted text contrast checks. |
| Operator importer and batch company labels | `make check` passed with 50 backend tests; synthetic import/replay/owner-isolation and >100-company label cases; applied/replay reports and browser/API verification retained privately | Local cached sources, not live Notion synchronization; private source/report details are excluded here |
| Reviewed actions, research execution, PDF exports and spending controls | `make check`: 229 backend, 4 frontend unit and 11 companion browser tests; Ruff, mypy, frontend lint/types and production build. Separate workspace browser suite: 36 passed. Synthetic Docker execution confirmed no child credentials, socket or network; generated PDF has a valid PDF header. A locking regression verifies that claiming one chat does not wait on another owner's recovery. | Provider calls use synthetic adapters; live delivery and paid-model evaluations remain unverified. Five-platform application coverage still needs custom-control, frame and authenticated-tenant work. |
| Local upgrade and recovery rehearsal (2026-09-22 UTC) | Quiesced database/blob backup restored and verified in isolated temporary resources; local schema upgraded from 0007 to 0014. API/web health passed; all five Celery queues responded. The deployed execution worker generated a synthetic PDF and ran a script with no child credentials/socket/network; cleanup was verified. | Local Compose only; private backup data and raw logs remain untracked. This does not establish live provider or authenticated ATS coverage. |
| Application control compatibility (2026-09-22) | `make check`: 233 backend, 4 frontend unit and 21 companion browser tests; generated contracts, Ruff/mypy, frontend lint/types and production build passed. New regressions cover exact iframe document identity, React state, the intended resume control, bounded selected choices and numeric range/step constraints. | Hands-on platform/provider QA is deferred to the user. Search-dependent/unknown widgets and cross-origin frames remain manual; no authenticated five-platform coverage or real submission is claimed. |
| Scoped connected context (2026-09-22, `52c452b`) | 245 backend tests; generated contracts, Ruff/format and mypy passed. Synthetic provider cases cover exact owned account identity, durable request recovery, bounded Calendar/Linear/Notion context, spending, cancellation and immutable observations. Migration 0015 refuses a downgrade that would lose Calendar-list provenance. | Live provider responses and paid execution remain unverified. |
| Workspace completion pass (2026-09-22) | `make check` passed with 245 backend, 48 frontend unit and 21 companion tests; the final unit suite passed 50 tests after adding sign-out and same-user coverage. All 36 synthetic workspace browser tests passed. Forwarding, draft/review pinning, retained write identity, query recovery, memory pagination and deferred-view recovery have regressions. Build diagnostics show 65.8% smaller first-load uncompressed section JavaScript. | Sessions and providers are mocked. Browser fixture dependencies are prebundled to avoid late optimizer reloads. Build bytes do not measure transferred bytes or latency; real signed-in QA remains user-deferred. |
| Durable questions, draft lineage and evaluation tooling (2026-09-22) | `make check` passed: 253 backend, 50 frontend unit, 21 companion and 15 offline evaluation tests; contracts, Ruff/format, mypy, frontend lint/types and production build passed. Seven focused conversation/stream/question browser tests passed. Native parallel specialist interrupts resume by exact saver ID without repeating the other branch; unanswered UI drafts survive resume/refresh failures. Source-version ownership, replay and immutable derivation have regressions. Local images/schema0016 were upgraded after a verified isolated backup restore; API/web health and all five queues passed. | Offline judge responses establish adapter behavior only. No paid quality run or signed-in QA occurred. The overview attention/running-work/output projection remains unfinished. |

Raw prior evidence is under ignored `.local/qa/` and `.local/imports/`. Logs and images can contain private data; do not commit them. No Supabase or production deployment is claimed. Record current-session checks in local, untracked handoff notes.

## What already exists

Reuse Clerk forwarding, the shared API client, TanStack Query, official shadcn/AI Elements, actor-owned API queries, request receipts, row revisions and bounded list endpoints. Existing Activity/Records pagination supplies the Memory pattern. The accepted changes below need no new application runtime or storage architecture; Vitest/RTL/jsdom are approved development test dependencies only.

## Accepted workspace hardening

All nine remedies below were accepted in the earlier 2026-09-21 engineering review: T1–T5 individually; T6–T9 under the user's instruction to take all remaining recommendations. T1–T7 and T9 are implemented with synthetic regressions. T8's automated forwarding boundary is covered; real authenticated provider journeys remain deferred to the user. Local implementation is not release approval.

The prior detailed review and synthetic QA plan remain at `~/.gstack/projects/command-center/*-eng-review-20260921-64621.md` and `*-eng-review-test-plan-20260921-64621.md`. This committed document owns the current task list; those private files preserve historical evidence, not a competing plan.

### Notes, Library and linked commitments — 2026-09-22

The dedicated `/notes` and `/library` pages reuse the Document facet and shared Tiptap draft store. Notes offer a list beside the writer, recoverable autosave and explicit checkpoints without replacing newer typing. Creation opens directly into continued writing; renaming advances only the acknowledged local metadata revision. Mobile selection/back restores keyboard focus. Library searches current saved text (including the extraction of the current original), filters by type and sorts deterministically. It groups extraction records beneath their original and reads the selected original and pinned extraction together. Legacy artifact routes remain available.

Creating a task from a document atomically writes the canonical Task, TaskArtifact relationship and audit under an idempotency receipt. Task detail opens linked source documents in context. No migration is needed; schema remains `0022_record_work`. Alfred's note-list/writer continuity and silent autosave informed the interaction; no Alfred storage model or parallel note/memory system was imported.

Validation: `make check` passed with 309 PostgreSQL tests, 76 UI unit tests, 21 companion checks, 15 offline eval contracts and the production Next build. The focused notebook tests cover creation, draft recovery across selection/reload, slow checkpoint/new typing, rename/checkpoint, linked task/source navigation, content/type search and mobile focus. Existing document/navigation regressions pass. Final frontend lint/types pass; the pre-existing unused Badge warning remains. Eighteen focused notebook/document browser cases pass in aggregate, plus the existing navigation checks. Settled desktop/mobile axe reports zero violations and no overflow; the desktop incomplete item is the synthetic account stub (a span label), not production Clerk UI. Desktop/mobile visual review uses synthetic data only. API/web and all four application workers were rebuilt and are running with port 3001 health and API readiness verified; no actual mail, provider purchases or application submissions were exercised.

Still active: integration of the isolated daily-task experience, application-preparation automation, true email reply targeting and broader frontend/provider verification. General routine scheduling and final autonomous submission policy remain unresolved.

### Recognized application identity — isolated implementation

Branch `application-identity` extends `6cf0198` with a shared fixed-reader job identity, domain validation and immutable package persistence, automatic same-posting continuation, different-posting separation and a canonical posting link in Applications. Known-host parsing covers explicit URL shapes for the five target providers; unsupported/custom URLs retain manual continuity. Cross-device and owner boundaries remain, and identity changes do not overwrite historical packages. The native reader still invokes AgentBrowser; Direct browser explicitly runs the fixed reader and labels that mode. No schema migration is needed; companion version is `0.4.5` only in this isolated worktree.

Non-browser verification passes: 516 backend tests and 322 UI/unit tests, including 76 actual fixed-reader cases and 33 new actual-popup cases. After the encoded Greenhouse embed-path correction, all 45 identity backend cases passed again. Lint/format, mypy, frontend types, generated contracts, extension syntax, diff checks and the production Next.js webpack build pass. The two full-backend warnings are existing Starlette and SQLAlchemy warnings. An independent parser comparison identified the encoded-path mismatch and it was fixed. Both reader modes now bind the full URL locally before writes; query data remains absent from durable posting links and snapshots. Raw logs are ignored `.local/identity-*.log`. No real browser, provider/model calls or application submission is performed. Root `frontend-redesign` remains pushed at `2ad39e7`, with companion `0.4.3` and the same running smoke-test services.

### Daily workspace — isolated implementation

Branch `daily-workspace`, based on `819454b`, adds owned SQL work queues and timezone-aware daily tasks, an Overview organized around these records, and honest task-state controls wired into the task inspector. Exact action reviews, ongoing task/opportunity conversations and saved artifact versions remain the only authority-bearing paths. Standalone run inspection reuses RunActivity; browser attention is a saved summary with a Browser link. The new GET routes neither mutate recovery state nor call providers. No schema migration is needed.

Validation completed: 471 PostgreSQL/backend tests and 213 React/jsdom unit tests pass, including eight new backend cases and the task/queue/detail interaction regressions. Ruff/format, mypy, frontend lint/typecheck, generated-contract checks, diff checks and the production Next.js webpack build pass. The two backend warnings are existing Starlette and SQLAlchemy warnings. Raw logs remain in ignored `.local/daily-*.log`. Browser QA is skipped at the user’s request. The running root branch `frontend-redesign` remains at pushed commit `2ad39e7`, with extension `0.4.3`; this work is local and not deployed. No actual mail, model/provider requests, application submission or running-service change was exercised.

## Implementation Tasks

Each task derives from an accepted finding. Estimates are rough planning estimates, not measured runtime. P1 fixes block release; P2 work should land with the same implementation effort. The subsequent user-approved UI implementation is included in the status notes below.

- [x] **T1 (P1, human: 3–5h / Codex: 30–50min)** — Preserve record/profile drafts and original revisions. Opening revisions remain pinned through dirty refetch, conflict and pending-save races. Failed profile refetch retains the mounted draft with local retry; reload/keep/discard choices are explicit. Regressions live in `record-editor.test.tsx` and `settings.test.tsx`.
- [x] **T2 (P1, human: 2–3h / Codex: 20–35min)** — Pin artifact review content, reason and submitted version. Immutable submission snapshots bind version/hash/decision/reason; a new version requires a deliberate switch and dirty-review discard. Refetch, retry and pending-edit regressions live in `record-detail-review.test.tsx`.
- [x] **T3 (P1, human: 3–5h / Codex: 30–60min)** — Scope private workspace/cache state to authenticated identity. `providers.test.tsx` covers unresolved identity, unchanged-user reuse, sign-out/re-entry and A→B late-response isolation. Real Clerk session journeys remain part of deferred T8 provider QA.
- [x] **T4 (P2, human: 3–5h / Codex: 30–50min)** — Retain keys for receipt-backed write intents. `retained-intent.ts` and workspace callers preserve exact submitted bodies through ambiguous manual retry, separate independent account operations and reset only the confirmed intent. Definitive connected-request/spending failures permit an explicit fresh request; running or unknown outcomes retain their key. Helper, account and proposal-save regressions cover these distinctions.
- [x] **T5 (P2, human: 2–3h / Codex: 20–35min)** — Add complete states and local retry to review/step/command panels. Artifact reviews, agent profiles/runs/steps and browser devices/commands distinguish loading, empty, failed and stale cached results, with targeted retry and synthetic regressions.
- [x] **T6 (P2, human: 1–2h / Codex: 15–25min)** — Paginate memory management. Bounded pages, counts and offset repair are implemented; `memory.test.tsx` verifies note 101 is reachable/editable and archiving the final item repairs offset 90 to 60.
- [x] **T7 (P2, human: 2–4h / Codex: 25–45min)** — Establish frontend behavior-test infrastructure and integrate it into checks. Source: finding 7. Files: `apps/web/package.json`, lockfile, `vitest.config.ts`, test setup, `src/**/*.test.{ts,tsx}`, `Makefile`. Verify independent Vitest/Playwright discovery, non-watching execution, and failing repros becoming passing tests alongside T1–T6.
- [ ] **T8 (P2, human: 3–5h / Codex: 35–60min)** — Test the authenticated forwarding boundary and critical real-provider journeys. **Automated boundary implemented:** 15 route-handler cases cover missing/expired sessions, rejected origins/paths/oversize bodies, credential/header isolation, exact write forwarding, downloads, streaming/disconnect and safe errors. Provider/component tests cover identity isolation and edit races. Real signed-in Clerk A/B and connected-provider journeys are deferred to the user; mocked sessions do not establish those results.
- [x] **T9 (P2, human: 2–4h / Codex: 25–45min)** — Split ordinary screens from conditional rich rendering. A client section dispatcher loads the selected screen; record details, conversations and rich responses load when shown. `ActivityList` is independent of record detail. Local error boundaries retry failed loads without clearing surrounding input. Production build diagnostics show first-load uncompressed JavaScript reduced from 3,034,660 to 1,038,832 bytes for `/[section]` (65.8%) and 2,925,414 to 1,042,561 bytes for `/` (64.4%). These are build-size measurements, not network-transfer or latency benchmarks.

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

## Historical implementation plan

The original plan ordered shared workspace edits as T7 test foundation → T3 identity → T4 operation keys → T1 drafts → T2 reviews → T5 panel states → T6 memory → T8 integration → T9 production bundle verification. Each remedy includes its tests. The later completion pass kept overlapping component edits sequential and delegated independent backend, forwarding-test and bundle work.

The user approved D1 and requested D2, so T10/T11 are implemented over existing owned API contracts. Their inspector URLs use native history integrated with Next hooks; frame count is bounded, parent content stays mounted, and smaller screens use Radix focus containment. The synthetic browser suite covers this presentation boundary. The record editor and identity provider fixes are dependencies of reliable context retention and remain separately tracked under T1/T3.

## Historical UI-slice exclusions

- Completing every prior hardening task in the UI slice: status is explicit above; pending work is not claimed as shipped.
- Product decisions Q5–Q10 and autonomous submission/outreach: remain in Product Spec.
- A runtime migration, generic service/repository layer or replacement component system: reuse the selected implementation.
- Full backend/security/performance re-audit and paid-provider execution: prior evidence has explicit limits.
- Notion publication, production deployment and private source-data changes: this is local documentation and UI work.

No new deferred TODOs were proposed; all accepted implementation work is above. No separate TODOS.md is needed. New navigation and appearance paths have maintained synthetic checks; broader auth and mutation risk remains as listed. LLM prompts/tools are unchanged, so no new eval scope is required.

## Historical review findings — before the completion pass

The findings and review report below describe the earlier consolidation checkpoint. Current implementation status is in Accepted workspace hardening above; historical open findings are retained as the rationale for those remedies.

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

## Historical GSTACK review report

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

### Contact research and connection notes — 2026-09-22

Implemented the contacts-row research/draft/copy/edit workflow for work-opportunity outreach with a 200-character connection-note limit. Reuses RecordWork tasks, scoped agents, Firecrawl source captures and immutable FollowUp versions. Migration `0027_contact_research` is required before running the updated API; restart workers to load the updated outreach directives/tools. Targeted backend tests cover evidence integrity, uncertain identity, edit preservation, length enforcement and migration round-trip; browser verification uses synthetic records. Paid-model quality and real-founder research remain unverified.


### Standalone chat continuity (2026-09-22)

The Agents composer starts an unscoped `AgentSession` and sends replies with
`continue_run_id`. Replies append durable messages to that session; an active run
accepts additional instructions, and a completed run starts the next turn in the
same conversation. Older one-shot runs are attached lazily with their original
prompt and completed answer preserved. The sidebar groups runs by session; New chat
starts a separate conversation. Migration `0028_standalone_conversations` allows
zero or one work scope and refuses a downgrade that would discard standalone chats.

Cohere catalog entries now require a supported Command tool model, and custom Aya
selections are rejected before enqueueing. Native Cohere API errors are classified
without exposing provider response bodies. Synthetic tests cover continuity,
legacy adoption, idempotency, ownership and unsupported model filtering.

## Shared MCP and generic chat — 2026-09-23

Implemented a request-scoped FastMCP catalog and authenticated local stdio bridge; named expiring/revocable credentials; explicit API operation policies; progressive supervisor discovery; and atomic private lead intake from literal text, an owned saved text version or a saved user message. The generic supervisor can call tools directly or delegate within its pinned limits. Home now uses incremental transcripts, saved-session search/pagination, streamed activity and durable question controls. Bounded middleware persists conversation summaries across turns; exact eligible first-exchange text transformations have a five-minute answer-reuse path with visible provenance and fresh-answer bypass.

Focused synthetic evidence: 17 intake/lead tests, 10 actual HTTP/stdio local-MCP tests, 65 context/conversation/question/runtime tests and 12 application-context/writing regressions passed. Frontend: 349 unit tests and all 99 workspace browser checks passed, with desktop/mobile synthetic screenshots inspected. Independent review also verified the active-run model lock and eliminated duplicate replayed tool cards. These checks make no paid provider calls and do not establish live model quality or measured production latency. Final `make check` passed: 595 backend tests, 349 frontend unit tests, 33 companion/browser tests, 15 offline evaluation-contract tests, generated contracts, lint, types and production build. The full workspace browser suite separately passed 99 tests. A final 38-test MCP/context/persistence run covered the actual HTTP lead-intake path and the reviewed compaction edge; all passed. Docker API, execution-worker and web images also built successfully.

See [local setup and tool policy](local-mcp.md). Migrations `0030_mcp_clients` and `0031_chat_context` add credentials, compacted context and answer provenance; existing transcripts remain intact.

Local Compose was rebuilt and restarted with these images. Migration `0031_chat_context` applied; API readiness, web health and worker readiness passed. The local MCP credential endpoint rejects unauthenticated requests. This is local verification, not an external deployment or a paid-model quality benchmark.

## Focused-work prompt optimization — 2026-09-23

Implemented the confirmed productivity decisions in `agents/skills/opportunity-work.md`, research/outreach/application directives and the shared writing skill. The supervisor remains general; career work gets explicit priority, completion and next-action rules. Research gains read-only approved-profile access for the dossier. Quick connection-note settings and existing action/approval/persistence contracts remain unchanged. Product and Tech Specs record scope and remaining decisions.

Added seven synthetic scenarios in `apps/api/evals/productivity_cases.json`, retaining the original seven. Suite revision `2026-09-23.1` has fourteen cases and 42 judge calls. Fixture loading derives evidence digests; contract tests derive case/call counts and now remove every case for a platform when checking missing coverage. The fixed rubrics assess source authority, requested mode, relationship-specific intent and honest partial completion. Original prompt/config/rubric files are preserved in the ignored local baseline directory.

Validation: `make eval-check` passed 15 tests; configuration contracts plus existing profile/skill-loading coverage passed 11 tests; evaluation Ruff lint/format and `git diff --check` passed. The running API loaded the revised mounted agent configuration successfully. Newly created runs load it; existing snapshots stay pinned. No frontend/backend domain behavior changed, so this pass used targeted checks rather than rerunning the whole workspace build. No paid generation/judging, model-quality improvement or end-to-end task completion is claimed.

The learning article in `docs/learning/eval-driven-agent-development.md` was updated in Notion Command Center with Status=Blogs, using synthetic examples and the actual validation results. It explains the fixture/capture/judge distinction, controlled comparisons and the added read tool as a separate experimental variable. Recorded-model baseline/candidate evaluation remains pending a reviewed plan; the generated plan retains zero allowance.


## Evidence previews and Strands experiment — 2026-09-24

Implemented smaller model-facing evidence pages without changing source storage: document reads default to 4,000 characters, saved lead excerpts to 400 characters when exact full-source access is granted. Canonical version IDs, provenance and pagination survive projection. Exact document retrieval now reaches beyond the former 200,000-character offset ceiling and preserves boundary whitespace. The three-source fixture measures 9,999 → 2,483 UTF-8 bytes (75.2% smaller); this is not a model-token savings claim.

An optional pinned Strands worker shares the existing scoped MCP, model factory, spending, compaction, retry limits, steering and durable activity controls. All existing profiles remain Deep Agents. The single-agent experiment rejects specialists, skills, JEV routing, durable questions and interrupted-run resume; no default runtime or deployment was changed. See [implementation and setup](strands-experiment.md).

The user selected offline comparison only with $0 API spend. The final matched research/drafting/document comparison passed all 12 strict scripted outcomes using gpt-6-sol/medium profile metadata, with matching runtime configuration hashes and current source hashes. No provider calls were made. Reports distinguish synthetic usage, model attempts, actual scripted calls, reserved live calls, known usage cost, unknown reservations and latency distributions; both runtimes share a deadline. [Benchmark instructions](runtime-benchmark.md) describe the separate gated live path, which was not executed.

Validation: full `make check` passed 781 backend tests, 378 frontend tests, 33 browser/extension tests and 18 offline evaluation contracts, plus lint, Python/TypeScript checks, generated contracts and the production web build. The final benchmark-only deadline change and its five additional cases were verified separately in the 16-test benchmark suite, with Ruff and targeted mypy passing. The adapter suite contains 25 tests, including actual SDK and PostgreSQL worker/spending/event integration. Independent task and cross-feature reviews passed after corrections. Existing transaction/deprecation/color warnings remain. Raw full-check log: `.local/strands-check.log`; final synthetic report: `.local/runtime-benchmark/20260924T095711Z-700f288e2f654dd382d0678df8280d8c/report.json`. No live quality, invoice savings, deployment or outbound action is claimed.
