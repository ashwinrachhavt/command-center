# Command Center

**Revision:** 2026-09-21-r9. **Status:** connected workspace and operator import implemented; same-page UI and appearance implemented locally; broader workspace hardening partial/pending. Deep Agents selected; detailed agent architecture/interview and review in progress.

A local workspace for autonomous job discovery, relationships, research, tailored applications and follow-ups. Product and technical decisions have one canonical home each.

## Document ownership

There are exactly two active specifications. Supporting documents elaborate their own concern and link back instead of maintaining another requirement list.

| Document | Owns |
| --- | --- |
| [Product Spec](product-spec.md) | Product behavior, release acceptance, implemented boundary and open Q5–Q10 decisions |
| [Tech Spec](tech-spec.md) | Selected architecture, data/state/API contracts and labelled future extensions |
| [Product direction](product/product.md) | Strategy, confirmed decisions and scope rationale |
| [Engineering](tech/engineering.md) | Accepted tasks and status, dependencies, test plan and delivery evidence |
| [Design](tech/design.md) | Interface hierarchy, interaction states, tokens, accessibility and approved visual direction |
| [Handoff](HANDOFF.md) | Latest objective, changed files, validation, unresolved work and next step |
| [Root README](../README.md) | Setup, local commands, operator import and deployment instructions |

Model/schema/API source and migrations establish what is implemented. A spec or review score describes a contract; it does not prove implementation or release readiness. Preserve confirmed direction when correcting stale status. Keep historical evidence dated and distinguish it from checks run in the current session.

## Operational leads

[Leads Real Data](https://app.notion.com/p/3e22e26208a58027b5f4d84258dd8c6f)

[Command Center — Contacts & Relationship Registry](https://app.notion.com/p/3e22e26208a58182be40d036fd9561cf)

These operational pages are unchanged by consolidation. Live personal content is not copied into committed documentation. Product Spec defines future staged ingestion.

## Planning state

**Current checkpoint:** the eight product-interview rounds are answered (AR-1–AR-26). The architecture is drafted; formal engineering review and the implementation plan are still ahead. No new agent implementation has begun in this planning work.

| Part of the design | Current direction | Where to review it |
| --- | --- | --- |
| Work and interface | Work-first dashboard; ongoing task/opportunity conversations; visible lead and specialists | [Product boundary](product-spec.md#first-agent-release--confirmed-interview-direction), [dashboard proposal](tech/design.md#dashboard-and-work-inspector-proposal) |
| Agent execution | Deep Agents on LangGraph; Celery background execution; local Chrome form filling | [Architecture and boundaries](tech-spec.md#first-agent-release-architecture-draft) |
| Durable records | PostgreSQL for work, decisions and audit; shared immutable artifacts for sources and outputs | [Data model](tech-spec.md#data-model-and-ownership), [system of record](tech-spec.md#system-of-record-and-dashboard-projections) |
| External work | Composio for Gmail, Calendar, Linear and Notion; exact changes reviewed in Command Center | [Tool and integration contracts](tech-spec.md#mcp-composio-and-tool-discovery) |
| Context and cost | Scoped skills/tools, reviewed memories, bounded handoffs and configurable spending caps | [Agent context](tech-spec.md#agents-skills-memory-and-handoff), [token usage](tech-spec.md#efficient-token-usage-and-measurable-limits) |
| Delivery | One always-on Docker server; workflow-by-workflow verification; costs set after benchmark-plan review | [Verification and proposed sequence](tech/engineering.md#agent-release-verification-draft), [benchmark draft](tech/engineering.md#agent-benchmark-plan-draft) |

The user opened a documentation-first agent architecture interview on 2026-09-21 and selected Deep Agents on LangGraph: one lead with visible specialists, Copilot-style extension filling with user Next/Submit, outreach approved and sent from Command Center, and isolated scripts producing research documents. The backend targets always-on operation. Composio is central for Gmail, Google Calendar, Linear and Notion, with reviewed external changes; Slack comes next. The [first-release boundary](product-spec.md#first-agent-release--confirmed-interview-direction) precedes later unattended applications. [Product Spec](product-spec.md#agent-architecture-interview--opened-2026-09-21) owns the interview. The [technical architecture draft](tech-spec.md#first-agent-release-architecture-draft) covers data ownership, service/module boundaries, async/Celery, agents/skills/memory/handoff, MCP discovery and token efficiency; [Engineering](tech/engineering.md#agent-release-verification-draft) maps verification, and [Design](tech/design.md#new-agent-experience--interview-draft) records interaction contracts and the Simplify reference. The new architecture has not completed engineering review or implementation.

First application targets are Greenhouse, Lever, Ashby, Workday and iCIMS; required support is distinct from verified coverage. Gmail searches relevant messages on request in one selected account. The user's dashboard/system-of-record request is developed in the [dashboard proposal](tech/design.md#dashboard-and-work-inspector-proposal) and [record/projection contract](tech-spec.md#system-of-record-and-dashboard-projections). The user selected work-first dashboard priority, ongoing conversations per task/opportunity, reviewed reusable memories, preservation of existing form values and the general portfolio resume as the default upload. Spending amounts follow review of the [benchmark plan](tech/engineering.md#agent-benchmark-plan-draft). New instructions steer active work at safe points; the first deployment keeps the existing Docker stack on one always-on server; research produces editable cited documents with PDF export and optional reviewed Notion publication. Detailed scope, execution/recovery, deployment and delivery contracts remain under engineering review.

The connected workspace and operator-run CSV/cached-Notion import exist. The full autonomous application loop remains a later product objective. Nine accepted engineering fixes and the UI delivery status are tracked in [Engineering](tech/engineering.md#accepted-workspace-hardening). The user approved a same-page layout with fewer competing actions and requested selectable appearance; implementation and reference findings are recorded in [Design](tech/design.md). The interview partially answers Q7–Q9 for the first release; remaining campaign choices stay explicit in Product Spec.

## Source history

[Source History](https://app.notion.com/p/3e22e26208a581c9b075e0617a050b6d)

The former Planning Doc, duplicate requirements, standalone lead/agent notes and interview/comment worksheets have been absorbed into the two specs. Their historical copies remain reference material, outside active navigation. Local pre-consolidation copies are gitignored under `.local/history/` and `.local/source/`.

## Local mirror

The repository mirrors this hierarchy under `docs/`. Page mappings and last-published hashes live in `docs/notion-map.json`. Current revisions are local and have not been published to Notion; the manifest still describes the prior published revision. Future publishing must fetch first and preserve concurrent changes. Root `AGENTS.md` contains coding-assistant instructions. Private review artifacts under `~/.gstack/projects/command-center/` are supporting evidence, not additional active specifications.
