# Agent efficiency and reliable interaction

Research and implementation review: 2026-09-24. This is supporting engineering guidance; [Tech Spec](tech-spec.md), [Product Spec](../product/product-spec.md) and [Design Spec](../design/design-spec.md) retain ownership of their contracts.

## Optimize completed work

The useful target is **cost and latency per correctly completed task**, with visible evidence and recoverable partial results. Minimizing tokens alone can remove necessary context and increase repeated work. A fast answer that did not save the requested artifact is a failed task.

Command Center already has a suitable foundation: PostgreSQL owns tasks, immutable artifacts and action receipts; Deep Agents/LangGraph runs bounded conversations; Celery executes background work; persisted events drive the interface. Improve this path before adding another runtime or agents whose coordination costs exceed their contribution.

## Literature and practical implications

| Primary source | Finding relevant to this workspace | Application |
| --- | --- | --- |
| [ReAct, Yao et al., ICLR 2023](https://arxiv.org/abs/2210.03629) | Alternating decisions with tool observations allows plans to respond to external evidence. | Judge completion from saved records and tool outcomes. Keep private reasoning out of public activity. |
| [Building effective agents, Anthropic](https://www.anthropic.com/engineering/building-effective-agents) | Simple workflows are effective for predictable work; dynamic orchestration adds latency and cost. | Direct task routes and bounded specialists; avoid delegation for a single cheap lookup. |
| [Writing effective tools, Anthropic](https://www.anthropic.com/engineering/writing-tools-for-agents) | Clear interfaces, useful response formats and task-based evaluations improve tool use. | Progressive catalog discovery, bounded passages, exact version references and actionable errors. |
| [Effective context engineering, Anthropic](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) | Context is finite; relevant retrieval, compaction and scoped subagent context help manage it. | Retain the objective, constraints and references; reuse immutable reads; reload current authorization from structured state. |
| [Timeouts, retries and backoff with jitter, AWS Builders' Library](https://d1.awsstatic.com/builderslibrary/pdfs/timeouts-retries-and-backoff-with-jitter.pdf) | Layered retries amplify load; side effects need idempotency; jitter avoids synchronized retry bursts. | One retry owner for eligible reads, a shared attempt budget and preserved call identities. |
| [Deep Agents fault tolerance, LangChain](https://docs.langchain.com/oss/python/deepagents/fault-tolerance) | Transient, model-correctable, human-correctable and unexpected failures require different handling. | Retry known transient reads, return actionable errors, preserve durable questions, and propagate programming errors. |
| [τ-bench, Yao et al., 2024](https://arxiv.org/abs/2406.12045) | Tool-agent-user interactions require evaluation of task outcomes and consistent policy adherence. | Evaluate saved outcomes and repeated reliability, alongside latency and token usage. |

These are design inputs, not evidence that this application meets published benchmark scores. The choices below are repository-specific conclusions drawn from those sources and the current implementation.

## Implemented in this pass

### Finish within the existing call budget

The reported lead/research/reply run stopped at the **model-call cap**, after six allowed searches and four denied search attempts. That is distinct from LangGraph's recursion guard. A synthetic real-graph reproduction confirmed that an agent choosing research while it remained available could use every model call without saving its output. The old near-limit guidance considered tool calls, not the number of model calls needed to save and answer.

`WorkMiddleware` now supplies shared and per-tool remaining quotas from the first model call. With two model calls left, it exposes completion tools and closes research/discovery, including research invoked through `catalog_execute`. The last model call has no tools and asks for an honest final answer based on actual receipts. A depleted tool budget likewise switches to an answer. These are dynamic tool filters using the [LangChain middleware API](https://docs.langchain.com/oss/python/langchain/tools#dynamic-tool-selection), backed by the existing dispatch/accounting gates; no additional model routes the request.

Specialists leave two model calls for the supervisor and obey their configured role cap. Counts are shared under the existing lock and retained in checkpoints. A specialist hitting this reserve returns available save references and source excerpts to the supervisor; context, spending, cancellation and other failures still propagate. This preserves a chance to save remaining requested outputs and answer without silently starting another run. A partial result must identify unsaved work; bounded execution does not establish task success.

The lead directly exposes the small intake/research/document tool set alongside catalog discovery for other operations. Its directive keeps one pasted lead, company research and reply in one connected workflow, with three explicit deliverables. It avoids unnecessary delegation, repeated discovery and unrelated workspace/memory reads. This trades a few initial schemas for fewer discovery turns; live net token savings remain unmeasured.

The configured model-call, tool-call, search, output-token and recursion limits are unchanged. Synthetic regression coverage exercises two independent output saves, exhausted catalog quotas, specialist handoff, concurrent accounting and resumed counters. Paid model quality, cost per successful task and parity with another coding assistant still require matched outcome evaluations. Profile/directive changes apply to newly snapshotted runs after the updated API/worker is deployed; existing pinned runs retain their profile snapshots.

### Selective recovery

`WorkMiddleware` owns automatic tool recovery. Eligibility comes from the host capability map: catalog discovery and tools mapped exclusively to GET routes, including eligible tools reached through `catalog_execute`. Remote `readOnlyHint` values never authorize retries. Network-backed search/capture/provider operations using POST and all writes remain outside this policy.

An eligible read may make three attempts total for a known transport timeout/network error or HTTP 408, 429, 502, 503 or 504. Attempts use exponential jitter (250–500 ms, then 500–1000 ms); a valid `Retry-After` takes precedence. A requested delay above eight seconds returns the failure for later recovery instead of retrying early or holding a tool slot for a long wait. The existing run deadline still bounds all work.

Each retry reserves a shared tool attempt and consumes the relevant per-tool quota. Its attempt count persists with the existing tool ledger, so checkpoint replay cannot reset the automatic retry allowance. Cancellation interrupts backoff. Steering is checked before another dispatch. Concurrent duplicate immutable reads share the same underlying recovery work. Exhausted errors are not cached as evidence.

Authentication, permission, validation, missing-record, conflict and unclassified errors receive no automatic retry. Transport errors are sanitized before reaching model context. The classifier unwraps transport envelopes; source document text cannot instruct it to retry. Unknown exceptions still propagate for diagnosis.

Model SDK retries remain disabled. Failed model requests can have unknown billable usage and partially streamed output. Adding paid retries requires reservation/reconciliation and duplicate-output handling; a generic retry decorator is insufficient. Ambiguous external writes retain the existing reviewed-action reconciliation path.

### Less tool-dispatch overhead

MCP lookup previously built every tool object and copied every schema to find one tool. It now refreshes the actor/grant registry and constructs only the requested tool. Listing still returns the full scoped catalog. No credential or grant cache was introduced. The synthetic 100-tool regression verifies one construction per lookup, independent schema copies and immediate revocation between lookups. A local microbenchmark (10 warm-up pairs, 200 alternating samples per path) measured median lookup time of 0.649 ms before and 0.082 ms after; p95 was 0.712 ms and 0.132 ms. This measures tool construction/lookup only, excluding registry construction, transport and model latency. Raw measurements are retained locally in `.local/agent-efficiency-benchmark.json`.

### Streaming and recovery

The browser flushes pending text on a terminal event and releases the stream reader immediately, without waiting for connection closure or an animation frame. Stream reconnection only repeats the GET event delivery request from the persisted sequence; it never restarts agent work.

Transient HTTP/network failures have bounded, jittered reconnects. The client honors `Retry-After`, pauses while offline or hidden, and restores the consecutive-failure allowance when new durable activity arrives. Permanent access errors and invalid transport responses stop automatic reconnects and leave explicit recovery available. An unterminated event buffer is bounded at 256,000 characters.

Existing durable-first event delivery, immutable-read deduplication, prompt projection and bounded summarization remain in place. No additional model calls are used for recovery progress or catalog lookup.

## Verification and next measurements

Document tool reads now default to 4,000 characters; explicit requests retain the 12,000-character limit. Saved lead evidence exposes 400-character excerpts only with canonical immutable version IDs and a granted full-text retrieval route. Provenance and pagination remain available. Unsaved search results, errors and write receipts retain their original content. Stored artifacts are unchanged. Document pagination reaches the full source length and preserves whitespace at page boundaries.

A three-source synthetic fixture measured 9,999 bytes before projection and 2,483 bytes after, including continuation metadata (75.2% smaller). This is response-byte reduction, not token or quality evidence. [The experimental Strands worker](strands-experiment.md) shares host controls and stays opt-in. [Matched comparisons](runtime-benchmark.md) cover research, drafts and documents; offline results cannot justify a production runtime switch.

Deterministic tests cover transient/permanent errors, unchanged write behavior, shared/per-tool quotas, retry identity, checkpoint state, steering/cancellation, source-data isolation, scoped catalog lookup, terminal flush, reconnect replay, offline/hidden behavior and server-directed delay. See [Engineering](engineering.md#agent-efficiency-and-recovery--2026-09-24) for actual check results.

The full frontend run exposed worker contention: six failures with 33 isolated workers. Capping concurrency at four preserved test isolation and existing time limits; all 378 tests passed, with wall time dropping from 34.67 s to 19.48 s in this local comparison. The cap is now in `apps/web/vitest.config.ts`. This is test-harness timing, not application latency.

Before changing model routing or claiming end-to-end savings, capture the existing offline/explicitly funded evaluation scenarios with these measures:

| Measure | Definition |
| --- | --- |
| Task success | Correct owned artifact/action state, evidence and no unauthorized side effects |
| First feedback | Enqueue acknowledgement and first persisted visible activity, measured separately |
| Tool latency | Queue wait, catalog/discovery time, tool dispatch and result-to-visible-event delay |
| Completion latency | p50/p95 by task class, including retries and failed runs |
| Efficiency | Input/output/cached tokens, tool attempts and cost per successful task |
| Recovery | Transient recovery rate, permanent retries avoided and duplicate writes (must be zero) |
| Repeated reliability | Several independent runs of each scenario; report failures, not just the best attempt |

Use synthetic fixtures and redact operational traces. Numerical production latency targets, paid model comparisons, model routing changes and provider invoice savings are not established by unit tests. Existing budget setup and explicit paid-evaluation requirements still apply.
