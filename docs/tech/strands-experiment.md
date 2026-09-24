# Strands worker experiment

Deep Agents remains the default. `AgentProfile.runtime` accepts `deepagents` or `strands`, pinned in each run's configuration snapshot. Strands Harness 0.1.2 and Strands Agents 1.57.0 are optional dependencies. Install them in the API/worker environment with `uv sync --project apps/api --extra strands --frozen`. `make check` installs and tests this extra; normal production installation does not enable it.

## What the experiment measures

[Strands' launch announcement](https://strandsagents.com/blog/introducing-strands-harness/) reports 28% lower token cost across six benchmark suites with comparable accuracy. This is a vendor result, not proof of fewer tokens or lower cost for Command Center. Prompt size, model choice, tool output, retries and task success all affect the result.

The adapter uses the actual Strands harness loop with Command Center's LangChain provider models, bounded summarizer, duplicate-read suppression, tool recovery and spending accounting. This compares two application-compatible runtimes, not the vendor's stock harness benchmarks. See the official [configuration](https://strandsagents.com/docs/user-guide/harness/reference/configuration/) and [context/caching](https://strandsagents.com/docs/user-guide/harness/configure/context-and-caching/) references.

`create_harness` receives no built-in tools or plugins. Local memory, skills, sessions, filesystem offloading, background tasks and SDK model retries are disabled. The host system prompt and existing provider configuration remain in use; native provider-side prompt caching is unaffected. Compaction uses the application's summarizer so exact references stay in existing storage and every summary call is accounted for. Temporary file references are not used as durable evidence.

## Worker boundaries

Celery selects the adapter from the pinned profile. Scoped MCP credentials, HTTP capability checks, approval routes, spending reservations, deadlines and the lease heartbeat remain host controls. Tools, public text, usage and final status use the existing durable event stream. Provider reasoning stays out of public text while original message metadata remains available to subsequent provider requests.

Every model call passes through `ModelAccounting`; scoped tools pass through `WorkMiddleware`. Read retries consume shared tool budgets, writes are not automatically retried, and host failures stop subsequent calls. Cancellation closes in-flight streams. Neither Strands nor the summarizer adds implicit paid retries.

This first adapter supports single-agent text/tool tasks. Profiles with specialists, skills, JEV routing or `ask_user` are rejected. Nonempty prior checkpoints and human-question resumes are rejected rather than replaying possibly completed writes. Inspect an interrupted experiment before starting a new run. Deep Agents continues to own workflows requiring these capabilities.

## Opt-in profile

After installing the extra in both API and worker environments, add an experimental profile to `agents/profiles.toml`, leaving existing profiles unchanged. For example:

```toml
[profiles.strands_experiment]
name = "Strands experiment"
description = "Experimental single-agent evidence and drafting tasks"
runtime = "strands"
provider = "openai"
model = "gpt-6-sol"
reasoning_effort = "medium"
directive = "writer"
tools = ["workspace_summary", "document_read", "draft_artifact", "approved_profile"]
max_steps = 6
max_output_tokens = 2500
max_tool_calls = 12
max_parallel_tools = 4
```

Select it for a new run; existing runs keep their snapshots. Standard spending policy and credentials remain required. A custom Compose image must include the extra; the default Docker image does not. This implementation has not switched profiles, running services or deployments.

Run `make benchmark-runtime` for the matched synthetic comparison. See [benchmark setup, report fields and explicit live-spend gate](runtime-benchmark.md). Scripted results verify integration, outcomes and accounting; funded live comparisons are required to establish model quality or token/cost savings.
