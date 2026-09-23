# product.md — Direction and scope

**Parent:** [Product Spec](product-spec.md). **Revision:** 2026-09-23-r8. **Purpose:** strategy and decision rationale, not a second requirement list.

## Product thesis

**Central mission — confirmed 2026-09-23:** Command Center OS should let agents gather context and carry out coordination, repetitive work and follow-through across the user's work tools, so the user can focus on the most important task. Interview preparation is the immediate priority. Evaluate product progress by useful work completed and attention saved.

The desired connected surfaces include Gmail, WhatsApp, Slack, Notion, Calendar, PDFs, internet browsers and web forms. Composio is the preferred integration layer where supported, with appropriate document and browser capabilities alongside it. The user requested a standalone local Hinterview setup for practice now and explicitly deferred investigation of Hinterview/Command Center integration and broader cross-surface orchestration to a later session. This records the mission and future direction; availability and implementation of each connector remain separate facts. [Product Spec](product-spec.md#1-outcome-and-user) owns current behavior and approval boundaries.

The user expanded the direction on 2026-09-21 to a configurable agent workspace for operating a one-person company, then clarified it on 2026-09-22 as an all-in-one personal workspace for knowledge work and automation. Email, relationships, reading, connected ideas, writing, interviews, outreach and follow-through should feel like one coherent product. The original revamp order was **email/relationships/follow-up → routines/automation → Library/writing/linked tasks**. The latest D5 direction is to build connections now and defer routines; the broader roadmap does not make routine decisions a prerequisite. [Product Spec](product-spec.md#personal-work-os-revamp--confirmed-2026-09-22) owns the accepted delivery direction and unresolved behavior.

The implemented runtime uses Deep Agents on LangGraph with Celery and persistent task/opportunity conversations. After reopening the comparison with custom LangGraph and Codex, the user selected Deep Agents on LangGraph for the new architecture. Composio is the integration priority. A browser extension/client connects the running server to the user's signed-in local browser to inspect and fill forms seamlessly, without exporting browser cookies or profiles. The named AISpot/Youspot reference was uncertain inspiration, not a selected product dependency.

Job search is fragmented across job boards, relationships, inboxes, documents and portals. Command Center should turn a search intent into high-quality applications and deliberate follow-ups, while retaining the evidence and exact work used. Agents should do the repetitive browser work without requiring the user to supervise every field.

The durable foundation is relationships, evidence, artifacts/documents, tasks, actor identity and execution history. The user's 2026-09-22 clarification makes shared Tiptap writing and linked tasks prerequisites of email/follow-up, not a separate third-phase build. Deliver the shared capabilities needed by the current connections work; routines and the expanded Library can reuse them later. Job search supplied the initial full workflow; the current revamp prioritizes connections. The same relationship and discovery capabilities may support selling the user's AI SaaS products, without implying a separate sales-platform build.

The user explicitly keeps Gmail for inbox management. Command Center retrieves email only on an explicit request to pull it, then helps turn that context into writing, decisions and follow-through. Its all-in-one value is connected work and knowledge, rather than background replication of every connected application. Routine design must preserve this boundary.

The user also narrowed the LinkedIn import to contacts and professional profile in revamp D4. Complete that mapping without bringing historical message bodies into the workspace. The product connects the information selected for work; it does not need to archive every conversation to be useful.

For the immediate build, the user clarified that “connections” means connected external apps. App setup and account management come first, using the supplied mockups and current Composio integration. People/LinkedIn, shared writing and Library work remain in the broader roadmap; routines are deferred. The user wants the current slice running quickly, with ordinary implementation decisions handled without further interview rounds.

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
| Product, Tech and Design specs | Canonical outcome, architecture and UX contracts; absorb duplicate planning/context notes |

Latest agent-interview decisions refine the first delivery: one lead with visible specialists on Deep Agents; Copilot-style browser assistance with the user reviewing/clicking Next/submitting; outreach approved for sending inside Command Center; and isolated scripts producing interview-prep/company-research documents. The backend targets always-on operation while the authenticated application stays in Chrome. A reviewed Command Center profile backed by selected documents is authoritative; missing application answers are collected together. Composio initially targets Gmail, Google Calendar, Linear and Notion, with external changes reviewed and Slack next. Automatic application submission remains a later goal. [Product Spec](product-spec.md#first-agent-release--confirmed-interview-direction) owns this current release boundary and the unresolved product choices.

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

Product Spec owns capabilities, user journeys, acceptance and open product questions. Tech Spec owns architecture, model, states, runtime authority, integrations and sources. Its [engineering.md](../tech/engineering.md) owns work sequencing/tests; [Design Spec](../design/design-spec.md) owns the user experience. The home page is a navigation index. Existing operational leads remain unchanged and are linked, not duplicated here.

The latest navigation clarification treats Overview as one section: sidebar choices open full pages, while suitable body actions open dialogs or contextual side panels. The user selected pytest/pytest-mock for tests and mocking, and DeepEval for agent evals. These decisions are specified in [Product Spec](product-spec.md) and [Tech Spec](../tech/tech-spec.md); [Design Spec](../design/design-spec.md) owns interaction acceptance. The user subsequently authorized autonomous implementation; the Deep Agents runtime/conversation slice is implemented, while the broader workflows remain in progress.
