# Local Command Center MCP clients

Command Center uses FastMCP 3 for a shared, explicitly authorized catalog. In-app agents use `/mcp/` with short-lived run/lease credentials; local Claude Code and Codex use the stdio bridge with individually revocable actor-bound credentials. Both paths call the same owned FastAPI operations. Local clients need no database access, model provider keys, Clerk signing keys or API administrator token.

## Set up a client

Start the API and apply the repository migrations, including `0030_mcp_clients`. In the signed-in application, create a named local MCP client credential. The token is shown once. Choose a separate credential for each client so it can be revoked independently. Credentials expire after 90 days by default (configurable from 1 to 365 days).

From the repository root, save the token through a hidden prompt:

```bash
uv run --project apps/api python -m command_center.agents.local_mcp configure \
  --token-file "$HOME/.config/command-center/codex-token"
```

The command writes a private file with mode `0600`. Do not put the token in a command argument, project configuration, prompt, or tracked file. The bridge accepts HTTPS URLs, or HTTP on localhost, and rejects credential-bearing URLs and non-private token files.

Register the stdio server with an absolute repository path (replace `/absolute/path/command-center` below):

```bash
codex mcp add command-center -- \
  uv run --project /absolute/path/command-center/apps/api \
  python -m command_center.agents.local_mcp serve \
  --url http://localhost:8000/mcp/ \
  --token-file "$HOME/.config/command-center/codex-token"
```

For Claude Code, create a separate named credential and token file, then:

```bash
claude mcp add --transport stdio --scope user command-center -- \
  uv run --project /absolute/path/command-center/apps/api \
  python -m command_center.agents.local_mcp serve \
  --url http://localhost:8000/mcp/ \
  --token-file "$HOME/.config/command-center/claude-token"
```

The stdio bridge proxies discovery and calls to the shared authenticated server. Revoking the credential in the app blocks subsequent discovery/API calls even if a bridge process remains open. Restart the client after replacing a token file because the bridge reads the token at startup.

## Tool coverage and review boundaries

The machine-checkable inventory is [`mcp_policies.json`](../../apps/api/src/command_center/agents/mcp_policies.json). Every API operation has an explicit policy. New unclassified routes receive no capability; a contract test requires their classification. Additional operation schemas come from each approved route's typed FastAPI contract, rather than an unrestricted HTTP/SQL tool.

| Policy | Behavior |
| --- | --- |
| `tool` | Executes a typed owned operation, preserving API validation, versions, receipts and workflow checks. |
| `runtime` | Executes in the assigned leased run. Local clients receive `context_required` with the concrete conversation workflow to establish that scope. |
| `human` | Returns `human_required`; never treats an agent request as human consent or approval. |
| `transport` | Uses a specialized authenticated UI/device transport, such as document multipart upload, binary download, browser pairing, or streaming events. |

Direct tool families include CRM lookup/create/update/archive, task and work queues, artifacts and immutable versions, document text/import status, reviewed facts, application context and tracking reads, conversations/runs, public research, connected context/action proposals, writing-draft reads, PDF jobs, and spending reads. Existing configured providers, spending policies and owned task/application context remain prerequisites where the API requires them.

Runtime output tools (`save_record_work`, `save_application_material`, `suggest_application_answers`) preserve the assigned run's provenance. Memory proposals also require run provenance. Local users can start record work with `cc_record_work_start_work`, or create/select an owned conversation with `cc_conversations_create_session` and request the workflow using `cc_conversations_receive_message`. Application preparation and material-generation initiation retain their existing human selection/review steps. The generated output is persisted by its assigned runtime.

Human-only operations include reviewing profile facts/memory/artifact versions, approving or reconciling external actions, connecting/selecting accounts, explicit mail pulls, paid contact-provider actions, browser pairing/fill/generation decisions, confirming application outcomes, changing spending policy, and managing MCP credentials. Merely listing a human-required helper does not mean that it executes the operation. Private binary uploads/downloads use the signed-in document UI; document text is available through `document_read`. No local filesystem tool is exposed.

## Arguments, retries and progressive discovery

Additional API tools place path/query parameters at the top level and the typed JSON request under `body`. Existing handwritten tools retain their argument shapes. Every local mutation requires a top-level `operation_id`: use a new identifier for a new action and reuse it with identical arguments for a retry. The API's durable receipt rejects conflicting reuse. The token is never a tool argument.

In-app lead agents can hold explicit `catalog_search` and `catalog_execute` grants. Search returns a bounded page of matching operation schemas; execute validates the selected schema and invokes its reviewed handler. These two small schemas avoid loading the entire catalog on every model turn. A specialist receives only its pinned profile grants; the broad catalog grant is never inferred from the lead's grant.

To add a capability, register its typed API route and add its exact method/path, unique tool name, policy and reason to the inventory. Grant that name to the relevant profile, or use the lead's explicit catalog grant. Existing `ToolRegistry` handlers remain reusable. `mcp_policy.register_operation()` supports a trusted extension registered before application construction; it is not exposed to models.

Local audits include `initiator=local_mcp` and the client credential ID. The server stores only the token hash, checks revocation/expiry on every invocation, and fences writes after external I/O. MCP and API audiences remain separate. Human review endpoints are outside the local API policy.

## Provisioning API contract

These endpoints require an authenticated human session:

- `GET /api/v1/mcp-clients`: up to 100 credential metadata records, newest first.
- `POST /api/v1/mcp-clients` with `{ "name": "Codex", "expires_in_days": 90 }`: `201`, metadata plus a one-time `token`.
- `POST /api/v1/mcp-clients/{client_id}/revoke`: metadata with `revoked_at` set; idempotent.

Metadata fields are `id`, `name`, `created_at`, `expires_at`, and nullable `revoked_at`. There is no `last_used_at` field. Hashes and tokens never appear in list/revoke responses or audit metadata.

Synthetic verification covers actual HTTP and stdio discovery/calls, audience separation, actor isolation, revoked/expired clients, human-review denial, exact retry receipts, concurrent clients, progressive discovery/execution and the existing scoped worker path. No live workspace, paid model or real provider action is required.
