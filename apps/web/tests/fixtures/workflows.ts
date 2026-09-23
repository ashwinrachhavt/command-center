import type { Schema } from "../../src/lib/api";

const account: Schema["AccountRead"] = {
  id: "11111111-1111-4111-8111-111111111111",
  row_version: 1,
  toolkit: "gmail",
  display_name: "Synthetic outreach · alex@example.com",
  provider_identity: { email: "alex@example.com" },
  connection_status: "ACTIVE",
  identity_verified_at: "2026-09-21T10:00:00Z",
  selected_purpose: "outreach",
};
const card: Schema["RateCardRead"] = {
  id: "22222222-2222-4222-8222-222222222222",
  name: "Synthetic rate card",
  source_label: "Offline UI fixture only",
  currency: "USD",
  rates: {
    models: [
      {
        provider: "openai",
        model: "synthetic-model",
        input_per_million_micros: 0,
        output_per_million_micros: 0,
        fixed_micros: 0,
      },
    ],
    tools: [],
  },
  sha256: "a".repeat(64),
  created_at: "2026-09-21T10:00:00Z",
};
const cards = [card];
let spending: Schema["SpendingSummary"] = {
  currency: "USD",
  configured: false,
  active: false,
  rate_card_id: null,
  monthly_limit_micros: null,
  default_work_limit_micros: null,
  row_version: null,
  readiness: {
    code: "spending_policy_unconfigured",
    message: "Configure and activate spending limits and a rate card first.",
  },
  period: null,
  work_budgets: [],
  invoice_note:
    "Provider invoices remain authoritative; unknown spend is retained until reconciled.",
};
const actions: Schema["ActionRead"][] = [
  {
    id: "33333333-3333-4333-8333-333333333333",
    row_version: 1,
    kind: "gmail_send",
    state: "proposed",
    account,
    task_id: null,
    opportunity_id: null,
    approved_revision_id: null,
    attempt: null,
    conditional_update_notice: null,
    created_at: "2026-09-21T10:00:00Z",
    updated_at: "2026-09-21T10:00:00Z",
    current: {
      id: "44444444-4444-4444-8444-444444444444",
      version: 1,
      tool_slug: "GMAIL_SEND_EMAIL",
      toolkit_version: "20260915_00",
      payload: {
        kind: "gmail_send",
        to: ["recruiter@example.com"],
        cc: [],
        bcc: [],
        subject: "Synthetic Northstar introduction",
        body: "Hi Alex,\nI would like to learn about the platform role.\nRegards, Sam",
        is_html: false,
      },
      payload_hash: "b".repeat(64),
      source_version_id: null,
      source_content_sha256: null,
      attachments: [],
      expected_remote_revision: null,
      observed_target: null,
      expires_at: null,
      review_state: "proposed",
      reason: "Requested introduction for synthetic review",
      created_at: "2026-09-21T10:00:00Z",
    },
  },
];
const recorded: {
  route: string;
  method: string;
  body: Record<string, unknown>;
  key: string | null;
}[] = [];
let conflict = false;

