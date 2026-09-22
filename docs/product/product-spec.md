# Command Center — Product Spec

**Revision:** 2026-09-21-r13. **Status:** product contract; implemented scope is distinguished below from the full workflow release. Core agent, document-review and model-provider slices are implemented locally; remaining workflows are tracked below.

This is the single source for product behavior and acceptance. [product.md](product.md) owns product direction and scope rationale. [Tech Spec](../tech/tech-spec.md) owns architecture and execution contracts. The former Planning Doc, duplicated requirements, lead-planning notes, and interview material are absorbed here or in Tech Spec; superseded copies are historical only.

## 1. Outcome and user

Command Center is a personal workspace for Ashwin to run job search, outreach, relationships, research, application materials, and eventually automatic applications. The next agent release targets an always-on backend with local development and browser interaction in the user's Chrome session. The broader automation goal includes discovering roles, judging fit and legitimacy, finding useful connections, navigating employer portals, tailoring answers, uploading a resume, submitting and recording the outcome; the assisted first-release boundary below precedes unattended submission.

A prepared draft alone does not satisfy the broader autonomous application outcome. The user has now selected a preceding agent release with Copilot-style filling and user submission, reviewed outreach sent from Command Center, and code-assisted research documents. The full unattended job-to-application loop remains a later objective. The connected workspace is an implemented foundation toward those outcomes. The longer-term extension is people/company relationship management and finding connections for the user's AI SaaS sales; it is not a requirement to build a sales product now.

## 2. Confirmed scope and release boundary

### Current implementation

The personal workspace includes CRM records, profile, tasks, artifacts and immutable versions/reviews, bounded research/drafting agents, memory, provider setup and a paired browser companion for reviewed manual form filling. Task/opportunity conversations support lead discovery, source evidence and private outreach drafts. Local document ingestion preserves originals, creates linked Docling extractions and proposes candidate facts for human review; the selected default resume pins an exact original version. Deep Agents supports OpenAI, Gemini, Mistral and Cohere independently per lead or specialist. An operator-run importer handles supported LinkedIn CSVs and cached Notion lead pages. It does not provide a portal staging/review flow or live Notion synchronization. See [Tech Spec](../tech/tech-spec.md) for contracts and [engineering.md](../tech/engineering.md) for accepted fixes and verification status.

### Navigation and contextual work — confirmed clarification

Sidebar navigation opens the selected section as a full page in the workspace. Overview is one destination, not a permanent background or a required return point. This applies equally to Contacts, Companies, Opportunities, Roles, Tasks, Artifacts and the other top-level sections; ordinary clicks must not substitute an inspector for route navigation.

Within any page body, prefer a modal, drawer or contextual side panel for record details, related records, previews, editing and review actions when the task fits. Preserve the originating page's selection, filters and working context; Close/Back returns to that context. Existing list/detail panes satisfy this intent for selected records. Use a full page for a genuinely separate destination or a workflow that needs the main workspace, and keep external links and explicit open-in-new-tab behavior intact. See [Design Spec](../design/design-spec.md#navigation-and-context-contract) for the interaction contract.

### Testing and evaluation — confirmed tooling decision

The user chose **pytest** for test authoring/execution, **pytest-mock** for mocking, and **DeepEval** for agent/LLM evaluations. New planned test work follows these choices; existing TypeScript frontend checks remain current coverage until a deliberate migration preserves their behavior. DeepEval is selected but not installed or implemented yet.

