# engineering.md — Delivery and verification

**Parent:** [Tech Spec](../tech-spec.md). **Revision:** 2026-09-21-r5. **State:** connected workspace, authenticated agent harness and browser companion implemented; full campaign workflows pending.

## Build objective

Deliver the autonomous loop in [Product Spec](../product-spec.md): title/URL/CSV and reviewed Notion leads → discovery/qualification → source-backed material and tailored answers → browser fill/upload/submission → confirmation or reconciliation → follow-up. An importer-only demo is a foundation checkpoint, not the release outcome.

## Dependency-ordered work

| Stage | Work package | Exit evidence |
| --- | --- | --- |
| E-00 Decisions | Set target, connection, campaign, answer, outreach and budget rules; choose initial site/account scope | Product answers and accepted scope, with unresolved items explicit |
| E-01 Browser spike | Disposable profile and synthetic multipage application fixture; compare native filling with optional Simplify/custom bridge | Resume upload, tailored fields, redirects, interruption, one observed submission and supported invocation/completion contract |
| E-02 Foundation | Local API/web/worker, identity, migrations, artifact store, evidence, separate durable work queue and audit | Healthy local startup, schema/access checks, persistence and restore demonstration |
| E-03 Entry and seed | Job title/URL capture, minimum CSV staging and synthetic Notion-source mapping; canonical identities | Reviewable mapping/provenance, conflict and replay behavior |
| E-04 Discovery | Defined target search; legitimacy/fit/connection reasons; research and budgeted optional enrichment | Accepted/rejected/unknown examples with sources and clear quota/failure handling |
| E-05 Materials | Candidate facts/answer library, artifact/document versions, writer/review, package assembly | Tailored supported output, missing-fact cases, immutable version references |
| E-06 Execution | Campaign authorization, browser runner, events/receipts, stop and unknown-outcome reconciliation | Controlled end-to-end automatic application without duplicate replay |
| E-07 Pilot/recovery | Bounded configured real-site pilot and failures; monitor intervention, coverage and outcome | Account/site/material scope verified, exceptions actionable, restore cannot replay submissions |
| E-08 Expansion | More sources/portals, full archive support, Google sync, broader follow-up and later relationships | New capabilities retain the same contracts and regression evidence |

Some foundation work can accompany the spike; do not promise site coverage before checking it. No dates or effort estimates are assigned until the product rules and feasibility boundary settle.

## Ticket and contract requirements

Every implementation ticket names the user outcome, P requirement IDs, prerequisites, exact files/modules, migrations/indexes/constraints, API/tool schema, state transitions, permissions, failure/retry rules, synthetic fixtures and acceptance scenarios. Identify operational rollback/restore separately from a migration downgrade. Record selected package/runtime versions and reasons in the accepted technical decision log.

Keep long intelligence work outside API handlers. Keep trusted dispatch/storage access separate from model/tool sandbox privileges. Do not create a second draft/resume lifecycle or mix user task state with worker leasing. Follow the Tech Spec contracts; do not silently add Redis, vectors, another auth provider or a framework rewrite.

Implemented layout: `apps/api/src/command_center/{api,core,db,integrations}`; `apps/api/migrations`; synthetic `apps/api/tests`; minimal `apps/web`; root Compose, Makefile and setup/smoke scripts. Follow Rails-inspired fat models/thin controllers: SQLAlchemy model methods own validations/state changes and enqueue audit records; controllers establish authentication and transactions, then delegate. Model methods never commit their caller's transaction. Provider clients own HTTP I/O outside transactions. Avoid generic repository/service abstractions. `Task.complete` and `Task.reopen` are the first examples.

Worker, companion, agent runtime, CRM operations and artifact byte storage are later slices. Add directories when implementing their behavior. The user requested that `mockups/` guide later web/extension design; no complete product interface is implemented yet.

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

Actual commands: `make setup`, `make up`, `make check`, `make schema-check`, and `make smoke`. `make test` uses a separate tmpfs-backed PostgreSQL database named `command_center_test`, runs Alembic round trips, constraints, append-only triggers, stale-edit checks, atomic task/audit behavior and provider/API contracts. `make check` also checks Ruff/mypy and Next.js lint/types/production build. `make smoke` makes a public example query and scrape against the existing providers. See root README for startup, credentials and migration details.

## Operations and delivery evidence

Document startup, health/readiness, migration/upgrade, backup/restore, connector revoke/re-pair and browser halt/reconcile procedures. Monitor queue age, lease health, failed/paused work, disk/backup state, provider usage and application outcomes using redacted IDs rather than raw personal content.

Before handing off an implementation, record changed files, schema/API additions, commands/results, fixture demonstration, deliberate deferrals and remaining risks. Use the root [AGENTS.md](../../AGENTS.md) for coding-tool and workspace instructions. The current handoff is [HANDOFF.md](../HANDOFF.md).

Confirmed convention: YAGNI and DRY complement the Rails-inspired fat-model/thin-controller design; they do not replace it. Prefer concrete domain methods and only extract abstractions from demonstrated repetition. The frontend runs on port 3001.


## Connected-slice evidence (2026-09-21)

Checks: `make lint`, `make test`, `make schema-check`, `make contracts`, `npm run build --prefix apps/web`; browser regression from `apps/web`: `npm run test:browser` with localhost:3001 running. Tests use PostgreSQL, pytest-mock for paid-model responses and real MCP/HTTP/API execution. The extension content script runs in a real browser against a controlled synthetic form. Actual paid OpenAI/Composio execution requires operator credentials; configuration is not execution evidence. Use `make auth-check` / `make auth-sync` after setting Clerk credentials. Docker includes Redis plus worker/beat, and mounts versioned agent files read-only. Supabase uses the existing Alembic history and FastAPI access boundary; no deployment has been made.
