# Command Center — Design Spec

**Companion specs:** [Product](../product/product-spec.md) · [Tech](../tech/tech-spec.md). **Revision:** 2026-09-22-r25. **State:** full-page section navigation, contextual record inspection and appearance controls implemented locally; broader hardening remains tracked in Engineering. New agent interaction contracts below are documentation, not implemented UI. [Product Spec](../product/product-spec.md) owns product requirements.

**Release integration (2026-09-22):** `frontend-redesign` now includes keyword coverage, career row expansion, the daily workspace and posting identity through `ed69ac1`, with companion `0.4.5`. Earlier isolated-branch/build references below record validation checkpoints and do not describe the current checkout. Hands-on browser/provider QA remains user-led.

This is the canonical design specification for navigation, page composition, interactions, visual language and accessibility. Product Spec owns user outcomes and scope; Tech Spec owns data, runtime and API contracts; Engineering owns delivery evidence. Do not create competing design requirements in a root DESIGN.md. Requirements below describe the intended experience. [Engineering](../tech/engineering.md#accepted-workspace-hardening) distinguishes accepted fixes from implemented behavior; dated checks live there.

## Calm workbench cleanup — confirmed 2026-09-22

The user selected a calm workbench: spacious content and compact navigation, guided by the supplied Loan Labs and Perplexity screenshots. Home is the agent conversation workspace. Main navigation is Home, Opportunities, Tasks, Library, Document Vault, Contacts and Companies, followed by workspace tools. Applications and saved roles sit under Opportunities. Notes is a Library collection. Reviewed actions and Jobs are removed from the main sidebar; existing contextual flows and old links remain usable.

Library contains authored notes and saved outputs, including message drafts. All work, Notes and Agent outputs organize existing records. Review status always refers to the current immutable version; saving a new version restores Needs review. The Agent outputs collection uses recorded run provenance, never an inference from writing style. Document Vault contains uploaded originals, their type/metadata, and existing local extraction/retry controls. Extracted text stays with its original; it is not a second Library entry. This is an interface split over one artifact/version lifecycle.

Document links open a centered, scrollable canvas up to 1152px wide, filling the viewport on mobile. Content opens first. The originating selection and filters remain underneath; Back, Close, Escape and browser history restore the context and trigger focus. Related non-document records retain the contextual inspector. Reading text uses a comfortable measure and larger line spacing. Home keeps its composer in the first desktop viewport; secondary controls and conversation history must not obscure the main action.

Structured artifacts display saved fields and nested values instead of a false empty state. Written artifacts keep the text primary and expose other saved fields under Saved details. Zero, false and missing values remain distinguishable. Stored data never creates executable markup or actions. Structured packages keep their existing domain-specific edit path rather than being rewritten through the text editor.

Agents groups current profiles, Connectors, Skills, Workflows and Memory using the reference's understated tabs and catalogue layout. Profile tool/skill assignments are inspectable; model selection remains in conversations. Workflow cards lead to existing actions. Scheduled workflows and editable persistent grant configuration are not implied by the scaffold. Keep Geist, existing Graphite/light/dark/accent choices, 4px spacing increments, 6–12px control/surface radii, visible keyboard focus and restrained motion.

The companion defaults to This browser, reading the active Chrome tab without a separate helper. An explicitly saved AgentBrowser choice is preserved and stays an advanced option. The setup page gives three steps; capture settings and optional cover letters use progressive disclosure. Permission failures identify the next action. No silent reader fallback, automatic Next or Submit is introduced.

## Direction and existing components

Use the user's CRM screenshots in `mockups/` and [trycrm.ai](https://trycrm.ai) as references. The user requested the restraint and attention to detail associated with Jony Ive and Steve Jobs, with maximum appropriate reuse of prebuilt shadcn components. This is an operating workspace: records and next actions carry the hierarchy. Dark surfaces follow the selected mockups and the personal desktop-work setting; they are not a category default.

Use official shadcn/Radix Nova primitives and installed Vercel AI Elements. Geist remains the interface typeface. The Appearance popover uses the downloaded [Kibo UI Theme Switcher](https://www.kibo-ui.com/components/theme-switcher), discovered through [Awesome shadcn](https://www.shadcn.io/awesome/registries), and the official shadcn Popover. The downloaded switcher is adapted for pressed states, keyboard focus, larger mobile controls, reduced motion and hydration-safe mounting. Its MIT notice is retained in `apps/web/src/components/kibo-ui/LICENSE.md`.

`apps/web/src/app/globals.css` owns semantic colors. Users choose Light, Dark or System plus Graphite, Teal, Blue or Violet. System and Graphite are defaults. Appearance persists in this browser, including across tabs; it is not a server-synced user preference. Accent colors affect primary actions, focus and active marks; status meanings stay fixed. Light uses near-white surfaces and dark text; dark uses charcoal surfaces and light text. Toasters and Clerk appearance reference the same theme. Keep the 224px sidebar, 56px header, modest radii and thin separators. No promotional agent cards, decorative gradients or fabricated activity.

## Current knowledge-work revamp

A lead should lead directly to a useful action: open the person/company, inspect context, write a follow-up, save it and choose how to use it. Person detail exposes Follow up and a Follow-ups tab; the composer is contextual and uses shared Tiptap, visible autosave, recoverable drafts and deliberate version checkpoints. Closing a writer preserves unfinished work. Copy, LinkedIn and mail-app actions use saved text; preparing an email pins the exact saved source and opens a separate reviewable message. No send is inferred from copying or opening another app.

Notes, document content, task details and CRM writing share the writer foundation. Documents keep original bytes, selected-version reading and paginated metadata history. Earlier drafts are recovery copies, separate from durable artifact checkpoints and approvals. Library is the full-page destination for notes and generated work; the older Notes route remains supported. Notes keeps the selectable list beside a persistent writer on desktop and provides an explicit, focus-restoring All notes action on mobile. Saving a checkpoint leaves the live editor mounted and preserves newer typing. Library and Document Vault use saved-content search, document-type filters and deterministic sorting; the Vault groups uploaded originals with their pinned extracted text. Document/task links open in context. Company enrichment and contact discovery have contextual actions; broader layout refinement remains active work. Use the supplied `mockups/platform-mockups` connection/settings references; routine controls shown there are references, not evidence of implemented scheduling.

## Application companion

Use a persistent side panel so closing a popup does not interrupt ordinary review. The primary sequence is Page reader → Résumé → Autofill this page → visible results and questions. AgentBrowser and Direct browser are explicit choices; an unavailable helper never silently substitutes another engine. Keep profile/résumé setup and the saved task conversation easy to open. Present counts of filled/attached, failed and unanswered fields; never call a partial result fully filled. Preserve selection and operation identity across reopening, freeze pending choices and offer Start over without deleting saved workspace history. Further edited answers use Save review and fill answers with an automatic fresh capture. Manual sharing/proposal controls are secondary. Next/Submit remain controls on the employer page.

When Autofill captures a different full URL and an existing application is available, show a labelled choice with the earlier application title/site: Continue this application or Start a new application. Do not prepare or fill until that choice is made. Keep the captured choices after panel closure or a lost response; another tab/navigation requires returning to the captured page or starting over. Explain that continuing keeps the task, conversation and saved job description. The application history labels each page and identifies human-confirmed continuation. Exact same-page repeats keep their existing one-click flow.

Applications keeps a Job description card beside the saved preparation. Show source, company when known, checkpoint version and capture truncation. Offer an explicit writer when no description was captured. Use shared Tiptap autosave/recovery and deliberate checkpoints; saving leaves writing open. Reading saved requirements and reopening unfinished edits are separate choices. The companion explains that Autofill saves recognized job descriptions with the form structure.

Application documents follows the job-description card. Keep résumé selection, optional autosaved writing preferences and separate Draft cover letter/Tailor résumé actions together. Explain missing saved requirements before enabling generation. A pending request freezes its original choices and offers recovery with the same identity after reload; do not disguise a retry as new work. Show queued/running/waiting/failed/saved outcomes and source versions in bounded history. Open draft & export uses the contextual document writer, preserving the application underneath. Generated résumé and cover-letter PDFs appear in separate companion selectors. The optional letter starts unselected; its attachment checkbox describes the destination. Each reviewed file field offers Leave unchanged, selected résumé or selected cover letter, with one choice per control. Existing files require a visible replacement choice. Pending operations freeze both document selections; recovering a request preserves the original files. Long filenames stay within mobile width. Saved application packages link each exact selected document version.

Keyword coverage appears within Application documents and reuses its selected résumé and saved job-description checkpoint. This UI was verified at isolated ancestor `d83c6d7` and is inherited by `application-autofill`, with keyword non-browser validation complete and browser QA skipped at the user's request; the stable smoke-test build remains `frontend-redesign` at `2ad39e7` with extension `0.4.3`. Explain that coverage measures text, not ATS ranking or eligibility, and uses no AI generation. Keep optional chosen keywords in a disclosure: commas or new lines separate up to 50 terms of at most 80 characters; an empty editor uses detection, and selected terms may come from outside the description.

Require saved sources before enabling Check job keywords. Show loading, checking, missing-source and retry states; freeze relevant choices while checking. Reset the keyword input and report when actor, application, résumé version or saved job version changes, and clear the report when keyword text changes. Reject a response whose source versions differ from the request. Show percentage/count, detected or selected mode, labelled Matched/Missing lists, and exact links for the saved job, selected résumé and separate readable source when applicable. Missing terms describe text gaps. An empty detection invites a chosen list and shows no percentage; distinguish detected-list truncation from a shortened captured job description. The report does not edit documents, approve facts or change application/task status.

Employment and education editing stays within the Settings profile-fact dialog. Display human-readable entries, with labelled company/school and role/degree fields, explicit current/ended/unknown choices and date precision guidance. Use shared Tiptap for descriptions, durable draft status/recovery and a separate Save proposal/Approve exact revision flow. Legacy source text offers an explicit Map fields action with suggested values and pinned source evidence. Drafts retain their editing base until the user deliberately accepts a newer one. The dialog scrolls within the viewport and keeps a single-column layout on narrow screens.

Career form answers show their section heading beside each field so repeated company/school inputs remain distinguishable. Date/month editors preserve the captured range and step constraints. Occupied groups remain unchanged; ambiguous entry order, unknown components or insufficient date precision appear as manual questions. In isolated companion `0.4.4`, Autofill may add rows through explicit Add controls in an unambiguous empty history section, including a section with no rows yet. Targets come from the saved preparation, with at most ten eligible entries per kind; uncertain chronology means no expansion. Keep progress visible, retain the same row-operation identity through retries, and capture and prepare the expanded page under the same application before filling. Preserve existing values and leave ambiguous sections manual. Next and Submit remain manual. This increment has passed non-browser verification but is not deployed or browser-verified; broader portal coverage and exact Simplify parity remain incomplete.

## Navigation and context contract

**Confirmed user clarification:** full screen means the selected section occupies the main workspace with the persistent navigation/header; it does not request the browser fullscreen API or removal of navigation. Home opens agent conversations; the previous Overview remains available as a secondary route.

| Entry/action | Required presentation | Context and exit |
| --- | --- | --- |
| Main sidebar: Home, Opportunities, Tasks, Library, Document Vault, Contacts, Companies, Agents, Browser companion, Activity or Settings | Navigate to that full section route; update the active item and page heading | No previous section or inspector pinned behind the destination; browser Back/Forward behaves normally |
| Record row within a section | Existing adjacent detail pane, or responsive single detail pane | Retain the list/filter/selection context; Back to list on narrow screens |
| Related record, body directory shortcut, task/output preview or contextual search result | Side inspector/drawer; modal when a short focused task fits better | Keep originating route and selection; explicit Back/Close and focus return |
| Create/edit form, confirmation or bounded review | Labelled dialog or suitable contextual pane | Retain entered values on failure; dismiss without unintended mutation; nested Escape closes the active surface first |
| Independent destination or task needing the main workspace | Full-page route with an explicit navigation affordance | Do not force complex workflows into a tiny overlay merely to stay on the current page |
| External URL or modified link click | Normal browser link/new-tab semantics | Do not intercept external destinations or silently execute external effects |

Choose one contextual surface per task, keep its title and origin visible, and avoid overlapping modal stacks. Inline controls such as filters, tabs and toggles act in place; they do not open a dialog solely because they are in the body. This is a preference for context-preserving work where appropriate, not a requirement to turn every click into an overlay. The shell's main navigation must remain visually distinct from contextual Back/Close controls.

## Design acceptance and implementation status

| ID | Acceptance | Current evidence or remaining work |
| --- | --- | --- |
| DS-01 | Ordinary sidebar clicks from Overview or another page open the requested section, update the URL, and occupy the main workspace without an inspector | Navigation regression covers desktop and mobile; all sections use shared sidebar links |
| DS-02 | Body-linked records open in context; original record/search/tab state survives inspection and close | Existing inspector and nested-record regression coverage |
| DS-03 | Mobile navigation closes after choosing a section; body inspector has a visible origin and restores focus on close | Mobile navigation, Escape/focus and viewport-overflow checks |
| DS-04 | Direct links, refresh and Back/Forward reflect the selected section/record; modified links retain browser semantics | Existing URL-backed record/inspector history; live authenticated route verification remains separate from synthetic fixtures |
| DS-05 | Loading, empty, error, stale and outcome-unknown states are distinguishable; no fabricated activity or completion | Per-surface state table below; delivery gaps remain in Engineering |
| DS-06 | Light/Dark/System and accents remain readable, keyboard controls have names/focus, responsive layouts do not overflow | Theme persistence and contrast checks; broader accessibility audit remains pending |
| DS-07 | Exact artifact/action versions remain visible during review; edits cannot inherit prior approval | Confirmed requirement; outstanding artifact-review hardening is tracked in Engineering |
| DS-08 | Future work conversations, grouped questions, specialist activity and approval flows obey Product/Tech boundaries | Design direction selected; detailed layouts, recovery interactions and new runtime remain proposed |

Use synthetic records for design fixtures and screenshots. Verify UI behavior with deterministic tests; agent-response quality belongs in the selected DeepEval plan, not a visual score. The user's test-authoring convention is pytest with pytest-mock. Current TypeScript UI suites remain implemented evidence until an explicit migration preserves coverage. Do not label a proposed screen or a passing mock fixture as a delivered authenticated workflow.

## Information hierarchy

The first three questions are: what needs my attention, where is this opportunity, and what did my agent actually do? The user's latest feedback is that the current UI is clunky, has too many CTAs and feels AI-generated. The user approved contextual record inspection and requested selectable themes and accents. Their latest clarification requires full-page navigation from the sidebar, with dialogs or side panels for suitable body actions. This supersedes the earlier interpretation that sidebar sections should open over Overview.

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

The isolated daily-workspace Overview prioritizes tasks by day and saved attention/running/output queues; counts and stage distribution remain secondary. The stable smoke-test build still shows the earlier upcoming-task layout. A first workspace is empty and offers a primary create action; synthetic examples are an explicit opt-in. Record lists provide bounded pagination, search and relevant filters. Record detail occupies the adjacent main pane; related records use one bounded inspector stack with Back and Close. Editing and archiving remain explicit. Artifact versions and their reviews remain adjacent: approving one version does not approve a later draft.

Accepted interaction fixes: retain dirty record/profile drafts and their original revisions across refresh and failed saves (T1); keep displayed artifact content, reason and submitted review bound to the opened immutable version until an explicit switch (T2, still pending); gate private content while identity resolves and isolate cache/UI state when the signed-in user changes (T3). These outcomes are already approved, not new design choices.

Tasks and opportunities expose persistent Conversation tabs with a lead or selected specialist. New messages can steer active work; Received/Applied reflects whether a run has consumed the message. Saved activity includes specialist/tool outcomes and links to exact immutable output versions in the related inspector. Standalone requests are available on Home; Agents contains configuration and capability inspection. State comes from the durable ledger. Generated Markdown uses AI Elements `MessageResponse`; it does not execute HTML or load remote images. Tool panels show execution evidence, not hidden reasoning or the system prompt. Missing provider credentials have an explicit configuration action. Skills and tool access are pinned when a run is created. Memory is user-editable context, visibly marked human/agent, and is never represented as verified candidate facts or permission.

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

At desktop widths, retain the 224px sidebar and a 260px record list beside the detail. At 1280px and above, related non-document records dock in a 360px pane. Documents use the centered canvas defined above at every width. Below 1280px, it overlays from the right beneath the header, with an explicit origin label, trapped keyboard focus and an inert parent. Below 768px, the list/detail uses one panel at a time with Back to list; related content uses the available width and the navigation uses the prebuilt off-canvas sidebar. Keep table overflow inside its region rather than widening the page. Forms use one column on mobile and text inputs use 16px to avoid browser zoom. Primary controls have at least 44px touch height on mobile. Sidebars scroll on shorter screens so account controls remain reachable.

Use semantic landmarks, real buttons/links, visible field labels, dialog/sheet titles and descriptions, keyboard dismissal/focus restoration supplied by Radix, and visible focus states. Status always includes text, not color alone. Announce mutation feedback through the toaster; keep durable errors inline. Respect reduced motion; content remains visible without animation. Theme selection and scrollbars use semantic colors. Source links in generated prose distinguish visited state. Readable contrast takes precedence over decorative subtlety.

## Scope boundaries and remaining product design

The current slice covers personal CRM records, tasks, artifacts, bounded research/drafting runs, memory, provider setup and paired manual browser fill. Operator CSV/cached-Notion import exists outside the portal. Portal import staging/live sync, autonomous campaigns, application submission and broader multi-account policy remain future design. Exact résumé uploads, approved facts, multi-turn conversations and one-click assisted filling are implemented locally. These are future workflow decisions, not hidden buttons in the current UI.

Eve was evaluated when the user invoked its skill. Its TypeScript durable-session runtime overlaps the selected Python LangGraph/Celery execution layer. Retain the selected runtime for this slice; any Eve migration needs an explicit architecture decision. AI Elements is a presentation library and works with the existing API-backed runs.

## Approved workspace direction — D1 and D2

**D1, clarified direct user decision:** opening Contacts from an opportunity body action keeps that opportunity context; choosing Contacts in the main sidebar opens the Contacts page. The earlier same-page preview approval did not authorize keeping Overview permanently open or intercepting top-level navigation. **D2, direct user request:** add light/dark themes, selectable accents, downloadable shadcn ecosystem components and Vercel AI Elements. Specific palette values are implementation choices, not claims of separate user approval.

The public embedded demo on [trycrm.ai](https://trycrm.ai/) informed the list/detail composition and record tabs. Inspection covered the public page, not signed-in product behavior. The original HTML direction is at `~/.gstack/projects/command-center/designs/workspace-simplification-20260921/index.html`; the current reviewable fixture uses the real React components via `npm run preview:workspace` on port 4318. Both contain only synthetic data. No image-generator mockups were produced.

Implemented interaction rules:

- Selecting a record splits its list and detail on desktop. Main list search, filter, sort, page and scroll state remain mounted while related content opens.
- Sidebar links open their full section route, including ordinary unmodified clicks. Body search results and linked-record buttons open a directory or record in a contextual inspector. Selecting a sidebar destination clears the prior inspector by navigating to that section. Modified link clicks retain standard browser behavior.
- `record` and repeated `inspect` URL parameters identify selection and a bounded stack (maximum eight frames). Browser Back/Forward and explicit Back/Close work. Previous frames stay mounted while inspecting a nested record; focus returns to its trigger. A failed lookup leaves the parent available and exposes Retry.
- Directories retain search/pagination and a local create action. Record editing and archive confirmation remain available. A record draft keeps its opening revision across refresh/409; a successful save cannot discard text typed while the request was pending. Profile draft hardening remains T1 work.
- Overview prioritizes tasks, a compact pipeline and activity. Repeated agent promotions, the global agent CTA, motivational headings and metric-card mosaics were removed. Agents have their own run workspace; opening that tool remains deliberate navigation. No opportunity-scoped AI conversation is claimed.
- Appearance has one header control. Four accent palettes work in both modes; System follows device changes. Selection is restored on reload. Local preference storage contains no record data.

## JobPilot design inspiration

The neighboring JobPilot source at `68a72c71` was inspected read-only. Its workspace tabs and attention strip reinforce keeping work and the next needed action together. Its application detail pairs activity with the exact submitted resume/variant, posting and correspondence. These are useful future evidence views for this product, subject to Product Spec decisions. Its current MUI theme is dark-only, so it is not the theme implementation used here. [Engineering](../tech/engineering.md#jobpilot-reuse-assessment) records the concrete reuse choices and compatibility limits. No JobPilot source, runtime or private data was imported.

## Simplify Copilot reference — agent interview

The Applications sidebar link opens a full section. Its searchable, status-filtered list preserves context beside the selected application on desktop; mobile shows the detail with an explicit All applications return action. Selection survives reload in the URL. The detail keeps human-reported hiring status distinct from task completion and fill results, presents the next task/due date, and opens linked tasks, conversations, résumés and versions in contextual inspectors. Saved answers are selectable/copyable and retain exact version identity. A failed status acknowledgement offers retry with the same request identity or an explicit reload of current state. Captures outside the recent browser list remain reopenable. Query-free page links are labelled as saved pages, with their limitation disclosed beside the saved package.

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

**Revamp clarification, 2026-09-22:** Gmail remains the user's inbox. In a work context, an explicit Pull email action or explicit user request acquires selected correspondence; display its account, source and retrieval time. Ordinary navigation, composing and follow-up creation must not fetch mail. Use the shared Tiptap writer for email and other authored content from the first delivery; the broader Library later exposes the same content foundation. Detailed layout and draft/version interactions remain under engineering/design review. This clarification is a contract, not a claim that these controls are implemented.

**Writing save behavior — D3:** the user selected autosaved working drafts with meaningful checkpoints. Typing should not require repeated Save actions. Display a restrained Saving/Saved/Unable to save state, keep retry and conflict recovery near the text, and restore unfinished work after navigation or refresh. History exposes meaningful checkpoints and exact reviewed/exported/sent content rather than every autosave. Review and Send remain separate deliberate actions. Announce meaningful save-state changes without a screen-reader announcement on every keystroke.

**LinkedIn scope — D4:** relationship and profile views use mapped contacts and professional-profile fields, with source/conflict information where relevant. Do not add a historical LinkedIn conversation browser or imply that message bodies were imported. Keep excluded-file accounting in import details rather than presenting an empty conversation archive.

**Immediate scope — D5 and follow-up:** connections means connected external apps. Build a full-page Connected apps destination from the supplied app-card references, with clear app/account identity, truthful connection status and usable connection actions. Preserve the existing verified-account and outreach-selection behavior. Do not copy permission toggles without an enforced backend contract. Routine lists, setup forms and schedule/activity mockups remain later references; they are not prerequisites. Use the supplied mockups directly; optional generated concept exploration is deferred in favor of getting this slice running.

Confirmed direction: one lead with visible specialists using Deep Agents on LangGraph; a reviewed Command Center profile backed by selected documents; background research/drafting on an always-on backend; local Chrome application assistance; isolated research scripts; and reviewed external changes through Composio. AR-18 selects work-first dashboard priority, AR-19 selects ongoing conversations per task/opportunity, AR-20 requires review of proposed reusable memories, and AR-24 selects steering active work at safe points. These decisions extend the implemented independent-run UI described above; detailed layout and recovery interaction remain to be reviewed.

- **Profile and sources:** show extracted assertions beside source references, then promote reviewed facts to the reusable profile. Later contradictory mail/pages cannot silently replace them. Missing application facts appear together beside the current form; show what was filled and what still needs the user.
- **Visible delegation:** show the lead's assignment, specialist name, status, concise activity, saved artifacts and actionable questions. Reopening the portal reconstructs activity from persisted events. Show tool/result evidence rather than private reasoning.
- **Work conversation:** keep the lead and visible specialist contributions in the selected task/opportunity's ongoing conversation. Addressing a specialist changes who handles the message without losing the work context. Unrelated work opens another conversation; show its scope clearly so the user does not unknowingly steer the wrong task.
- **Steering active work:** save a new instruction immediately and show when the running work has incorporated it. Until the next safe stopping point, distinguish Received from Applied. Preserve completed actions in the timeline; show revised outputs for fresh approval and do not imply that a message has recalled an already sent request.
- **Proposed memories:** save ordinary work history automatically. Show suggested reusable notes with their wording, scope and source work, with Edit, Approve and Reject. Unapproved suggestions do not appear as established preferences. Memory review is a separate, batchable queue and does not prevent an otherwise completed task from finishing; personal facts remain in the reviewed profile.
- **Review external changes:** email shows exact sender account, recipients, subject/body and attachments. Calendar/Linear/Notion proposals show the target and intended change. Editing invalidates approval of the prior version. Successful execution shows a provider receipt/link; ambiguous outcomes are labelled and cannot be blindly retried.
- **Browser continuation:** keep the signed-in tab as the work surface. User reviews/clicks Next and requests the next page. A closed tab cannot be filled by the always-on server; saved progress can remain available while a fresh page must be captured on return.
- **Existing answers:** preserve populated fields and distinguish Already filled from Filled by agent. If the user edits while generation runs, keep that edit and report the skipped fill. Offer a replacement only through an explicit revise action; accepting it targets the selected answer rather than replacing the entire page.
- **Resume choice:** preselect the user's general portfolio resume, displaying the exact document/version before upload. Allow an explicit switch to a specialized variant. Tailoring or later file edits do not silently replace the selected default or a prepared upload.
- **Research results:** show an editable, source-cited Command Center document and relevant generated files. Offer PDF export of the selected version and optional reviewed Notion publication. Script execution can proceed automatically in its task workspace. Preserve source/version context during editing and label which version was exported or published; research remains available if either operation fails.
- **Waiting and recovery:** questions and approval requests remain visible after refresh/restart. Cancelling stops future work and reports any operation whose external result is still unknown. Memory suggestions and artifact review must not look like permission to send or update an external record.

The [technical draft](../tech/tech-spec.md#first-agent-release-architecture-draft) owns state and boundary proposals. The historical design review below does not approve this new agent experience.

In isolated companion `0.4.5`, recognized equal posting IDs continue the saved application across pages; a recognized different posting starts another application with visible feedback. Unknown identity keeps the existing explicit choice. Reader status identifies Direct browser or AgentBrowser accurately. Applications exposes the canonical posting link and labels a `same_job` history entry as matching the same posting across pages. Page titles alone do not imply identity, filling still does not imply submission, and the current smoke-test build is unchanged.

### Dashboard and work inspector proposal

**Status: information priority and continuity confirmed in AR-18–AR-20; the bounded daily Overview is implemented on isolated `daily-workspace` and is not yet in the stable smoke-test build. Richer specialist/lineage displays below remain proposed.** The dashboard prioritizes work needing attention, work in progress and completed outputs, with agent activity and an ongoing conversation within the task/opportunity. Agents propose reusable memories for review. A live agent view can be a secondary entry point. Preserve the already approved same-page record context and restrained shadcn/AI Elements composition. These choices do not approve every detail of the synthetic preview.

The implemented composition uses shadcn task-view tabs and explicit rows, independently paginated attention/running/recent-output sections, and a secondary activity/pipeline summary. Each section has loading, empty and retry states. Today includes overdue work in the profile timezone; Snoozed explicitly means paused until resumed. Start/Resume/Complete/Reopen/Snooze/Cancel update task state, while Open conversation opens the existing ongoing work. Action reviews reuse the exact review dialog; saved artifacts open their pinned version; standalone runs open real activity; browser rows expose saved state and a link to Browser without inferring connectivity. Only confirmed succeeded action records appear as successful external outputs. No progress percentage, draft generation or agent launch is inferred from a task title. The composition remains keyboard reachable and uses semantic status text; no browser visual or accessibility QA was run under the user’s no-browser instruction.

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

“Store everything” means the meaningful work trail can be reopened: requests, visible responses, chosen context/source versions, generated outputs/scripts, handoffs, questions, approvals, errors and external receipts. Exact storage and retention boundaries are in [Tech Spec](../tech/tech-spec.md#system-of-record-and-dashboard-projections). The UI must distinguish saved local work from a current remote observation, an approved proposal from an executed change, and application filling from actual submission.

Refresh/reconnect must restore the same selected task and real state. Loading, empty, partial, stale, failed and outcome-unknown views remain distinct. Counts and rows agree; a new draft does not inherit an old approval; a user answer removes only its own outstanding question. Private data disappears on account changes. On narrow screens, switch between list and inspector with Back rather than compressing several permanent columns.

A synthetic interactive design preview accompanies this proposal; it is not the implemented dashboard or evidence that its runtime integrations work. The approved light/dark/system theme and contextual body interactions remain the visual foundation; sidebar destinations open full pages.

## Historical design review — consolidation and implementation

Historical scope: the then-active Product/Tech specs and supporting design document, before Design became a separate canonical spec and sidebar navigation was clarified. The earlier historical 8/10 score is superseded by this review. Scores assess the design contract and inspected synthetic composition; they do not clear the application for release.

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

- [x] D1/T10 — Implement full-page section navigation, compact Overview and contextual body-record inspection. Files: `context.tsx`, shell, records, detail, overview. Verify nested inspection, Back, missing records, mobile focus and retained list/tab state.
- [x] D2/T11 — Implement Light/Dark/System and four accent palettes using downloaded Kibo/shadcn components. Files: Appearance/provider, layout/CSS, Kibo switcher, Popover. Verify reload, device-theme changes, keyboard controls and 4.5:1 primary/body/muted text contrast in every palette/mode.

Prior hardening status and remaining acceptance tests are owned by [Engineering](../tech/engineering.md#implementation-tasks), not duplicated here.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
| --- | --- | --- | --- | --- | --- |
| Design | `/plan-design-review` + direct UI requirements | Consolidation, hierarchy and states | 1 current + historical review | CLEAN DESIGN PLAN | 4/10 → 8/10; two user directions resolved; real-component fixture inspected |
| Engineering | `/plan-eng-review` | Contracts, implementation and tests | 1 current + historical review | ISSUES OPEN | UI slice implemented; broader hardening remains pending/partial |
| Outside | Configured plan-review provider | Independent challenge | 0 completed this run | DISABLED | No outside coverage or native substitute |

**VERDICT:** Approved UI direction implemented locally. Design review completion does not clear the remaining engineering release gaps.

**NO UNRESOLVED DECISIONS** for this UI slice. Product Spec Q5–Q10 remain explicit future-policy decisions.


Contact discovery lives in a contextual dialog from Contacts and Company details, with provider configuration in Connected apps. Search, Apollo reveal, Add contact and Fill missing details are separate actions. Show observed date, provider-reported email status, source links, empty results and retry outcomes. Saved discoveries reopen without provider I/O. Keep existing contact values visible and unchanged unless the user explicitly applies available facts to blank fields. A discovery action must never send outreach.

CRM agent work stays beside its source record: Enrich company on a row opens the company inspector; generated follow-ups appear in the person’s saved-draft workflow. Show queued, working, waiting, failed and saved states honestly; link to the canonical task conversation and exact research versions. Older useful research survives failed refreshes. Manual company notes remain separate from sourced agent claims.

Streaming replies belong in the conversation timeline. Keep scrolling pinned only while the reader is at the bottom, expose an accessible Scroll to latest message button, and preserve typed instructions while output arrives. Use short word fades without a long artificial typing delay; respect reduced motion for both text and scrolling. External source previews must trap focus as dialogs and return it to the originating link.

### Contacts: researched LinkedIn connection notes — 2026-09-22

Extend the existing Contacts table with a LinkedIn outreach column. Empty rows offer Draft connection note; active rows show queue/progress or an input request with Open work. Ready rows display the entire short note, Copy note, Edit, LinkedIn and an N/200 counter. Identity uncertainty and unconfirmed employment remain visible beneath researched notes. Sources opens a contextual dialog with the research summary, caveats, exact quotations and captured-source links. The connection-note editor uses a plain textarea and live character count; oversized drafts stay editable but cannot be saved. The existing working-copy recovery and immutable save flow remain intact. A collapsible page brief lets the user tailor the purpose and voice for subsequent requests. Keep sending manual and preserve the table position during editing.

**Speed and depth clarification — confirmed 2026-09-23:** quick notes use saved context, with at most one targeted search and one public-page capture when a necessary detail is missing. Optional background must not trigger elaborate enrichment. Enrich contact is a separate deliberate action. Batch enrich opens a selection dialog for up to ten contacts on the current page, shows each queue result and lets failed requests retry without repeating successful ones. Changing the search or page starts a fresh selection. The batch uses the shared outreach brief and queues independently tracked research tasks. Company research remains detailed and sourced.


Agents conversations retain the full user/assistant transcript across turns. The
sidebar shows one entry per conversation, and New chat explicitly starts another.
Enter sends; Shift+Enter adds a line; IME composition does not submit. The Contacts
outreach controls stack below the contact name on narrow screens so the full note
and copy action remain visible.

## Generic Home conversations — 2026-09-23

Home starts with the Command Center supervisor and a general-purpose composer; lead intake is an example rather than the identity of the chat. Session selection is URL-addressable. Searchable paginated conversation history stays separate from recent run activity, and selecting an existing conversation preserves its configured profile. Stream token/tool activity, show saved questions in place and distinguish waiting from cancellation. Load transcript deltas, defer older run detail and stop rapid polling when idle.

Show cached-answer provenance and an explicit fresh-answer option. Settings → Local AI clients creates named, revocable credentials and shows each token once, with copy/hide controls and setup instructions. Keep token values out of query caches, URLs and browser persistence. Lead-intake results link to the saved records and exact source version; private pasted-source identifiers are not external web links.


### Home chat layout — confirmed 2026-09-23

Navigation and conversation history collapse independently with visible controls; desktop choices persist across reloads. On mobile, history opens in a dismissible drawer and restores focus to its trigger. Home chat fills the available dynamic viewport: a compact toolbar, one message scroll region, and a bounded composer. Long pasted drafts scroll within the textarea, and long saved messages remain reachable without page or nested transcript scrolling. Changing panel visibility preserves the selected conversation and unsent text.
