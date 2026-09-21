# Command Center

**Revision:** 2026-09-21-r5. **Status:** connected workspace implemented; agent/browser and design verification recorded in HANDOFF.

A local workspace for autonomous job discovery, relationships, research, tailored applications and follow-ups. Product and technical decisions have one canonical home each.

## Specifications

[Product Spec](product-spec.md)

User workflows, scope, lead behavior, requirements, acceptance and open product decisions. Supporting document: [product.md](product/product.md).

[Tech Spec](tech-spec.md)

Architecture, data model, evidence, agents, APIs, integrations, privacy/recovery and reference learnings. Supporting documents: [engineering.md](tech/engineering.md) and [design.md](tech/design.md).

## Operational leads

[Leads Real Data](https://app.notion.com/p/3e22e26208a58027b5f4d84258dd8c6f)

[Command Center — Contacts & Relationship Registry](https://app.notion.com/p/3e22e26208a58182be40d036fd9561cf)

These operational pages are unchanged by consolidation. Live personal content is not copied into committed documentation. Product Spec defines future staged ingestion.

## Planning state

Title/URL/LinkedIn CSV inputs, Notion seed leads, new-lead discovery, tailored answers and automatic browser applications are confirmed direction. The user authorized the FastAPI/Next.js scaffold, PostgreSQL in Compose, existing Firecrawl/SearXNG connections, and Rails-inspired fat models/thin controllers. The backend-first foundation now has a mockup-led Next.js/shadcn frontend, Clerk, LangGraph/Celery/MCP tools, skills/memory and a paired browser companion. Target filters, connection priority, campaign limits, unknown-answer handling, outreach sending and budgets remain explicit questions in Product Spec.

## Source history

[Source History](https://app.notion.com/p/3e22e26208a581c9b075e0617a050b6d)

The former Planning Doc, duplicate requirements, standalone lead/agent notes and interview/comment worksheets have been absorbed into the two specs. Their historical copies remain reference material, outside active navigation. Local pre-consolidation copies are gitignored under `.local/history/` and `.local/source/`.

## Local mirror

The repository mirrors this hierarchy under `docs/`. Page mappings and last-published hashes live in `docs/notion-map.json`. The scaffold revisions are local and have not been published to Notion; the manifest still describes the prior revision. Future publishing must fetch first and preserve concurrent changes. Local `docs/HANDOFF.md` records current work; root `AGENTS.md` contains coding-assistant instructions.
