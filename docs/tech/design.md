# Command Center experience and design

**Parent:** [Tech Spec](../tech-spec.md). **Revision:** 2026-09-21-r6. **State:** connected workspace and browser companion implemented; verification in progress. [Product Spec](../product-spec.md) owns product requirements.

## Direction and existing components

Use the user's CRM screenshots in `mockups/` and [trycrm.ai](https://trycrm.ai) as references. The user requested the restraint and attention to detail associated with Jony Ive and Steve Jobs, with maximum appropriate reuse of prebuilt shadcn components. This is an operating workspace: records and next actions carry the hierarchy. Dark surfaces follow the selected mockups and the personal desktop-work setting; they are not a category default.

Use official shadcn/Radix Nova components for the sidebar, breadcrumbs, tables, forms, sheets, dialogs, tabs, selects, feedback and search. Use installed Vercel AI Elements for conversations, generated Markdown and tool results. Reuse these sources; do not introduce a competing component system. Geist is the interface typeface. Semantic CSS tokens in `apps/web/src/app/globals.css` are authoritative: background `#101213`, sidebar `#161819`, panels `#17191a`, foreground `#edf0ef`, muted text `#9ba5a2`, borders `#2a2e2f`, primary `#58cfaa`. Reserve mint for active navigation and primary actions. The 224px sidebar, 56px header, modest radii and thin separators organize dense records. Desktop controls are 13–14px; generated prose is 16px. Avoid decorative gradients, patterned agent backgrounds, repeated promotional cards, fabricated metrics or fake activity.

## Information hierarchy

The first three questions are: what needs my attention, where is this opportunity, and what did my agent actually do?

```text
Clerk sign-in → personal workspace
  Workspace
    Overview → pipeline stage or upcoming task → record detail
    Opportunities → linked company / contact / role
    People · Companies · Roles · Tasks · Artifacts
  Assistants
    Agents → choose profile → request → saved run → tools + result
    Browser companion → pair → share current form → propose → review/apply
    Memory → inspect notes/preferences → create/edit/archive
  Manage
    Activity → dated changes
    Settings → profile + provider connections
```

Overview shows actual counts, stage distribution and upcoming tasks. A first workspace is empty and offers a primary create action; synthetic examples are an explicit opt-in. Record lists provide bounded pagination, search and relevant filters. Detail sheets retain list context, expose linked records and offer edit/archive actions. Artifact versions and their reviews remain adjacent: approving one version does not approve a later draft.

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

At desktop widths, retain the 224px sidebar and table context. Below 768px use the prebuilt off-canvas sidebar; record details occupy the full viewport width. Keep table overflow inside its region rather than widening the page. Forms use one column on mobile and text inputs use 16px to avoid browser zoom. Primary controls have at least 44px touch height on mobile. Sidebars scroll on shorter screens so account controls remain reachable.

Use semantic landmarks, real buttons/links, visible field labels, dialog/sheet titles and descriptions, keyboard dismissal/focus restoration supplied by Radix, and visible focus states. Status always includes text, not color alone. Announce mutation feedback through the toaster; keep durable errors inline. Respect reduced motion; content remains visible without animation. Theme selection and scrollbars. Source links in generated prose distinguish visited state. Readable contrast takes precedence over decorative subtlety.

## Scope boundaries and remaining product design

The current slice covers personal CRM records, tasks, artifacts, bounded research/drafting runs, memory, provider setup and paired manual browser fill. Autonomous campaigns, application submission, upload support, imports, verified candidate answers, multi-turn sessions and multi-account policy still follow the open Product Spec decisions. These are future workflow decisions, not hidden buttons in the current UI.

Eve was evaluated when the user invoked its skill. Its TypeScript durable-session runtime overlaps the selected Python LangGraph/Celery execution layer. Retain the selected runtime for this slice; any Eve migration needs an explicit architecture decision. AI Elements is a presentation library and works with the existing API-backed runs.

## Design review — 2026-09-21

Review target confirmed by the user: current Command Center design and agent experience. The separate `sections/review-sections.md` referenced by the installed skill is absent; the same seven passes are embedded in its `SKILL.md` and were read. No design generator is installed; existing user-selected screenshots and live synthetic desktop/mobile captures supplied visual evidence. No new mockup approval is claimed. There is no Git commit history or branch diff baseline yet. This is a native review, not an independent engineering clearance.

| Pass | Before → current | Findings and disposition |
| --- | --- | --- |
| 1. Information architecture | 6 → 8 | Old document deferred the UI and omitted agent/memory/browser navigation. Reconciled to the user's accepted implementation scope and current hierarchy. |
| 2. Interaction states | 6 → 8 | Generic state instructions lacked concrete run/tool/browser outcomes. Recorded existing ledger states and integrated requested AI Elements execution panels. |
| 3. Journey and emotional arc | 7 → 8 | Added the accepted create/research/review/fill journey and explicit trust cues. Future campaign policy remains outside this slice. |
| 4. Generic-design risk | 7 → 8 | OPERATE mode. Removed patterned agent background; interactive metrics/stage links retain a functional purpose. No stock hero, glow or decorative feature grid. |
| 5. Design system | 7 → 8 | Reconciled tokens to the implemented theme; official shadcn and AI Elements provide one component vocabulary. Fixed upstream React ref usage without type/lint suppression. |
| 6. Responsive/accessibility | 6 → 8 | Mobile sheet was 75% width and cramped; corrected full-width mobile/500px desktop behavior. Added mobile input/control sizes and short-screen sidebar scrolling. Desktop/mobile screenshots inspected. |
| 7. Decisions | Unscored | No new product tradeoff was approved by this review. Existing user decisions authorize the corrections above. Eve adoption and future campaign policy remain explicit future decisions. |

Initial overall score: 6/10. Current design specification: 8/10, using the lowest rated pass. These are design judgments, not a claim of exhaustive accessibility certification. Litmus: brand YES; primary workspace anchor YES; headline scan YES; one job per section YES; cards serve navigation/grouping YES; motion limited to meaningful state YES; shadow-free clarity YES.

Implementation tasks: verify AI Elements against saved run fixtures; verify browser fill rejection and non-submission on the controlled fixture; complete lint/types/build; preserve responsive capture evidence. No speculative features are added by the review. Current task completion and verification evidence live in [HANDOFF.md](../HANDOFF.md).

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
| --- | --- | --- | --- | --- | --- |
| Design | User invoked plan-design-review and confirmed current workspace | UI hierarchy, states, reuse and responsive behavior | 1 | Native design review complete | Six rated passes 6/10 minimum → 8/10; existing user decisions retained; no new product tradeoff approved |
| Engineering | Not run as an independent review | Architectural release review | 0 | Not evaluated | Automated tests/builds are reported separately |
| Outside voice | Not run | Independent second opinion | 0 | No coverage | Do not infer outside validation from native review |

**VERDICT:** Current workspace design reviewed. Independent engineering release review has not been performed; this is not shipping clearance. Open campaign policies remain in Product Spec and are outside this review's scope.

NO UNRESOLVED DECISIONS
