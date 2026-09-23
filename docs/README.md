# Command Center

**Revision:** 2026-09-22-r24. **Status:** connected workspace and operator import implemented; full-page navigation, contextual inspection, appearance and workspace state/retry/loading remedies implemented locally. Deep Agents conversations, job-lead discovery/evidence/drafts, local document ingestion and reviewed candidate facts are implemented locally. Deep Agents supports OpenAI, Gemini, Mistral and Cohere per profile. Grounded application preparation, exact resume uploads, reviewed scoped memory and durable token/tool streaming are implemented locally with synthetic coverage. Scoped Calendar/Linear/Notion context, reviewed external actions, isolated scripts/PDF exports, spending controls and job cleanup recovery are implemented locally with synthetic tests. The user has deferred hands-on ATS/provider QA to their own testing. Paid-model evaluation and an always-on deployment remain release work.

A personal workspace for knowledge work and automation, including correspondence, relationships, reading, writing, research and follow-through. The active [personal work OS revamp](product/product-spec.md#personal-work-os-revamp--confirmed-2026-09-22) includes connected apps, LinkedIn mapping, shared writing, Library, contact discovery and enrichment. Application automation is the latest priority; general routines remain deferred. Product and technical decisions have one canonical home each.

## Document ownership

There are three canonical specifications: Product, Tech and Design. Product direction and Engineering elaborate strategy and delivery evidence without maintaining competing requirements.

| Document | Owns |
| --- | --- |
| [Product Spec](product/product-spec.md) | Product behavior, release acceptance, implemented boundary and open Q5–Q10 decisions |
| [Tech Spec](tech/tech-spec.md) | Selected architecture, data/state/API contracts and labelled future extensions |
| [Design Spec](design/design-spec.md) | Interface hierarchy, interaction states, tokens, accessibility and approved visual direction |
| [Product direction](product/product.md) | Strategy, confirmed decisions and scope rationale |
| [Engineering](tech/engineering.md) | Accepted tasks and status, dependencies, test plan and delivery evidence |
| [Root README](../README.md) | Setup, local commands, operator import and deployment instructions |

Model/schema/API source and migrations establish what is implemented. A spec or review score describes a contract; it does not prove implementation or release readiness. Preserve confirmed direction when correcting stale status. Keep historical evidence dated and distinguish it from checks run in the current session.

The current `frontend-redesign` release includes saved job descriptions, recoverable tailored résumé/cover-letter requests, contextual Tiptap editing and PDF export; deterministic keyword coverage pinned to saved sources; approved employment/education autofill and bounded Add-row expansion; current-job recognition across supported application pages; and the daily Overview attention/running/output queues and task controls. Companion `0.4.5` retains manual Next and Submit. See [Engineering](tech/engineering.md) for the recorded validation checkpoints. These features are integrated through `ed69ac1`. Historical-application matching, broader authenticated ATS coverage, accurate email reply targeting and live provider/model quality remain unfinished. General routines remain deferred. Hands-on platform/provider QA is user-led; paid evaluation remains disabled until a reviewed plan and allowance exist.

The subsequent local usability cleanup makes Home the agent workspace, consolidates career views under Opportunities, separates Library writing/reviews from the uploaded Document Vault, and opens artifacts in a wide reading canvas. Agents groups current profiles, connectors, skills, workflow entry points and memory. Companion `0.4.6` defaults to reading the active Chrome tab. This work is local, with validation recorded in [Engineering](tech/engineering.md#calm-workbench-usability-cleanup--2026-09-22); it is not a deployment claim.

For hands-on release testing, use the [smoke-test checklist](smoke-test.md). It covers core workflows, optional live integrations and known limits.

## Operational leads

[Leads Real Data](https://app.notion.com/p/3e22e26208a58027b5f4d84258dd8c6f)

[Command Center — Contacts & Relationship Registry](https://app.notion.com/p/3e22e26208a58182be40d036fd9561cf)

These operational pages are unchanged by consolidation. Live personal content is not copied into committed documentation. Product Spec defines future staged ingestion.

## Agent reading order and decision status

1. Read [Product Spec](product/product-spec.md) for confirmed outcomes, release boundaries and unresolved questions.
2. Read [Tech Spec](tech/tech-spec.md) for implemented contracts, proposed architecture and the pytest/pytest-mock/DeepEval decision.
3. Read [Design Spec](design/design-spec.md) for full-page navigation, contextual body interactions, responsive/accessibility rules and design acceptance.
4. Use [Engineering](tech/engineering.md) for delivery tasks and actual validation evidence; inspect code before treating a design as implemented.

Latest explicit user decisions supersede historical previews and review scores. Framework selection is a decision, not evidence of installation; proposed screens are not shipped behavior. Keep decisions in their owning spec and link to them. Before new agent implementation, resolve the open questions affecting that slice, record acceptance/tests/evals, and complete the engineering review. This documentation pass does not silently decide budgets, judge models, sandbox hosting or later campaign authority.

## Planning state

**Current checkpoint:** Deep Agents conversations, reviewed browser preparation, scoped memory, streamed tool/token activity, reviewed connected actions, isolated research/PDF jobs and spending controls are implemented locally. The eight product-interview rounds are answered (AR-1–AR-26); numerical budgets and live-provider validation remain explicit setup/release work. Historical architecture drafts below describe direction; current contracts and evidence are in source, migrations and Engineering.

| Part of the design | Current direction | Where to review it |
| --- | --- | --- |
| Work and interface | Work-first dashboard; ongoing task/opportunity conversations; visible lead and specialists | [Product boundary](product/product-spec.md#first-agent-release--confirmed-interview-direction), [dashboard proposal](design/design-spec.md#dashboard-and-work-inspector-proposal) |
| Agent execution | Deep Agents on LangGraph; Celery background execution; local Chrome form filling | [Architecture and boundaries](tech/tech-spec.md#first-agent-release-architecture-draft) |
| Durable records | PostgreSQL for work, decisions and audit; shared immutable artifacts for sources and outputs | [Data model](tech/tech-spec.md#data-model-and-ownership), [system of record](tech/tech-spec.md#system-of-record-and-dashboard-projections) |
| External work | Composio for Gmail, Calendar, Linear and Notion; exact changes reviewed in Command Center | [Tool and integration contracts](tech/tech-spec.md#mcp-composio-and-tool-discovery) |
| Context and cost | Scoped skills/tools, reviewed memories, bounded handoffs and configurable spending caps | [Agent context](tech/tech-spec.md#agents-skills-memory-and-handoff), [token usage](tech/tech-spec.md#efficient-token-usage-and-measurable-limits) |
| Delivery | One always-on Docker server; workflow-by-workflow verification; costs set after benchmark-plan review | [Verification and proposed sequence](tech/engineering.md#agent-release-verification-draft), [benchmark draft](tech/engineering.md#agent-benchmark-plan-draft) |

The user opened a documentation-first agent architecture interview on 2026-09-21 and selected Deep Agents on LangGraph: one lead with visible specialists, Copilot-style extension filling with user Next/Submit, outreach approved and sent from Command Center, and isolated scripts producing research documents. The backend targets always-on operation. Composio is central for Gmail, Google Calendar, Linear and Notion, with reviewed external changes; Slack comes next. The [first-release boundary](product/product-spec.md#first-agent-release--confirmed-interview-direction) precedes later unattended applications. [Product Spec](product/product-spec.md#agent-architecture-interview--opened-2026-09-21) owns the interview. The [technical architecture draft](tech/tech-spec.md#first-agent-release-architecture-draft) covers data ownership, service/module boundaries, async/Celery, agents/skills/memory/handoff, MCP discovery and token efficiency; [Engineering](tech/engineering.md#agent-release-verification-draft) maps verification, and [Design](design/design-spec.md#new-agent-experience--interview-draft) records interaction contracts and the Simplify reference. The runtime/conversation slice has completed engineering review and local verification. Broader workflow contracts remain planned; implementation is authorized without another planning interview.

First application targets are Greenhouse, Lever, Ashby, Workday and iCIMS; required support is distinct from verified coverage. Gmail searches relevant messages on request in one selected account. The user's dashboard/system-of-record request is developed in the [dashboard proposal](design/design-spec.md#dashboard-and-work-inspector-proposal) and [record/projection contract](tech/tech-spec.md#system-of-record-and-dashboard-projections). The user selected work-first dashboard priority, ongoing conversations per task/opportunity, reviewed reusable memories, preservation of existing form values and the general portfolio resume as the default upload. Spending amounts follow review of the [benchmark plan](tech/engineering.md#agent-benchmark-plan-draft). New instructions steer active work at safe points; the first deployment keeps the existing Docker stack on one always-on server; research produces editable cited documents with PDF export and optional reviewed Notion publication. Detailed scope, execution/recovery, deployment and delivery contracts remain under engineering review.

The connected workspace and operator-run CSV/cached-Notion import exist. The full autonomous application loop remains a later product objective. Nine accepted engineering fixes and the UI delivery status are tracked in [Engineering](tech/engineering.md#accepted-workspace-hardening). The user clarified that sidebar destinations open full pages, while suitable body actions preserve context in dialogs or side panels; they also requested selectable appearance; implementation and reference findings are recorded in [Design](design/design-spec.md). The interview partially answers Q7–Q9 for the first release; remaining campaign choices stay explicit in Product Spec.

## Source history

[Source History](https://app.notion.com/p/3e22e26208a581c9b075e0617a050b6d)

The former Planning Doc, duplicate requirements, standalone lead/agent notes and interview/comment worksheets have been absorbed into the canonical specs. Their historical copies remain reference material, outside active navigation. Local pre-consolidation copies are gitignored under `.local/history/` and `.local/source/`.

## Local mirror

The repository mirrors this hierarchy under `docs/`. Notion publishing metadata stays local and untracked. Current revisions are local and have not been published to Notion. Future publishing must fetch first and preserve concurrent changes. Root `AGENTS.md` contains coding-assistant instructions. Private review artifacts under `~/.gstack/projects/command-center/` are supporting evidence, not additional active specifications.