export async function workflowFixture(
  url: URL,
  init?: RequestInit,
): Promise<Response | null> {
  const route = url.pathname.replace("/api/backend/", "");
  const method = init?.method ?? "GET";
  const body =
    init?.body && typeof init.body === "string"
      ? (JSON.parse(init.body) as Record<string, unknown>)
      : {};
  if (route === "test/workflow-requests") return Response.json(recorded);
  if (route === "gmail/search" && method === "POST") {
    recorded.push({
      route,
      method,
      body,
      key: new Headers(init?.headers).get("Idempotency-Key"),
    });
    return Response.json({
      observation_id: crypto.randomUUID(),
      account_id: account.id,
      observed_at: "2026-09-22T18:00:00Z",
      next_page_token: null,
      result_size_estimate: 1,
      messages: [
        {
          messageId: "synthetic-message",
          subject: "Synthetic project note",
          sender: "Taylor <taylor@example.com>",
          messageText: "Here is the context you explicitly asked to pull.",
          display_url:
            "https://mail.google.com/mail/u/0/#all/synthetic-message",
        },
      ],
    });
  }
  if (route === "test/action-conflict") {
    conflict = true;
    return Response.json({ ok: true });
  }
  if (route === "test/action-unknown") {
    actions[0].state = "outcome_unknown";
    actions[0].attempt = {
      id: "55555555-5555-4555-8555-555555555555",
      state: "outcome_unknown",
      provider_log_id: "synthetic-receipt",
      provider_external_id: null,
      provider_url: null,
      receipt: null,
      observed_before_revision: null,
      observed_after_revision: null,
      error_code: "provider_outcome_unknown",
      reconciliation: null,
      started_at: "2026-09-21T10:05:00Z",
      completed_at: "2026-09-21T10:05:01Z",
    };
    return Response.json({ ok: true });
  }
  if (
    !["spending", "integrations/composio/accounts", "reviewed-actions"].some(
      (prefix) => route.startsWith(prefix),
    )
  )
    return null;
  if (method !== "GET")
    recorded.push({
      route,
      method,
      body,
      key: new Headers(init?.headers).get("Idempotency-Key"),
    });
  if (route === "spending/catalog")
    return Response.json({
      models: [
        {
          provider: "openai",
          model: "synthetic-model",
          label: "OpenAI · Synthetic model",
        },
      ],
      tools: [
        { slug: "GMAIL_GET_PROFILE", label: "Verify Gmail identity" },
        { slug: "GMAIL_SEND_EMAIL", label: "Send Gmail message" },
        {
          slug: "COMPOSIO_CONNECTED_ACCOUNTS_LIST",
          label: "List connected accounts",
        },
      ],
    });
  if (route === "spending/rate-cards") {
    if (method === "POST") {
      const created = {
        ...card,
        id: crypto.randomUUID(),
        name: String(body.name),
        source_label: String(body.source_label),
        rates: { models: body.models, tools: body.tools },
      } as Schema["RateCardRead"];
      cards.push(created);
      return Response.json(created, { status: 201 });
    }
    return Response.json(cards);
  }
  if (route === "spending/policy") {
    if (Number(body.monthly_limit_micros) < 60_000)
      return Response.json(
        {
          detail: {
            code: "spending_limit_below_committed",
            message:
              "The limit cannot be below reserved, accounted, or unknown spend.",
          },
        },
        { status: 409 },
      );
    spending = {
      ...spending,
      configured: true,
      active: Boolean(body.active),
      rate_card_id: String(body.rate_card_id),
      monthly_limit_micros: Number(body.monthly_limit_micros),
      default_work_limit_micros: Number(body.default_work_limit_micros),
      row_version: (spending.row_version ?? 0) + 1,
      readiness: null,
      period: {
        starts_at: "2026-09-01T00:00:00Z",
        ends_at: "2026-10-01T00:00:00Z",
        limit_micros: Number(body.monthly_limit_micros),
        accounted_micros: 10_000,
        reserved_micros: 20_000,
        unknown_micros: 30_000,
        committed_micros: 60_000,
      },
    };
    return Response.json(spending);
  }
  if (route === "spending") return Response.json(spending);
  if (route === "integrations/composio/accounts")
    return Response.json([account]);
  if (route === "integrations/composio/accounts/sync")
    return Response.json([account]);
  if (route.endsWith("/select")) return Response.json(account);
  if (route === "reviewed-actions" && method === "GET")
    return Response.json({
      items: actions,
      total: actions.length,
      offset: 0,
      limit: 20,
    });
  if (route === "reviewed-actions" && method === "POST") {
    const created: Schema["ActionRead"] = {
      ...actions[0],
      id: crypto.randomUUID(),
      state: "proposed",
      current: {
        ...actions[0].current,
        id: crypto.randomUUID(),
        payload: body.payload as Record<string, unknown>,
        reason: String(body.reason),
      },
    };
    actions.push(created);
    return Response.json(created, { status: 201 });
  }
  const action = actions.find((item) => item.id === route.split("/")[1]);
  if (!action)
    return Response.json(
      { detail: "Unknown synthetic action" },
      { status: 404 },
    );
  if (route.endsWith("/reviews")) {
    if (conflict) {
      conflict = false;
      action.row_version += 1;
      action.current = {
        ...action.current,
        id: "66666666-6666-4666-8666-666666666666",
        version: 2,
        payload: {
          ...action.current.payload,
          body: "Revised text that requires a fresh review.",
        },
      };
      return Response.json(
        { detail: "This proposal changed. Review the current version." },
        { status: 409 },
      );
    }
    if (
      body.expected_version !== action.row_version ||
      body.revision_id !== action.current.id
    )
      return Response.json({ detail: "Stale review" }, { status: 409 });
    action.current.review_state = String(body.decision);
    action.row_version += 1;
    action.state =
      body.decision === "approved" ? "queued" : String(body.decision);
    action.approved_revision_id =
      body.decision === "approved" ? action.current.id : null;
  }
  if (method === "PATCH") {
    action.current = {
      ...action.current,
      id: crypto.randomUUID(),
      payload: body.payload as Record<string, unknown>,
      version: action.current.version + 1,
      reason: String(body.reason),
    };
    action.row_version += 1;
  }
  if (route.endsWith("/reconcile"))
    action.attempt!.reconciliation = {
      state: "unknown",
      reason: "No definitive receipt yet",
    };
  return Response.json(action);
}
