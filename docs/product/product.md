# product.md — Direction and scope

**Parent:** [Product Spec](../product-spec.md). **Revision:** 2026-09-21-r4. **Purpose:** strategy and decision rationale, not a second requirement list.

## Product thesis

The user expanded the direction on 2026-09-21: Command Center should become a configurable agent workspace for operating a one-person company, starting with the existing job/research/application workflow. The implemented runtime uses custom LangGraph/OpenAI. After reopening the comparison with custom LangGraph and Codex, the user selected Deep Agents on LangGraph for the new architecture. Composio is now the integration priority. A browser extension/client connects the running server to the user's signed-in local browser to inspect and fill forms seamlessly, without exporting browser cookies or profiles. The named AISpot/Youspot reference was uncertain inspiration, not a selected product dependency.

Job search is fragmented across job boards, relationships, inboxes, documents and portals. Command Center should turn a search intent into high-quality applications and deliberate follow-ups, while retaining the evidence and exact work used. Agents should do the repetitive browser work without requiring the user to supervise every field.

The durable foundation is relationships, evidence, artifacts/documents, tasks, actor identity and execution history. Job search is the first full workflow. Later, the same relationship and discovery capabilities can support selling the user's AI SaaS products; that possibility informs the model without expanding the current release into a sales platform.

## Decisions already made

Implementation direction confirmed 2026-09-21: start the scaffold with FastAPI, PostgreSQL in Docker Compose, Alembic, and Next.js; connect to the existing Firecrawl/SearXNG services. Prioritize backend/data-model correctness, using Rails-inspired fat models/thin controllers. The user subsequently requested the mockup-led shadcn web interface and browser companion, Clerk, LangGraph/OpenAI/Composio agents, MCP discovery, skills/memory and Celery/Redis. The connected workspace is implemented; future autonomous campaign policies remain separate. The new interview partially resolves Q7–Q9 for the first agent release; remaining policy is tracked in Product Spec.

| Decision | Rationale/source |
| --- | --- |
| Command Center name | Explicit user correction; applies locally and in Notion |
| Standalone local project, independent of Alfred | Source comment; own repository and deployment |
| Job-to-application first | Explicit user priority; importing supports the loop rather than becoming the whole release |
| Job title, URL and LinkedIn CSV inputs | Round-1 answer; discovery and relationship ingestion are real entry modes |
| Autonomous discovery, qualification, tailored answers and submission | Round-1 answer; a drafts-only outcome is insufficient |
| Start with Notion leads and discover more | Round-1 answer; Hunter/Apollo/Firecrawl/free sources form the desired strategy |
| Jobs, outreach and applications now; relationship/SaaS prospecting later | Round-1 answer; no generic business-platform release yet |
| One Product Spec and one Tech Spec | Latest organization decision; absorb planning/context and remove redundant active docs |

Latest agent-interview decisions refine the first delivery: one lead with visible specialists on Deep Agents; Copilot-style browser assistance with the user reviewing/clicking Next/submitting; outreach approved for sending inside Command Center; and isolated scripts producing interview-prep/company-research documents. The backend targets always-on operation while the authenticated application stays in Chrome. A reviewed Command Center profile backed by selected documents is authoritative; missing application answers are collected together. Composio initially targets Gmail, Google Calendar, Linear and Notion, with external changes reviewed and Slack next. Automatic application submission remains a later goal. [Product Spec](../product-spec.md#first-agent-release--confirmed-interview-direction) owns this current release boundary and the unresolved product choices.

## Scope tradeoffs

Prove the selected Copilot, reviewed-outreach and research-document experiences using the existing foundation, then progress toward unattended applications with explicit site support and a bounded target profile. Preserve simple contact/manual fallbacks and source/import provenance. Supporting the current assisted workflow does not establish that the later autonomous outcome has shipped.

General artifacts should cover messages, research, documents and packages. Documents/types should cover resume and non-resume material without a competing version store. First-class tasks and audit stay meaningful operational records. Precise schema and runtime choices belong in Tech Spec.

## Principles

- Evidence and uncertainty are visible at the point of a consequential decision.
- Personalization is grounded in actual candidate facts, with reusable answers for repeated questions.
- Automation follows declared authority and produces a recoverable outcome record.
- Current relationship evidence matters more than an opaque lead score.
- Local operation and portability are defaults; external data and cost policies are explicit.
- Written plans distinguish user decisions, engineering proposals, research findings and implementation results.

## Reconciled historical advice

The supplied Comp AI analysis contributes durable-worker, evidence, versioned-skill and build-contract patterns. Its old name, importer-first release, and blanket submission prohibition do not override the user's newer decisions. Comp AI is a reference to study, not a selected fork or a reason to change stacks. Source verification and engineering implications are in Tech Spec.

## Planning ownership

Product Spec owns capabilities, user journeys, acceptance and open product questions. Tech Spec owns architecture, model, states, runtime authority, integrations and sources. Its [engineering.md](../tech/engineering.md) owns work sequencing/tests; [design.md](../tech/design.md) owns the user experience. The home page is a navigation index. Existing operational leads remain unchanged and are linked, not duplicated here.
