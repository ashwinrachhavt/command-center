# Request cost and evaluation

Command Center traces claimed agent runs in optional, self-hosted Langfuse. The run UUID without hyphens is its stable trace ID; conversation IDs group requests into sessions. Resuming a question adds observations to the same trace. Answer reuse, cancellation, failure and waiting states are recorded. Model generations include specialists and compaction, with model identity, input/output counts, cache reads, message characters and tool-schema characters. Tool observations record names, roles and outcomes. Content capture is off by default. Set `CC_LANGFUSE_CAPTURE_CONTENT=true` to export bounded diagnostic copies of the request, answer, model messages and tool input/output. The local installation opts in. Captures redact configured credentials, credential-shaped text and email addresses, omit reasoning/media blocks, and mark truncation at a 12,000-character content budget. This is limited diagnostic redaction, not a guarantee that all personal information is removed. Originals remain in PostgreSQL. Disabled capture is explicitly labeled instead of unexplained null fields.

## Runtime efficiency

Runtime efficiency also uses scoped concurrent tool discovery, a run-local cache for exact immutable document passages and pinned catalog searches, and a model-input projection that replaces repeated identical read bodies with references to the first full result. The canonical checkpoint keeps every original result. Cache keys include role and consumed instruction sequence; errors, writes, mutable workspace reads and connected-app reads are not cached. Caches are bounded to 32 entries of at most 32,000 characters and are never reused across runs. Dynamic budget hints follow the history, preserving the long system prefix for provider caching; simple initial responses add no budget hint.

A synthetic benchmark with five independent 40-ms discoveries measured median setup of 204.56 ms sequentially and 82.06 ms with concurrency four (60% less setup time). Three repeated immutable passages required one physical read, and their repeated result text fell from 37,800 to approximately 12,800 characters (66% less result text). These are bounded component measurements without paid models, not a claim of equivalent end-to-end token or cost savings. Langfuse records actual provider usage and cost for subsequent requests.

## Local setup

Run `make langfuse-up`, then rebuild the API/worker containers to load their server-only settings. Open http://localhost:3003. The generated login is stored in root `.env` under `CC_LANGFUSE_USER_EMAIL` and `CC_LANGFUSE_USER_PASSWORD`; project API keys remain there too. Setup fills blank values and preserves existing secrets. `make langfuse-down` stops the separate stack without deleting its volumes. On Linux, set `CC_LANGFUSE_DOCKER_URL` to a reachable address for the instance.

