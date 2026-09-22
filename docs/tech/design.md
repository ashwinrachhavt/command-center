# Command Center experience and design

**Parent:** [Tech Spec](../tech-spec.md). **Revision:** 2026-09-21-r9. **State:** same-page workspace and appearance controls implemented locally; broader hardening remains tracked in Engineering. New agent interaction contracts below are documentation, not implemented UI. [Product Spec](../product-spec.md) owns product requirements.

This is the canonical design document; do not add a competing root DESIGN.md. Requirements below describe the intended experience. [Engineering](engineering.md#accepted-workspace-hardening) distinguishes accepted fixes from implemented behavior; dated checks live there and the latest session is in [HANDOFF](../HANDOFF.md).

## Direction and existing components

Use the user's CRM screenshots in `mockups/` and [trycrm.ai](https://trycrm.ai) as references. The user requested the restraint and attention to detail associated with Jony Ive and Steve Jobs, with maximum appropriate reuse of prebuilt shadcn components. This is an operating workspace: records and next actions carry the hierarchy. Dark surfaces follow the selected mockups and the personal desktop-work setting; they are not a category default.

Use official shadcn/Radix Nova primitives and installed Vercel AI Elements. Geist remains the interface typeface. The Appearance popover uses the downloaded [Kibo UI Theme Switcher](https://www.kibo-ui.com/components/theme-switcher), discovered through [Awesome shadcn](https://www.shadcn.io/awesome/registries), and the official shadcn Popover. The downloaded switcher is adapted for pressed states, keyboard focus, larger mobile controls, reduced motion and hydration-safe mounting. Its MIT notice is retained in `apps/web/src/components/kibo-ui/LICENSE.md`.

`apps/web/src/app/globals.css` owns semantic colors. Users choose Light, Dark or System plus Graphite, Teal, Blue or Violet. System and Graphite are defaults. Appearance persists in this browser, including across tabs; it is not a server-synced user preference. Accent colors affect primary actions, focus and active marks; status meanings stay fixed. Light uses near-white surfaces and dark text; dark uses charcoal surfaces and light text. Toasters and Clerk appearance reference the same theme. Keep the 224px sidebar, 56px header, modest radii and thin separators. No promotional agent cards, decorative gradients or fabricated activity.

## Information hierarchy

The first three questions are: what needs my attention, where is this opportunity, and what did my agent actually do? The user's latest feedback is that the current UI is clunky, has too many CTAs and feels AI-generated. The user approved the same-page replacement preview and then requested selectable themes and accents. Those directions now govern the implemented composition.

```text
Clerk sign-in → personal workspace
  Workspace
    Overview → pipeline stage or upcoming task → record detail
    Opportunities list + selected record → related company / contact / role in place
    People · Companies · Roles · Tasks · Artifacts
  Assistants
    Agents → choose profile → request → saved run → tools + result
    Browser companion → pair → share current form → propose → review/apply
    Memory → inspect notes/preferences → create/edit/archive
  Manage
    Activity → dated changes
    Settings → profile + provider connections
```

Overview shows actual counts, stage distribution and upcoming tasks. A first workspace is empty and offers a primary create action; synthetic examples are an explicit opt-in. Record lists provide bounded pagination, search and relevant filters. Record detail occupies the adjacent main pane; related records use one bounded inspector stack with Back and Close. Editing and archiving remain explicit. Artifact versions and their reviews remain adjacent: approving one version does not approve a later draft.

Accepted interaction fixes: retain dirty record/profile drafts and their original revisions across refresh and failed saves (T1); keep displayed artifact content, reason and submitted review bound to the opened immutable version until an explicit switch (T2, still pending); gate private content while identity resolves and isolate cache/UI state when the signed-in user changes (T3). These outcomes are already approved, not new design choices.

Agent requests are independent runs, not an implied continuous conversation. A run shows the chosen profile, user request, actual tool results and final output. State comes from the durable ledger. Generated Markdown uses AI Elements `MessageResponse`; it does not execute HTML or load remote images. Tool panels show execution evidence, not hidden reasoning or the system prompt. Missing provider credentials have an explicit configuration action. Skills and tool access are pinned when a run is created. Memory is user-editable context, visibly marked human/agent, and is never represented as verified candidate facts or permission.

## Interaction states

| Feature | Loading | Empty | Error | Success | Partial / stale |
| --- | --- | --- | --- | --- | --- |
| Records | Skeleton rows in the table region | Explain the record's purpose and offer create; filtered-empty offers clear search | Inline message and retry | Saved record opens in context; mutation toast | Stale revision asks for refresh; entered text stays available after failure |
| Record editing | Disable duplicate save while pending | Visible labels and required fields | Field/request message without closing | Close editor and invalidate affected data | Failed save keeps values; a repeated transport request retains its idempotency key |
| Artifacts | Version list/content loading state | Create a draft | Visible append/review failure | Immutable new version or version-specific review | Older reviews remain with their original version |
| Agent runs | Queued vs running text, polled state | Purposeful prompt suggestions and profile selector | Explain failed/interrupted run; start a new run deliberately | Formatted answer and expandable tool results | Cancellation stops subsequent work; an in-flight call may already have happened; never silently replay it |
| Browser companion | Pair/share/apply status | Instructions to pair and share the active page | Expired pairing, stale form and revoked device messages | Filled fields plus instruction to review the page | Changed document rejects before filling; uncertain partial fill requires inspection, not automatic retry |
| Memory | Loading rows | Explain notes/preferences and offer first note | Retain editor content and report error | Note saved with source marker | Optimistic revision prevents overwriting another edit |
| Integrations | Independent provider checks | Configuration instructions | Provider unavailable with remaining workspace usable | Actual connected/configured state | Configured credential does not claim provider execution has been tested |

Implementation gaps remain: T4 retains one operation key across an ambiguous failure and manual retry; T5 supplies independent loading/empty/error/stale/retry states for reviews, agent steps and browser commands; T6 makes every memory note reachable with bounded pagination. In T1 a 409 keeps entered text and the original revision until deliberate reload/discard; a successful save must not erase newer input typed while saving. The table is an acceptance contract, not proof that these states are all implemented.

## Accepted journey storyboard

| Step | User does | Intended feeling | Interface support |
| --- | --- | --- | --- |
| 1 | Signs in | Oriented | Brand, short explanation, familiar Clerk sign-in |
| 2 | Creates a company and opportunity | In control | Labelled forms, linked company lookup, visible save result |
| 3 | Adds a follow-up task | Organized | Due date and priority; completion appears in activity |
| 4 | Asks an agent to research or draft | Informed | Profile, scoped tools, queued/running state and inspectable results |
| 5 | Reviews an artifact version | Confident in the exact draft | Content beside version history and review reason |
| 6 | Shares and fills a browser form | Aware of the target | Exact site/form, proposed values, explicit Apply, no automatic submission in this slice |
| 7 | Returns later | Continuity | Persistent records, run outcomes, memory and audit |

Within five seconds, navigation and the current task should be evident. Within five minutes, a record and first useful next action should be saved. Long-term trust comes from stable identities, inspectable changes and clear uncertainty, not a promise that every agent action succeeds.

## Responsive and accessibility contract

At desktop widths, retain the 224px sidebar and a 260px record list beside the detail. At 1280px and above, related content docks in a 360px pane. Below 1280px, it overlays from the right beneath the header, with an explicit origin label, trapped keyboard focus and an inert parent. Below 768px, the list/detail uses one panel at a time with Back to list; related content uses the available width and the navigation uses the prebuilt off-canvas sidebar. Keep table overflow inside its region rather than widening the page. Forms use one column on mobile and text inputs use 16px to avoid browser zoom. Primary controls have at least 44px touch height on mobile. Sidebars scroll on shorter screens so account controls remain reachable.

Use semantic landmarks, real buttons/links, visible field labels, dialog/sheet titles and descriptions, keyboard dismissal/focus restoration supplied by Radix, and visible focus states. Status always includes text, not color alone. Announce mutation feedback through the toaster; keep durable errors inline. Respect reduced motion; content remains visible without animation. Theme selection and scrollbars use semantic colors. Source links in generated prose distinguish visited state. Readable contrast takes precedence over decorative subtlety.

## Scope boundaries and remaining product design

The current slice covers personal CRM records, tasks, artifacts, bounded research/drafting runs, memory, provider setup and paired manual browser fill. Operator CSV/cached-Notion import exists outside the portal. Portal import staging/live sync, autonomous campaigns, application submission, upload support, verified candidate answers, multi-turn sessions and multi-account policy remain future design. These are future workflow decisions, not hidden buttons in the current UI.

Eve was evaluated when the user invoked its skill. Its TypeScript durable-session runtime overlaps the selected Python LangGraph/Celery execution layer. Retain the selected runtime for this slice; any Eve migration needs an explicit architecture decision. AI Elements is a presentation library and works with the existing API-backed runs.

## Approved workspace direction — D1 and D2

**D1, direct user decision:** when an opportunity is open, opening Contacts must keep the opportunity context. The user approved the synthetic same-page preview with “Yes looks good.” **D2, direct user request:** add light/dark themes, selectable accents, downloadable shadcn ecosystem components and Vercel AI Elements. Specific palette values are implementation choices, not claims of separate user approval.

The public embedded demo on [trycrm.ai](https://trycrm.ai/) informed the list/detail composition and record tabs. Inspection covered the public page, not signed-in product behavior. The original HTML direction is at `~/.gstack/projects/command-center/designs/workspace-simplification-20260921/index.html`; the current reviewable fixture uses the real React components via `npm run preview:workspace` on port 4318. Both contain only synthetic data. No image-generator mockups were produced.

Implemented interaction rules:

- Selecting a record splits its list and detail on desktop. Main list search, filter, sort, page and scroll state remain mounted while related content opens.
- CRM navigation, search results and linked-record buttons open a directory or record in a same-page inspector. Selecting the current main section closes related content without clearing the selected record. Modified link clicks still support opening a full route deliberately.
- `record` and repeated `inspect` URL parameters identify selection and a bounded stack (maximum eight frames). Browser Back/Forward and explicit Back/Close work. Previous frames stay mounted while inspecting a nested record; focus returns to its trigger. A failed lookup leaves the parent available and exposes Retry.
- Directories retain search/pagination and a local create action. Record editing and archive confirmation remain available. A record draft keeps its opening revision across refresh/409; a successful save cannot discard text typed while the request was pending. Profile draft hardening remains T1 work.
- Overview prioritizes tasks, a compact pipeline and activity. Repeated agent promotions, the global agent CTA, motivational headings and metric-card mosaics were removed. Agents have their own run workspace; opening that tool remains deliberate navigation. No opportunity-scoped AI conversation is claimed.
- Appearance has one header control. Four accent palettes work in both modes; System follows device changes. Selection is restored on reload. Local preference storage contains no record data.

## JobPilot design inspiration

The neighboring JobPilot source at `68a72c71` was inspected read-only. Its workspace tabs and attention strip reinforce keeping work and the next needed action together. Its application detail pairs activity with the exact submitted resume/variant, posting and correspondence. These are useful future evidence views for this product, subject to Product Spec decisions. Its current MUI theme is dark-only, so it is not the theme implementation used here. [Engineering](engineering.md#jobpilot-reuse-assessment) records the concrete reuse choices and compatibility limits. No JobPilot source, runtime or private data was imported.

## Simplify Copilot reference — agent interview

**Research checked 2026-09-21; Copilot interaction and user-submit boundary approved in AR-5.** The user asked to inspect Simplify and then selected filling/generating answers with personal review/submission for the first version. Exact feature/portal parity remains to be scoped. The reference product is Simplify Copilot at `simplify.jobs`. Public landing-page visuals were inspected in a clean browser; official help supplies the behavior below. No signed-in account, installed-extension execution or real application was tested. The existing review report below concerns the prior workspace UI, not this new agent design.

| Reference behavior | Evidence and design relevance |
| --- | --- |
| Work beside the application | Copilot opens a side panel on a supported application. It groups resume, cover-letter, common-field and unique-question controls, then fills the page after the user's action. This supports keeping the application context visible rather than requiring manual answer entry in a separate workspace. [Copilot guide](https://help.simplify.jobs/articles/2415391-using-copilot-to-autofill-applications) |
| Contextual AI answers | Uses job description, company/role, profile and resume context; supports one answer or several; generated text is editable in the application. [Essay-answer guide](https://help.simplify.jobs/articles/7306766-answering-essay-questions-with-copilot) |
| Reusable answers and documents | Exact-question matches can reuse saved responses. A saved resume can be selected and uploaded. These are reference behaviors; Command Center's answer-reuse semantics and document scope still need decisions. [Saved answers](https://help.simplify.jobs/articles/7306766-answering-essay-questions-with-copilot), [resumes](https://help.simplify.jobs/articles/2415391-using-copilot-to-autofill-applications) |
| Configurable assistance | Settings enable AI answers, selected field categories and continuous multi-page autofill. The multi-page description does not clearly identify who performs final submission. [Settings](https://help.simplify.jobs/en/help/articles/8686025-manage-autofill-settings-in-the-simplify-extension) |
| User review and submission | The main Copilot workflow says the user reviews, edits and submits. Its tracker can then record the application. [Copilot guide](https://help.simplify.jobs/articles/2415391-using-copilot-to-autofill-applications) |
| Separate unattended product | Simplify Autopilot completes and submits on the user's behalf; its comparison explicitly distinguishes this from Copilot. Selecting the extension as a reference does not select Autopilot's authority. [Autopilot comparison](https://help.simplify.jobs/articles/1784339-getting-started-with-autopilot) |

```text
Documented Copilot reference
  Signed-in application page + side panel
    -> profile / selected resume / job context
    -> standard-field fill + individual or bulk AI answers
    -> editable application fields; optional multi-page assistance
    -> user review and Submit
    -> application tracking
```

The settings page says continuous filling proceeds until submission, while the main guide and newer product comparison explicitly assign submission to the user. Treat the final behavior of that setting as unverified; do not describe automatic Copilot submission as established. Command Center's boundary is independently explicit: fill the current page, support resume upload, collect unknown personal answers together and leave Next/Submit to the user. Greenhouse, Lever, Ashby, Workday and iCIMS are the required initial platforms; field/tenant coverage remains to be verified. Unattended submission remains a later goal.

## New agent experience — interview draft

Confirmed direction: one lead with visible specialists using Deep Agents on LangGraph; a reviewed Command Center profile backed by selected documents; background research/drafting on an always-on backend; local Chrome application assistance; isolated research scripts; and reviewed external changes through Composio. AR-18 selects work-first dashboard priority, AR-19 selects ongoing conversations per task/opportunity, and AR-20 requires review of proposed reusable memories. These decisions extend the implemented independent-run UI described above; detailed layout and active-turn interaction remain to be reviewed.

- **Profile and sources:** show extracted assertions beside source references, then promote reviewed facts to the reusable profile. Later contradictory mail/pages cannot silently replace them. Missing application facts appear together beside the current form; show what was filled and what still needs the user.
- **Visible delegation:** show the lead's assignment, specialist name, status, concise activity, saved artifacts and actionable questions. Reopening the portal reconstructs activity from persisted events. Show tool/result evidence rather than private reasoning.
- **Work conversation:** keep the lead and visible specialist contributions in the selected task/opportunity's ongoing conversation. Addressing a specialist changes who handles the message without losing the work context. Unrelated work opens another conversation; show its scope clearly so the user does not unknowingly steer the wrong task.
- **Proposed memories:** save ordinary work history automatically. Show suggested reusable notes with their wording, scope and source work, with Edit, Approve and Reject. Unapproved suggestions do not appear as established preferences. Memory review is a separate, batchable queue and does not prevent an otherwise completed task from finishing; personal facts remain in the reviewed profile.
- **Review external changes:** email shows exact sender account, recipients, subject/body and attachments. Calendar/Linear/Notion proposals show the target and intended change. Editing invalidates approval of the prior version. Successful execution shows a provider receipt/link; ambiguous outcomes are labelled and cannot be blindly retried.
- **Browser continuation:** keep the signed-in tab as the work surface. User reviews/clicks Next and requests the next page. A closed tab cannot be filled by the always-on server; saved progress can remain available while a fresh page must be captured on return.
- **Existing answers:** preserve populated fields and distinguish Already filled from Filled by agent. If the user edits while generation runs, keep that edit and report the skipped fill. Offer a replacement only through an explicit revise action; accepting it targets the selected answer rather than replacing the entire page.
- **Resume choice:** preselect the user's general portfolio resume, displaying the exact document/version before upload. Allow an explicit switch to a specialized variant. Tailoring or later file edits do not silently replace the selected default or a prepared upload.
- **Research results:** show the saved document, sources and relevant generated files. Script execution can proceed automatically in its task workspace. Publishing the result to Notion is a separate reviewable change; research remains available if publishing fails.
- **Waiting and recovery:** questions and approval requests remain visible after refresh/restart. Cancelling stops future work and reports any operation whose external result is still unknown. Memory suggestions and artifact review must not look like permission to send or update an external record.

The [technical draft](../tech-spec.md#first-agent-release-architecture-draft) owns state and boundary proposals. The historical design review below does not approve this new agent experience.

### Dashboard and work inspector proposal

**Status: information priority and continuity confirmed in AR-18–AR-20; detailed layout remains proposed.** The dashboard prioritizes work needing attention, work in progress and completed outputs, with agent activity and an ongoing conversation within the task/opportunity. Agents propose reusable memories for review. A live agent view can be a secondary entry point. Preserve the already approved same-page record context and restrained shadcn/AI Elements composition. These choices do not approve every detail of the synthetic preview.

The overview answers three questions: what needs me, what is running, and what is ready. Use rows with explicit work states and next actions. Opening a row preserves the work list and opens the task/opportunity inspector. Keep a separate agent activity view for detailed operational inspection; do not make a network of agent avatars the only way to find an email draft or unfinished application.

```text
Command Center
  Overview                       Selected work: outreach for Northstar Labs
  Opportunities                  Person / company / opportunity / task links
  People · Companies · Roles     Status: awaiting your review
  Tasks                          Lead -> Research -> Outreach
  Artifacts                      Brief | Conversation | Activity | Records
  Agents                         Exact draft v3 and its source context
  Memory                         Review request bound to sender + recipient + v3
  Activity                       Next action: review this draft
  Settings
```

These labels describe a proposal, not a requirement to add every tab or navigation item. Reuse existing record/agent/artifact routes and avoid duplicate work lists. A first implementation can expose detail through one inspector with only the sections relevant to the selected work.

| Surface | Show | Stored records it reads |
| --- | --- | --- |
| Needs attention | Missing personal answers, draft/change review, disconnected browser, failed or uncertain execution | Questions, action intents, browser commands and failed/waiting run states |
| Work in progress | Goal, related opportunity, active specialist, last meaningful activity and elapsed/waiting time | Business task plus current root run and delegation events |
| Ready/recent outputs | Document/draft title, version, authoring specialist and linked work; sent/published only when confirmed | Artifact versions, derivations, action receipts and completed task/run state |
| Work inspector | Brief, conversation, visible specialist timeline, artifacts, sources, approvals and relevant usage | Shared task/opportunity/session/run references and their linked records |
| Agent activity | Real parent/child delegation, tools called, stage/waiting reason, errors and outcomes | Persisted sequenced run events; no hidden reasoning or invented completion percentages |
| Record/evidence detail | Canonical person/company/job/profile facts, source snapshots, timestamps and conflicts | Owned domain records and exact evidence/material versions |
| Action review | Before/after target, exact content, account, attachments, authorization and eventual receipt | Version-bound proposal/approval/attempt records |
| Memory | Proposed/retained reusable notes, source work and edit/review state | Memory records; task activity remains independently stored |

Prefer an activity timeline with compact specialist lanes for parallel work. Offer a small delegation graph only when the actual branching is useful; selecting a node opens the same run/activity inspector. Evidence lineage can similarly show source -> generated document -> approved action -> receipt. Both graphs are read projections of stored relationships. No graph node or attractive status animation substitutes for a confirmed record.

“Store everything” means the meaningful work trail can be reopened: requests, visible responses, chosen context/source versions, generated outputs/scripts, handoffs, questions, approvals, errors and external receipts. Exact storage and retention boundaries are in [Tech Spec](../tech-spec.md#system-of-record-and-dashboard-projections). The UI must distinguish saved local work from a current remote observation, an approved proposal from an executed change, and application filling from actual submission.

Refresh/reconnect must restore the same selected task and real state. Loading, empty, partial, stale, failed and outcome-unknown views remain distinct. Counts and rows agree; a new draft does not inherit an old approval; a user answer removes only its own outstanding question. Private data disappears on account changes. On narrow screens, switch between list and inspector with Back rather than compressing several permanent columns.

A synthetic interactive design preview accompanies this proposal; it is not the implemented dashboard or evidence that its runtime integrations work. The approved light/dark/system theme and same-page UI direction remain the visual foundation.

## Design review — consolidation and implementation

Scope: both active specs and supporting docs, expanded by the user's direct UI requirements and approval. The earlier historical 8/10 score is superseded by this review. Scores assess the design contract and inspected synthetic composition; they do not clear the application for release.

| Pass | Before → after | Evidence and disposition |
| --- | --- | --- |
| 1. Information architecture | 5 → 8 | List, selected record and related content retain context; one prominent create action in the active view. |
| 2. Interaction states | 7 → 8 | Loading/empty/error/retry specified, inspector failure verified, draft/identity protections started; broader T1–T6 work remains explicit. |
| 3. Journey and emotional arc | 6 → 8 | Browse opportunity → contact → company → return is verified without losing selection or list search. |
| 4. Generic-design risk | 4 → 8 | OPERATE surface uses rows, separators and literal labels; promotional cards and redundant agent entry points removed. |
| 5. Design system | 8 → 8 | Official shadcn, Kibo switcher, Geist and AI Elements share semantic light/dark tokens; four readable accents. |
| 6. Responsive/accessibility | 8 → 8 | Desktop docking, mobile origin/back, focus restoration/trap, reduced motion and contrast checks; not exhaustive accessibility certification. |
| 7. Decisions | Unscored | D1/D2 resolved by direct user instructions. Q5–Q10 remain outside this cleanup. |

Step 0 impression: 5/10. Overall minimum: 4/10 → 8/10. A 10 requires complete real-provider recovery journeys, remaining hardening and broader accessibility verification. Litmus: clear identity, one primary visual anchor, literal scanning labels, one job per section, no unnecessary card mosaics; motion is limited to selected-theme feedback and respects reduced motion. No outside review ran because it is configured disabled. No new deferred TODOs were proposed.

## What already exists

Reuse owned list/detail APIs, request receipts, record revisions, TanStack Query, semantic tokens and shadcn/AI Elements. The new context pane is presentation over those contracts. Backend schemas, agent policy, source screenshots in `mockups/` and the existing companion are unchanged.

## NOT in scope

- Autonomous campaigns, outreach, application submission and live Notion sync: open product policy still applies.
- JobPilot runtime integration or MUI migration: this pass assesses compatibility and borrows interaction ideas.
- Account-synced appearance, arbitrary color editing and a second theme library: four browser-local presets meet the request.
- Exhaustive accessibility certification and real Clerk account-switch QA: the current fixture mocks those boundaries.

## Implementation Tasks

- [x] D1/T10 — Implement context-preserving CRM navigation, compact overview and same-page record inspection. Files: `context.tsx`, shell, records, detail, overview. Verify nested inspection, Back, missing records, mobile focus and retained list/tab state.
- [x] D2/T11 — Implement Light/Dark/System and four accent palettes using downloaded Kibo/shadcn components. Files: Appearance/provider, layout/CSS, Kibo switcher, Popover. Verify reload, device-theme changes, keyboard controls and 4.5:1 primary/body/muted text contrast in every palette/mode.

Prior hardening status and remaining acceptance tests are owned by [Engineering](engineering.md#implementation-tasks), not duplicated here.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
| --- | --- | --- | --- | --- | --- |
| Design | `/plan-design-review` + direct UI requirements | Consolidation, hierarchy and states | 1 current + historical review | CLEAN DESIGN PLAN | 4/10 → 8/10; two user directions resolved; real-component fixture inspected |
| Engineering | `/plan-eng-review` | Contracts, implementation and tests | 1 current + historical review | ISSUES OPEN | UI slice implemented; broader hardening remains pending/partial |
| Outside | Configured plan-review provider | Independent challenge | 0 completed this run | DISABLED | No outside coverage or native substitute |

**VERDICT:** Approved UI direction implemented locally. Design review completion does not clear the remaining engineering release gaps.

**NO UNRESOLVED DECISIONS** for this UI slice. Product Spec Q5–Q10 remain explicit future-policy decisions.