Release acceptance requires deterministic correctness tests and separate agent-quality evaluations for assisted application answers, reviewed outreach and source-backed research. Mocked model/provider tests prove application behavior and failure handling; they do not establish real model quality. Eval cases must identify fixture/source revisions and assess factual grounding, unsupported claims, relevance and workflow completion. Authorization, owner isolation, preservation of user edits and duplicate-effect prevention are hard correctness gates, not scores that a favorable average can offset. Technical organization and open eval decisions live in [Tech Spec](../tech/tech-spec.md#testing-mocking-and-agent-evaluations).

### First agent release — confirmed interview direction

The user selected these first-release experiences during the agent architecture interview:

- One lead assistant coordinates visible specialists; a specialist can also be addressed directly.
- The dashboard prioritizes work needing attention, work in progress and completed outputs. Agent activity remains visible inside each task; this determines information priority, not approval of every preview layout detail.
- Conversations continue within a task or opportunity. The lead coordinates and specialists contribute in that shared work context; unrelated work starts a separate conversation.
- New instructions are saved immediately and steer active work at the next safe stopping point. Completed actions remain in history; changed drafts require fresh approval before execution.
- Task activity, sources and outputs are saved automatically. Agents propose reusable long-term memories for user review; personal facts continue to use the reviewed profile.
- Deep Agents on LangGraph is the selected harness for the new architecture. This is an architecture decision, not an implemented migration.
- Research and drafting target the existing Docker stack on one always-on server. The exact host, cost and recovery targets remain for operations review. Application filling stays in the user's open Chrome tab.
- A Chrome-extension application agent fills the current signed-in application page, generates editable responses and supports resume upload. The user reviews, clicks Next, requests filling on subsequent pages and performs final submission. Simplify Copilot is the interaction reference. Greenhouse, Lever, Ashby, Workday and iCIMS are required first-release targets; exact field/tenant coverage and its verification remain to be specified.
- Existing application values are preserved. Fill empty fields; offer replacements only when the user explicitly chooses to revise an answer.
- Use the user's selected general portfolio resume as the default upload. Specialized resume variants remain available through explicit selection; do not silently tailor or substitute another version.
- An outreach request searches relevant messages in one selected Gmail account, gathers person/company/task context, shows its email draft in Command Center and sends after the user approves there. Background inbox monitoring and searches across multiple accounts are outside this initial behavior.
- A research agent can write/run a script automatically in an isolated task workspace with selected materials and public research access, then save an editable, source-cited company-research or interview-prep document in Command Center. PDF export and optional reviewed Notion publication are required. Connected-app credentials stay outside scripts. Detailed input formats, document templates and sandbox provider remain to be specified.
- A user-reviewed Command Center profile backed by selected documents is authoritative for personal facts. Connected apps supply fresh task context. The application agent fills known fields and collects missing personal answers together in the extension; confirmed answers can be retained for appropriate reuse.
- Composio is the integration priority for Gmail, Google Calendar, Linear and Notion, with Slack next. Calendar supplies event/interview context and proposed event creation/updates; Linear supports reading/creating/updating tasks linked to Command Center work; Notion supplies selected pages and publication/updates of generated research documents. The user reviews external changes in Command Center before execution initially. Account scope and delivery sequencing remain open.

This first-release boundary supersedes the earlier expectation that the next agent delivery must already submit applications unattended. It preserves that broader goal for a later stage. The [agent interview](#agent-architecture-interview--opened-2026-09-21) records exact answers and pending choices; implementation begins after the architecture and supporting docs are agreed.

### Broader autonomous workflow direction

The following requirements describe the broader workflow target beyond the first agent release. They do not establish current implementation or override its confirmed user-submit boundary.

| Area | Confirmed direction | Boundary still open |
| --- | --- | --- |
| Inputs | Job title, job URL, or LinkedIn-export CSV | Exact CSV schemas and saved-search criteria |
| Existing leads | Seed from Notion Leads Real Data and Contacts & Relationship Registry | Reviewed mapping, deduplication and freshness |
| New discovery | Find additional roles/people with browser research, Hunter, Apollo, Firecrawl and free/public sources | Minimum provider and site coverage; available accounts/quotas |
| Qualification | Find promising, legitimate roles and useful relationship paths; filter suspicious listings | Hard filters, legitimacy threshold and connection priority |
| Materials | Resume/message/document authoring in the portal; tailored application answers | First output formats and candidate fact/answer policy |
| Execution | Local agents fill, upload and submit while the user is absent | Campaign authority, per-run limits, exceptions and supported portals |
| Outreach | Job-search outreach is current scope | Channels, sending authority, cooldowns and sequences |
| Foundations | General artifacts, documents/types, first-class tasks, evidence and human/AI audit | Future workflow extensions and retention policy; implemented schema/version contracts are in Tech Spec |
| Later | Broader relationship operations and AI SaaS prospecting | No sales workflow implementation in the first release |

The later unattended proof may support one target profile and limited portal coverage. Automatic applications remain part of the broader direction. Full LinkedIn ZIP coverage and broader synchronization can follow supported entry flows. The initial Composio integration set above governs current agent planning; inclusion of an app does not yet specify full mailbox/calendar synchronization.

The user selected Docling for local extraction, existing Docker Firecrawl/SearXNG for research, AgentBrowser for autonomous applications/outreach, and a local open-source companion inspired by Simplify for one-click applications and knowledge-backed form answers. Research adapters, local Docling document extraction and the manual-fill companion are implemented. Autonomous browser orchestration, browser resume uploads and submission remain future work; selecting these tools does not resolve Q5–Q10.

## 3. Product vocabulary

| Object | Meaning |
| --- | --- |
| Person | Reusable contact with identifiers, roles, employment observations, preferences and relationship evidence |
| Company | Employer, agency, client or other organization with dated research and identifiers |
| Job | Specific role with a source identity, description history and observed availability |
| Opportunity | The user's pursuit of a company/job, linked to relevant people and a next action |
| Application | Exact material/answer package, execution attempts, submission evidence and later hiring outcomes |
| Artifact | Captured or created work product such as a message, research result, document or package |
| Document / document type | A document facet of an artifact, classified by purpose such as resume, cover letter or company research; shares the artifact version lifecycle |
| Interaction | Communication/meeting event with participants, channel, time and source |
| Task | Actionable commitment with owner, due semantics, state, rationale and context |
| Lead | Discovery/pursuit term; whether it is a separate lifecycle or a view remains open |
| Audit event | Attributed history of a state change or decision, with redacted details |

Keep person identity separate from opportunity progress. Several people may support one application, and one person may remain useful across many jobs. A discovered email address, a LinkedIn connection, and a confirmed advocate are different relationship signals.

## 4. End-to-end workflows

### Start and seed

A title starts discovery using a saved target profile. A URL captures a specific role and its job description. A LinkedIn CSV supplies relationship/context data; do not assume it contains jobs. Existing Notion records enter a staging and review flow with page/row provenance. Manual entry remains available for missing records.

Preserve both operational sources in place: [Leads Real Data](https://app.notion.com/p/3e22e26208a58027b5f4d84258dd8c6f) and [Contacts & Relationship Registry](https://app.notion.com/p/3e22e26208a58182be40d036fd9561cf). Their historical notes are evidence, not proof of current employment, open roles, or live commitments. Real lead data stays outside committed specifications and fixtures.

### Discover and qualify

Agents explore the selected job sources, find relevant roles and people, and explain accepted, rejected, and uncertain results. Keep role fit, employer/listing legitimacy, identity confidence, source freshness, email deliverability, and relationship strength separate. A single opaque score must not hide a disqualifying condition.

Prefer official employer/job sources where available. Record suspicious indicators such as mismatched domains, unverifiable employer identity, payment requests or contradictory sources. Screening is an evidence-backed assessment, not a guarantee that no scam can pass. A failed fetch means unavailable/unknown, not automatically closed or fraudulent.

### Research the opportunity

| Dossier section | Required information | Quality rule |
| --- | --- | --- |
| Product | What is sold, customer, problem, differentiation, relevant technical signals | Official sources first; separate interpretation from facts |
| Company and story | Leadership, business model, milestones, recent news and hiring context | Claim-level source and collection time |
| Relevant roles | Title/team/location, source link, observed status and target-profile overlap | Show coverage and observation time; do not claim all current jobs were found |
| Job description | Full retained text, requirements, responsibilities and explicit compensation/compatibility statements | Version/hash/source; preserve the description actually used |
| Interview process | Reported stages, participants, timing and source | Distinguish recruiter-confirmed from reported/estimated |
| Interview questions | Question, role family/stage, source and anecdotal status | Reports are not company policy or guaranteed future questions |

Interview preparation should use the job/company dossier, interviewer context and verified experience to suggest stories, then support a post-interview follow-up. Outcome data does not rewrite candidate facts.

### Prepare materials and answers

From an opportunity, select actual candidate source material and write or generate resumes, messages, cover letters, research documents and application answers in the portal. Show relevant evidence, missing information, edits and versions. Preserve the exact material selected for each application.

Tailoring may rephrase supported experience and explain motivation/fit. It must not invent employment, achievements, metrics, eligibility, compensation preferences or demographic/legal declarations. In the first release, fill known fields and collect missing personal answers together; the user reviews the application and clicks Next/Submit. Exact contextual reuse rules and later unattended policy remain open. Approved reusable answers should retain context so the user is not asked the same resolved question repeatedly.

### Execute automatically

The requested AgentBrowser runner and local companion navigate the supported application flow, fill answers, upload the pinned resume and submit within the agreed authority. Simplify is a reference, not a required third-party orchestration interface. The active browser/account must be known. The implemented manual-fill companion is a foundation for this workflow, not completion of it.

Record submitted, failed-before-submission, paused, and outcome-unknown distinctly. A click is not proof of acceptance by a portal. Unknown outcomes must reconcile before retrying. A change to materials creates a new package rather than altering what an earlier attempt used. Authentication challenges, genuinely missing answers, scope drift and uncertain effects need specific recoverable exceptions.

### Outreach and follow-up

Discovering a person, drafting a message, sending it, and scheduling follow-ups are separate actions. Application authority does not silently authorize messaging. Do-not-contact excludes outreach; it is not a small score penalty. Show the reason and evidence for each reminder, preserve manual user priorities, and avoid duplicate reminders on replay/rescheduling.

## 5. Requirements and acceptance contract

| ID | Requirement | Acceptance evidence |
| --- | --- | --- |
| P-01 | Title/URL/CSV entry | Each mode produces the intended search, job or staged relationship context |
| P-02 | Notion lead seeding | Reviewed mappings retain source references and do not treat historical meetings as current tasks |
| P-03 | Canonical identities | Strong identifiers reconcile unambiguous records; name-only collisions and conflicts enter review |
| P-04 | Source-backed research | Dossier claims and job descriptions retain source/time/version and uncertainty |
| P-05 | Explained qualification | Fit, legitimacy and connection findings are separately inspectable; hard exclusions are enforceable |
| P-06 | General artifacts/documents | Resumes, messages and research share a coherent version/review lifecycle; no resume-only parallel store |
| P-07 | Tailored answers | Answers reference actual facts/material; missing factual content is surfaced and handled by agreed policy |
| P-08 | Automatic browser application | Controlled fixture completes fill/upload/submit and records confirmation without per-field supervision |
| P-09 | Duplicate and outcome handling | Replay/crash does not blindly create another submission; unknown effects enter reconciliation |
| P-10 | Tasks and follow-ups | Owner, due time/date, state, rationale and evidence are present; completion/reminder operations are idempotent |
| P-11 | Human/AI attribution | Consequential state changes and execution actions record the authenticated actor/delegator and material versions |
| P-12 | Local privacy and recovery | Access, secrets, source handling and backup/restore meet the Tech Spec contract |
| P-13 | Provider limits | Quota, failure, no-match and access-denied outcomes are distinguishable; no unapproved spend |
| P-14 | Portability | Selected record/material export is reviewable and excludes sensitive/internal data by default |
| P-15 | Usable portal | Editing, evidence inspection, campaign progress and exception recovery have designed states |

A complete synthetic acceptance scenario covers input → discovery/qualification → source evidence → candidate materials → answers → automatic application → confirmation/reconciliation → follow-up. A bounded real-site pilot follows validated account, candidate-data, site-support and campaign setup. Exact coverage and acceptable intervention count remain open; documentation alone is not a completed feature.

## 6. Success measures and boundaries

Measure discovery-to-confirmed-application time, user intervention count/duration, supported versus unsupported application coverage, duplicate/unknown outcomes, unsupported claims caught, due-task completion, and response/interview conversion using defined cohorts. Separate unknown outcomes from failures. Replace unverifiable claims such as “missed follow-ups prevented” with observable timing/completion counts.

Local-first means the core record store and workflow are local. Cloud models, Google, enrichment and external portals have separate data/spend boundaries. A disabled optional provider should leave supported manual/source alternatives usable. Do not claim complete job coverage, guaranteed scam detection, certain sponsorship from company history, or an absolutely immutable local audit log.

No hosted multi-tenant recruiting product, sales automation release, fabricated personal claims, name-only automatic person merging, credential harvesting, CAPTCHA bypass or site-access-control bypass is included. Outreach sending requires its own product decision.

## 7. Open product decisions — next interview round

The connected workspace and operator import are implemented within the accepted direction recorded in [product.md](product.md). Their maintenance proceeds independently of Q5–Q10. The new agent interview partially resolves Q7–Q9 for the first release; later campaign policy remains open.

| ID | Decision | Recommendation to discuss |
| --- | --- | --- |
| Q5 | Target titles, seniority, geography/remote, compensation and compatibility; hard exclusions | Named search profiles with must-haves separate from preferences |
| Q6 | How strong connections affect applying | Boost warm/referral paths; decide explicitly whether a relationship is mandatory |
| Q7 | Later campaign authority, volume and stopping limits | First release: user submits applications; external app changes require review. Bounded unattended authority remains a later decision |
| Q8 | Context-specific reuse and conflicts in personal answers | AR-9/AR-10 settle authoritative profile and missing-fact handling: fill known fields, ask together and retain confirmed answers for appropriate reuse. Exact reuse/conflict rules remain to specify |
| Q9 | Outreach initiation, account/context scope, follow-up and contact preferences | AR-6 settles first-release email sending after approval in Command Center; automatic sequences remain undecided |
| Q10 | Model, enrichment and research budgets | Use free quotas/cache first; separate model spend; no automatic purchase or top-up without policy |

Unresolved parts constrain the workflows they govern; recommendations are not accepted requirements. Continue the section-by-section interview here instead of maintaining a separate planning/interview specification. Later discovery/campaign choices do not block documenting the selected assisted first release.

### Agent architecture interview — opened 2026-09-21

The user explicitly requested a documentation-first architecture discussion grounded in this repository, followed by implementation after shared understanding. The brief calls for multiple agents working alongside Command Center and evaluation of Deep Agents, custom LangGraph and the Codex harness. The user subsequently clarified that Composio is the main integration priority: Gmail, Google Calendar, Linear and Notion are the initial named set, with Slack next. Slack is not a current design or delivery dependency. AR-11 settles the initial Calendar/Linear/Notion actions and review behavior; account scope and exact delivery sequencing remain open.

This reopens the agent-harness choice and refines the first delivery ahead of the broader autonomous job-to-application goal. The interview partially answers Q7–Q9 without deciding later campaign policy. The existing FastAPI/PostgreSQL workspace and implemented runtime remain the factual baseline. Supporting research is in [Tech Spec](../tech/tech-spec.md#agent-harness-evaluation--research-baseline).

Round 1 has answers. AR-1 and AR-3 are confirmed. AR-2 names two concrete workflows; AR-5/AR-6 subsequently settle their submission/sending boundaries. AR-4 defers Slack and prioritizes Composio. Pending recommendations are not accepted requirements.

| ID / interview question | Decision needed | Recommendation to discuss | Status |
| --- | --- | --- | --- |
| AR-1 / Q1 | One coordinating assistant, separately managed named agents, or mostly automatic workflows | One lead assistant delegates to visible specialists, with direct access when useful | Confirmed by user: one lead assistant coordinating visible specialists |
| AR-2 / Q2 | One exact delegated command, finished outcome and point where the system asks for help | Specify concrete outcomes and stopping conditions | Confirmed workflows: extension-activated application filling and context-aware email drafting; AR-5/AR-6 settle review and execution boundaries |
| AR-3 / Q3 | Whether general computer/code execution is core or Codex is primarily a candidate business-workflow harness | Evaluate the harness against the actual tool, file, browser and code work required | Confirmed by user: general computer/code execution and business workflows are equally important |
| AR-4 / Q4 | Slack's role and integration priority | Initial shared-conversation proposal superseded by user direction | Slack deferred; Composio is the main integration priority |

The user's two concrete use cases:

| Workflow | Confirmed experience | Details still to resolve |
| --- | --- | --- |
| Application filling | Activate from a Chrome extension in the authenticated browser; preserve existing values, use the reviewed profile to fill empty fields and generate editable responses; collect missing answers together; upload the selected general resume by default; user reviews, clicks Next and submits | Field/widget/upload coverage; resume import/version handling; source conflicts, answer reuse and failure recovery |
| Email outreach | On request, search relevant mail in one selected Gmail account, show the draft in Command Center, and send after approval there | Account configuration and exact context filters; recipient/intent selection; approval binding, threading, duplicates and follow-up |

The form workflow makes the extension an explicit agent entry point alongside the portal; Slack is deferred. AR-5 sets the first application's final-submit action with the user; unattended submission remains a later stage. AR-6 selects outreach approval and sending in Command Center. General computer/code execution is as important as business workflows, so the harness comparison must evaluate both.

Round 2 has responses. AR-5, AR-6 and AR-8 are confirmed; AR-7 names the apps and AR-11 subsequently specifies Calendar/Linear/Notion actions. Pending recommendations are not user decisions.

| ID / interview question | Decision needed | Recommendation to discuss | Status |
| --- | --- | --- | --- |
| AR-5 / R2.1 | First form-agent outcome and stopping point | Match Simplify Copilot's in-browser autofill, contextual answer generation and user review/submission | Confirmed after reference research: Copilot; fill/generate answers, user reviews and submits |
| AR-6 / R2.2 | Email draft destination and sending handoff | Initial mailbox-draft proposal superseded by the user's choice | Confirmed: show the draft in Command Center and send after the user approves there; broader outreach policy Q9 remains open |
| AR-7 / R2.3 | First Composio apps, actions and priority | Define action contracts for the named initial apps before enabling tools | Confirmed app set: Gmail, Google Calendar, Linear and Notion, with Slack next. AR-11 defines initial Calendar/Linear/Notion actions; accounts and ordering among the first four remain open |
| AR-8 / R2.4 | A concrete computer/code task with inputs and a finished result | Add that task as a harness acceptance scenario alongside application filling and outreach | Confirmed: write and run a research script to produce an interview-prep or company-research document; exact input/source contract remains open |

The [Simplify reference study](../design/design-spec.md#simplify-copilot-reference--agent-interview) records the observed public design and documented workflow. The user approved its Copilot interaction and submission boundary, not parity with every Simplify feature.

The third acceptance workflow is research-to-document generation with code execution when useful. AR-14 selects automatic script execution in an isolated task workspace, saving the resulting company-research/interview-prep document in Command Center and reviewing any Notion publication. Source/evidence rules already govern company research; exact input/output formats and sandbox implementation remain to be specified. This scenario gives the harness a concrete use for computer/code capabilities without assuming additional software-development workflows.

Round 3 is confirmed:

| ID / interview question | Decision needed | Recommendation to discuss | Status |
| --- | --- | --- | --- |
| AR-9 / R3.1 | Authoritative background when resume, Notion and previous correspondence disagree | Maintain a user-reviewed Command Center profile backed by selected documents; use connected apps for fresh task context | Confirmed: Command Center profile backed by selected documents |
| AR-10 / R3.2 | Handling an unknown personal/application fact | Fill known fields, collect missing answers together in the extension, and reuse confirmed answers in appropriate contexts | Confirmed: fill known fields and ask about missing answers together; resolves part of existing Q8 |
| AR-11 / R3.3 | Calendar, Linear and Notion actions and review behavior | Calendar event context and proposed event changes; linked Linear task read/create/update; selected Notion page reads and research publication/updates; review external changes initially | User accepted the proposed app actions and review behavior; Gmail's approve/send decision already stands |

Round 4 is confirmed:

| ID / interview question | Decision needed | Recommendation to discuss | Status |
| --- | --- | --- | --- |
| AR-12 / R4.1 | Whether research/drafting continues when the laptop is closed | Always-on backend target; local development remains possible and application filling stays in the open browser | Confirmed: always-on backend; application filling stays in the user's browser |
| AR-13 / R4.2 | Progression through multi-page applications | Fill the current page and support resume upload; user reviews/clicks Next, then requests filling on the next page; final Submit stays manual | Confirmed: fill each page; user reviews/clicks Next and Submit; site/field coverage remains separate |
| AR-14 / R4.3 | Authority and environment for generated research scripts | Automatic execution inside an isolated task workspace using selected materials/public research; keep connected-app credentials outside scripts and review publication | Confirmed: automatic execution in an isolated task workspace |

Round 5 is confirmed:

| ID / interview question | Decision needed | Recommendation to discuss | Status |
| --- | --- | --- | --- |
| AR-15 / R5.1 | Harness to develop the architecture around | Deep Agents on LangGraph for built-in delegation/context and Python integration, with sandbox execution for scripts | Confirmed: Deep Agents on LangGraph |
| AR-16 / R5.2 | Required first-version application sites | Define explicit platform targets and test their supported form controls/uploads | Confirmed: all popular platforms, explicitly Greenhouse, Lever, Ashby, Workday and iCIMS; all five are required first-release targets, not verified current support |
| AR-17 / R5.3 | Gmail context-gathering trigger and account scope | Relevant mail searches per outreach request in one selected account; background monitoring/multiple-account search separate | Confirmed: search relevant mail when the user requests outreach, in one account |

AR-16 establishes these five named platforms as the concrete initial coverage set. Do not silently defer Workday or iCIMS. Additional platforms can extend the matrix; “all popular” is not a claim that every employer customization or arbitrary form is already supported. Each platform needs explicit tested field/upload/page coverage and an actionable unsupported-field result.

The user also explicitly requested documentation of the data model, service boundaries, async/Celery execution, agents, skills, memory/handoff, MCP discovery and token efficiency. The [technical architecture draft](../tech/tech-spec.md#first-agent-release-architecture-draft) covers these topics before implementation; detailed proposals still require engineering review.

The user additionally requested a dashboard that makes this work visible and stores it in the system of record. Confirmed requirement: durable visibility of work, agent activity, context, artifacts, decisions and outcomes in Command Center. Proposed presentation and record contracts are in [Design](../design/design-spec.md#dashboard-and-work-inspector-proposal) and [Tech Spec](../tech/tech-spec.md#system-of-record-and-dashboard-projections). The request does not by itself choose a dashboard layout, unlimited raw-data retention or background synchronization of every connected app.

Round 6 is confirmed:

| ID / interview question | Decision needed | Recommendation to discuss | Status |
| --- | --- | --- | --- |
| AR-18 / R6.1 | Dashboard's primary view | Work needing attention, in-progress work and completed outputs; agent activity inside each task | Confirmed: work and outcomes first, with agents visible within each task |
| AR-19 / R6.2 | Conversation continuity | An ongoing conversation scoped to a task/opportunity, with lead and specialist contributions | Confirmed: ongoing conversations scoped to a task or opportunity |
| AR-20 / R6.3 | Authority to add long-term memory | Automatically retain task activity/sources/outputs; propose reusable memories for review initially | Confirmed: propose long-term memories for user review; task history is retained automatically and profile facts remain separate |

Round 7 is confirmed; numeric spending amounts will follow review of a benchmark plan:

| ID / interview question | Decision needed | Recommendation to discuss | Status |
| --- | --- | --- | --- |
| AR-21 / R7.1 | Treatment of existing application values | Preserve existing values; fill empty fields and offer replacements only through explicit revision | Confirmed: preserve existing values and offer replacements explicitly |
| AR-22 / R7.2 | Resume choice for uploads | Use a selected existing resume version with a saved default; tailoring is a separate requested task | Confirmed after locating four candidates: the general portfolio resume is the default; specialized variants are available for explicit selection. Exact source metadata stays private; no source contents copied into docs |
| AR-23 / R7.3 | Monthly/per-task model, research and sandbox spending limits | Configurable hard caps, retained partial results and no automatic purchases/top-ups; choose amounts after reviewing a benchmark plan | Confirmed: set amounts after reviewing the benchmark plan. Dollar values remain unset; no paid benchmark allowance is implied |

Resume source selection authorizes using the chosen existing document; it is not proof that extracted profile facts have been reviewed. Keep the private path/selection metadata outside committed docs and import the selected file into the shared immutable artifact lifecycle when that slice is implemented. The initial source directory is not a reason to give the always-on agent general access to the local portfolio project.

Round 8 is confirmed:

| ID / interview question | Decision needed | Recommendation to discuss | Status |
| --- | --- | --- | --- |
| AR-24 / R8.1 | A new user instruction during active work | Save it immediately and steer the current work at the next safe boundary; preserve completed effects and re-review changed drafts | Confirmed: steer current work at the next safe point |
| AR-25 / R8.2 | First always-on deployment model | Existing Docker stack on one controlled server; choose host/cost during operations review | Confirmed: existing Docker stack on one always-on server |
| AR-26 / R8.3 | Research-document output and editing destination | Editable source-cited Command Center document with PDF export and optional reviewed Notion publication | Confirmed: editable Command Center document, PDF export and optional Notion publication |
| AR-27 / provider follow-up | Model-provider choice for Deep Agents | Select provider and model independently for lead/specialist profiles, with server-only credentials | Confirmed: support OpenAI, Gemini, Mistral and Cohere, including `COHERE_API_KEY`; implemented with explicit per-profile selection and readiness checks |

Later dependent topics include account selection, browser field/page support, how agents ask and resume, task workspaces, budget/limits and recovery. Resolve these from the selected workflows and sources instead of prescribing them before the answers above.

The decision tree makes later questions depend on these answers rather than assuming a team structure or workflow:

```text
Confirmed: lead assistant + visible specialists + Command Center; docs first
  |
  +-- AR-1 Settled -> delegation, specialist identity, visibility details
  +-- AR-2/AR-8 Three workflows -> assisted forms, reviewed email, research docs
  |                            -> AR-5/6/9/10 settled: execution and fact handling
  |                            -> site/account scope, artifacts, exceptions, budgets
  +-- AR-3 Both equally important -> execution environment and harness criteria
  +-- AR-4 Composio first -> connected apps, accounts, actions and continuity
  |                      -> Slack explicitly deferred
                               |
                               v
         shared state + recovery + integration boundaries + harness decision
                               |
                               v
         architecture / code quality / tests and evals / performance review
                               |
                               v
         approved docs + build sequence -> implementation
```

Product Spec owns the interview and accepted behavior; Tech Spec owns architecture decisions; Engineering owns delivery tasks, test/eval plans and evidence; Design Spec owns portal/extension interactions, with Slack deferred. Keep unresolved choices visible in these documents and preserve the three canonical Product, Tech and Design specs.

## Supporting document

[product.md](product.md)