The Compose stack follows [Langfuse's deployment](https://langfuse.com/self-hosting/deployment/docker-compose) and [headless initialization](https://langfuse.com/self-hosting/administration/headless-initialization). It binds the UI and object-storage port to localhost. The local memory/thread limits are for a small development workload, not a production sizing recommendation. The stack stores traces in its own PostgreSQL/ClickHouse/object-storage volumes; it does not replace the application's PostgreSQL or Redis.

The verified local installation uses Docker Desktop with 10 GB allocated. At 8 GB, the combined existing services, builds and Langfuse exhausted available VM memory. Langfuse web also needs the larger Node heap configured in Compose. Check health before running paid evaluations.

In Langfuse, open **Tracing**, find a request by run ID and inspect its model generations. Langfuse's model catalog prices reported token types. Configure a matching model price for custom model IDs; a missing price or missing provider usage is unknown, not evidence of a free call. Provider invoices remain authoritative. Command Center's existing spending ledger uses its immutable rate cards and conservative reservations; its estimates can be higher than Langfuse's cache-adjusted estimates.

## Reading token counts

Cached input is part of input. A request with 30,000 input tokens, 25,000 cached input tokens and 500 output tokens used 30,500 tokens, not 55,500. For a provider where cached input is a subset, estimated cost is:

`(input - cached) × input_rate + cached × cached_rate + output × output_rate`

Rates must use the same unit (usually per million tokens). A run can include several generations; each resends its current prompt and context. Compare both tokens per generation and generations per request. Caching reduces price but does not eliminate the input or unnecessary tool calls.

The supervisor exposes `catalog_search`, `catalog_execute` and `ask_user` initially. Its original server capability grants remain authoritative, and specialists retain their scoped schemas. Discovery loads only the selected operation schemas. A regression measures the actual model invocation's domain schemas. The lead directive explains the LinkedIn connector's search limitations and asks for missing selection criteria before account lookups. Cancellation summaries remain durable context; original messages and receipts are retained.

## DeepEval

DeepEval runs in the isolated Python evaluation environment and publishes scores to Langfuse; it does not execute inside Langfuse's standard-library-only code evaluator. [Official integration](https://langfuse.com/resources/engineering/deepeval).

`make eval-check` runs offline adapter tests. `make eval-chat` prints the three-case synthetic smoke plan without model calls. After `make check`, `make eval-chat allow_paid=1` generates actual greeting/LinkedIn-limit/document responses through the runtime, evaluates each on grounding/relevance/completion, and publishes scores. The current GPT-6 Sol smoke covers a greeting, unsupported LinkedIn lead search and a real model/tool loop over a synthetic Document Vault fixture. Generation is capped at USD 0.40 and judging at USD 0.12, with no retries. This focused smoke is separate from the full workflow/ATS suite and cannot establish general model quality. Outputs are synthetic, private and untracked. No real LinkedIn reads or contact writes occur.

For full recorded-output reports, use `make eval-paid plan=... captures=... langfuse=1`. Optional capture `trace_id` links scores to the original request without importing its generation twice. Synthetic evaluator observations include the prompt, evidence, expected behavior and actual output for review. Judge calls use separate traces so evaluation spend is distinguishable from request spend. Errors receive categorical error statuses, never fabricated numeric scores. Reports retain failed attempts locally. The API SDK buffers exports; verify ingestion in the UI/API before claiming a report arrived. On Langfuse v4 in events-only mode, use `client.api.observations.get_many` and `client.api.scores_v3.get_many_v3`; the legacy trace and score listing endpoints return 404.

Automatic paid judging of every user request is intentionally absent: it could cost more than the optimized request. Use focused regressions and sampled evaluations after meaningful changes.

### Verified synthetic results, 2026-09-23

Actual runtime generations using GPT-5-mini, low reasoning, a 1,000-output-token limit and fresh conversations:

| Case | Model calls | Total input | Cached subset | Output | Langfuse request estimate |
| --- | ---: | ---: | ---: | ---: | ---: |
| Greeting | 1 | 4,116 | 0 | 18 | $0.001065 |
| LinkedIn lead clarification | 1 | 4,133 | 3,968 | 386 | $0.00091245 |

The LinkedIn run paused with one `ask_user` request; no external lookup or contact write occurred. These are measured fresh-context results, not a replay of the user's longer cancelled conversation or proof that every request now costs this amount. The deterministic schema comparison is 30,393 to 1,501 characters (95.1% less domain-tool schema text), not a 95.1% reduction in all input tokens.

The initial report exposed verbose answers and an evaluator HTTP-client event-loop problem. The next captured responses passed semantic review, but the judge penalized factual grounding for harmless wording differences. The grounding rubric now explicitly measures factual support independently of wording and completeness; its threshold remains 1.0. Rejudging the same captured outputs produced grounding/relevance/completion scores of 1.0/0.9/0.8 for the greeting and 1.0/0.9/1.0 for LinkedIn, passing all six thresholds. This final judging pass cost an estimated $0.006346, separately from request cost. Prior failures remain recorded; these two cases are a smoke evaluation, not full workflow coverage or statistical quality evidence.

Local final report: `.local/evals/20260923T221252Z-fe16c153d3ba44d884e98799c601dcaf/report.json`. The verified Langfuse request IDs are `703c58d04fdd4facbb5545c63b97a126` and `2361cbf19665421b8267d73d1df1652f`. Their original generations were not imported again during rejudging. Live API checks confirmed observations, all six final scores and separately priced judge observations.

## Model quality and optional Jev routing

The supervisor and research/writing/application/outreach profiles now default to `gpt-6-sol`; the short connection-note profile uses `gpt-6-luna`. Explicit session selections and already pinned runs keep their model. GPT-6 function calling uses Responses. Each worker invocation owns and closes an explicit asynchronous HTTP client, shared by its models within that run; cached clients must not cross the separate event loops used by successive Celery invocations. Sol is a quality-oriented default and costs more per token than Luna; no blanket cost reduction is claimed. The small discovery surface, context bounds, answer reuse and bounded tool results still limit input. [Sol capabilities and pricing](https://developers.openai.com/api/docs/models/gpt-6-sol), [Luna](https://developers.openai.com/api/docs/models/gpt-6-luna).

Jev is implemented as an optional typed capability router, disabled by default and enabled locally with `CC_JEV_ENABLED=true`. Select exactly one server transport with `CC_JEV_PROVIDER`: `typesafe` uses `TYPESAFE_API_KEY` (legacy alias `CC_JEV_API_KEY`), `gateway` uses `AI_GATEWAY_API_KEY`, and `venice` uses `VENICE_API_KEY`. The local installation selects Gateway. There is no automatic cross-provider retry or credential fallback. The supervisor pins eligibility through `jev_routing`. It sends at most 2,000 characters of the current request, with configured secrets and email addresses redacted, using five fixed routes: documents, Gmail, CRM, research and general. It supplies a short static discovery hint only above both confidence (0.85) and chosen-probability (0.8) thresholds. The agent still discovers the exact schema and all existing permissions, leases, ownership and human-review rules remain enforced. Jev does not generate answers, select recipients, approve writes or change the user's chosen chat model.

The attempt marker is persisted before dispatch. A recovered/paused run never retries an uncertain paid routing call. There is one attempt per fresh eligible run, a three-second overall timeout, no HTTP retries, and a fallback to normal agent behavior on outage, invalid output, uncertainty or unavailable budget. Model reservations and reported usage go through the existing spending ledger; unknown usage retains its reservation. Routing is a separate Langfuse generation in the request trace. Gateway-reported cost, including an explicit zero, takes precedence in Langfuse; otherwise the listed rate estimates cost. The spending ledger retains conservative list-price accounting, so a temporary promotion does not silently remove budget protection.

Direct TypeSafe pins `jev-1.13.0`; Gateway uses its published `typesafe-ai/jev` alias at `POST /typesafe/v1/systemone`, and Venice uses `jev-latest` at `POST /api/v1/decisions`. Gateway/Venice aliases may change underlying versions. Their live model catalogs list $0.042 per million input tokens and free output tokens, verified 2026-09-23. Migrations `0034_routing_rates` and `0035_jev_gateways` add these exact billing identities to new immutable app-managed default cards, preserving existing explicit rates, custom cards and policy limits. [TypeSafe models](https://docs.typesafe.ai/models), [Gateway TypeSafe API](https://vercel.com/docs/ai-gateway/sdks-and-apis/typesafe), [Venice decisions](https://venice.ai/lp/jev).

Live synthetic checks classified all five route categories correctly through Gateway, taking 337–547 ms including trace flushing. Gateway reported $0 for each checked call; do not assume that promotion will persist. A direct TypeSafe document-routing check also passed with the configured key. Venice model access and its HTTP contract were checked, but no live Venice decision was needed. All six decision traces have input/output, usage and explicit costs in Langfuse; exact-label routing scores are separate from DeepEval's chat-quality scores. The retained local report is `.local/jev-live-results.json`.

These six cases are a smoke check, not calibrated quality evidence. End-to-end net savings remain unmeasured. Compare matched baseline/candidate tasks on task success, total cost including the router, tool retries and latency before widening the router's responsibilities. A hint helps only when it prevents an otherwise wasted discovery/model round trip. Do not insert routing before every tool.

### Sol follow-up evaluation

The current three-case report is `.local/evals/20260924T001208Z-ccf0e5878116472e9c43cf85fba2cc91/report.json`. The completed greeting and LinkedIn generations were reused from the earlier partial report; the Vault case was generated after extending the synthetic fixture to support saving a sourced plan without workspace writes. Failed attempts remain recorded. `chat_smoke --reuse-captures PATH` checks suite/input/model identity and preserves each capture's original prompt/tool hashes, harness revision and trace ID; it does not charge for those generations again.

| Case | Model calls | Total input | Cached subset | Output | Langfuse request estimate | Grounding / relevance / completion |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Greeting | 1 | 3,921 | 3,918 | 6 | $0.0008496 | 1.0 / 0.4 / 0.8 |
| LinkedIn clarification | 1 | 3,938 | 3,935 | 180 | $0.002593 | 0.9 / 0.9 / 0.9 |
| Vault interview plan | 4 | 17,542 | 16,785 | 336 | $0.008231 | 1.0 / 0.9 / 0.9 |

Seven of nine checks passed. The failed greeting relevance score penalized the absence of an optional follow-up question despite the brief-greeting requirement. The LinkedIn grounding score flagged the arbitrary-profile limitation, which is stated in the actual connector directive but missing from the evaluation evidence. These are unresolved evaluation-fixture/rubric discrepancies; the report remains failed, with thresholds unchanged and no repeated judging to obtain a pass. The Vault case read its actual synthetic source and passed every quality threshold. This judging pass cost an estimated $0.010837. Earlier failed generation attempts, including unknown-usage reservations, are separate and are not included in these successful-request totals.

Live Langfuse API verification confirmed nonempty root/model input/output, all nine scores and cache-adjusted costs. Request trace IDs: `cf0c2e09784e4aaba443d163db5488a0`, `b803223431474d0986d82045d32d0ec5`, `4b14c81ebdc74f54bc45522bf3c1c912`. The new client-lifetime regression checks successive Responses calls in separate event loops, matching Celery's per-invocation execution.

## Persistence verification

Long runs emit deterministic public updates after three finished operations, then every five, or after 20 seconds while waiting. Updates use the existing durable SSE event stream and require no extra model calls. Middleware tells the current model its remaining shared budget, removes exhausted lookup tools from subsequent bindings, and enforces the same quota through catalog execution. Supervisor/research defaults allow six search calls and four source captures per run; requested saves retain the remaining general budget.

Failures, time limits and cancellations with recorded work retain an explicit partial reply in the conversation. Pending tool steps become interrupted with unconfirmed outcomes. The next user message receives bounded receipts from the preceding stopped run in the same owned conversation, prioritizing saved record references. This is working context, not reviewed long-term memory or permission to replay an external action. Existing PostgreSQL LangGraph checkpoints, immutable source/artifact records and reviewed memory remain the stores; no new database or automatic paid recovery is introduced. A user can say “continue” to begin a new bounded run that checks saved state before retrying work. Existing runs retain their pinned lookup limits.

Langfuse is a diagnostic projection, not the conversation store. Application messages, answers and run state are saved in PostgreSQL; LangGraph persists execution checkpoints in `agent_checkpoints`. Current LangGraph message channels use delta storage, so inspecting `saver.aget_tuple().checkpoint["channel_values"]` directly can omit messages. Reconstruct state using the compiled graph's `aget_state` API. The screenshot's completed run was checked read-only: both conversation messages were saved and `aget_state` reconstructed ten messages and the matching final answer, with no pending nodes or model calls. Content capture applies to new observations; historical metadata-only traces are not fabricated or replayed.
