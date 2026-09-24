# Matched agent runtime benchmark

This benchmark runs the existing Deep Agents graph and the optional Strands harness against the same three synthetic cases: saved lead research, an unsent draft receipt, and an immutable document read. Both runs in a pair use the same LangChain model identity, profile limits, prompt, scoped tool schemas, and fixture result. It compares adapter behavior only; scripted tokens and local latency do not establish live token, quality, cost, or production savings. The benchmark never selects a production runtime.

## Setup and offline run

From the repository root, install the pinned optional Strands dependencies and run the benchmark:

```sh
uv sync --project apps/api --extra strands --frozen
make benchmark-runtime
```

The default is two repeats, with runtime order `deepagents, strands` on the first repeat and `strands, deepagents` on the second. The default model identity is `gpt-5-mini`, with reasoning effort unset (the provider default), six maximum model calls per run and a 512-token output bound. The command writes a private JSON report under `.local/runtime-benchmark/<UTC timestamp>-<run ID>/report.json` and prints its path. To match the currently configured lead's model identity without making provider calls, use `make benchmark-runtime args='--mode offline --model gpt-6-sol --reasoning-effort medium'`. To select other settings, use `make benchmark-runtime args='--mode offline --repeats 4 --reasoning-effort medium --max-calls-per-run 6 --max-output-tokens 512'`. These settings reach both runtime profiles and appear in their shared configuration hash. The benchmark wraps either runtime call in the same 90-second profile deadline; a timeout is reported as `benchmark_timeout`, and any unsettled spending reservation remains charged as unknown. Offline runs use a scripted LangChain model, require no provider key, make no paid calls, and use synthetic tool results. The lead-evidence fixture contains a short preview and an exact synthetic version ID; its full synthetic text is available to the scoped `document_read` fixture tool.

Each result records case, fixture, source and configuration SHA-256 identifiers; runtime and repeat; exact, untrimmed output and exact tool-call sequence checks; model attempts, tool calls, retries, `input_tokens`, `output_tokens`, `total_tokens` and `cached_input_tokens`; estimated cost; time to first agent text; time to the first tool call; first tool execution latency; and total duration. Aggregates give attempted/completed counts and p50/p95 duration and first-feedback times for each runtime and case. P50 is the median; p95 is the nearest observed rank; missing observations are `null`. `model_attempts` comes from the shared host checkpoint, which counts a denied reservation before provider I/O. Offline `model_calls` counts actual scripted model stream entries. Live `model_calls` is `null`; `reserved_model_calls` counts durable pre-call reservations, including compaction, without claiming every reservation reached a provider. Usage also comes from the shared checkpoint. The JSON labels offline token counts `scripted_fixture`; its estimated cost is `null`, because they are synthetic. A failed deterministic check remains visible in the report. No automatic promotion follows a result.

## Live comparison gate

Live mode uses the same synthetic cases and the same host model factory as the worker. It requires a current, source-attributed price file for the selected provider/model, an explicit positive micro-USD cap, and `--allow-paid`. The price file follows the existing evaluation `Price` contract. Example shape (replace every rate, model and verification time with verified current values):

```json
{
  "provider": "openai",
  "model": "gpt-6-sol",
  "price": {
    "input_micro_usd_per_million": 1000000,
    "output_micro_usd_per_million": 2000000,
    "source_url": "https://example.com/verified-model-pricing",
    "verified_at": "2026-09-24T00:00:00Z"
  }
}
```

Only after a reviewed allowance is supplied, the command is:

```sh
make benchmark-runtime args='--mode live --repeats 2 --provider openai --model gpt-6-sol --reasoning-effort medium --price-file .local/current-runtime-price.json --max-spend-micro-usd YOUR_APPROVED_CAP --max-calls-per-run 6 --max-input-tokens 20000 --max-output-tokens 512 --allow-paid'
```

Replace `YOUR_APPROVED_CAP` with a positive integer in micro-USD. Reasoning effort can be set only for OpenAI reasoning models whose host adapter passes that setting to the provider. The CLI rejects stale rates, a price identity mismatch, missing approval flags, and a cap below the conservative bound for every case, repeat, runtime and possible model call. The bound is `case count × repeats × two runtimes × max calls per run × Price.cost(max input tokens, max output tokens)`. No live call is attempted while these checks fail. The same durable budget is passed to both runtimes through `ModelSpendingGate`; each model or compaction attempt reserves before provider I/O. Settled usage reduces its charge; missing usage retains the reservation and stops later calls. Provider retries are disabled in the host model setup. The report labels live tokens `provider_reported` and includes both estimated usage cost and charged/reserved cost. Both use the supplied `Price` contract and charge cached input at the standard input rate. The estimate excludes cache discounts, is conservative, and is neither an invoice nor measured cache savings. Known usage still receives an estimate when a later part of the run fails; unknown usage keeps its full reservation.

Live mode does not fetch real contacts, messages, resumes, or applications. Its draft tool returns a synthetic unsent receipt and performs no external write. This comparison does not test Strands durable question handling or interrupted-run recovery, which remain unsupported experimental configurations. Deep Agents remains the production default.
