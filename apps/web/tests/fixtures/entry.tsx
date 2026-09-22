import { createRoot } from "react-dom/client";
import { Providers } from "../../src/components/providers";
import { WorkspaceShell } from "../../src/components/workspace/shell";
import { Records } from "../../src/components/workspace/records";
import { Overview } from "../../src/components/workspace/overview";
import { Agents } from "../../src/components/workspace/agents";
import { installNavigation, usePathname } from "./navigation";
import "../../src/app/globals.css";

installNavigation();
const base = {
  row_version: 1,
  created_at: "2026-09-21T10:00:00Z",
  updated_at: "2026-09-21T10:00:00Z",
  archived_at: null,
};
const company = {
  ...base,
  id: "company-1",
  name: "Northstar",
  industry: "Developer tools",
  location: "San Francisco",
  website: "https://example.com",
  notes: "Synthetic company for interface review.",
};
const contact = {
  ...base,
  id: "contact-1",
  name: "Alex Morgan",
  title: "Engineering lead",
  company_id: company.id,
  email: "alex@example.com",
  relationship: "warm",
  notes: "Discuss the platform team and interview process.",
};
const opportunities = [
  {
    ...base,
    id: "opportunity-1",
    title: "Staff Product Engineer",
    company_id: company.id,
    contact_id: contact.id,
    stage: "interviewing",
    priority: 2,
    notes:
      "Build thoughtful tools for small teams. Follow up after the technical conversation.",
  },
  {
    ...base,
    id: "opportunity-2",
    title: "Senior Frontend Engineer",
    company_id: company.id,
    stage: "researching",
    priority: 1,
    notes: "Review the product and speak to the team.",
  },
];
const tasks = [
  {
    ...base,
    id: "task-1",
    title: "Prepare for the technical conversation",
    opportunity_id: opportunities[0].id,
    state: "open",
    priority: 2,
    due_date: "2026-09-24",
  },
];
const empty = { items: [], total: 0 };
const rows: Record<string, Record<string, unknown>[]> = {
  companies: [company],
  contacts: [contact],
  opportunities,
  tasks,
  artifacts: [],
  jobs: [],
};
const fixtureFetch: typeof fetch = async (input, init) => {
  const url = new URL(String(input), location.origin);
  if (!url.pathname.startsWith("/api/backend/"))
    throw new Error("Only fixture API requests are supported");
  const route = url.pathname.replace("/api/backend/", "");
  let payload: unknown = empty;
  const [resource, id] = route.split("/");
  if (rows[resource]) {
    if (!id && init?.method === "POST") {
      const created = {
        ...base,
        ...JSON.parse(String(init.body)),
        id: crypto.randomUUID(),
      };
      rows[resource].push(created);
      return Response.json(created);
    }
    if (id) {
      const record = rows[resource].find((row) => row.id === id);
      if (!record)
        return Response.json({ detail: "Record not found" }, { status: 404 });
      if (init?.method === "PATCH")
        Object.assign(record, JSON.parse(String(init.body)), {
          row_version: Number(record.row_version) + 1,
        });
      payload = record;
    } else {
      const q = url.searchParams.get("q")?.toLowerCase() ?? "";
      const stage = url.searchParams.get("stage");
      const matches = rows[resource].filter(
        (row) =>
          String(row.name ?? row.title)
            .toLowerCase()
            .includes(q) &&
          (!stage || row.stage === stage),
      );
      payload = { items: matches, total: matches.length };
    }
  }
  if (route === "company-labels") payload = [company];
  if (route === "me") payload = { display_name: "Alex’s workspace" };
  if (route === "dashboard")
    payload = {
      counts: { opportunities: 2, contacts: 1, companies: 1, tasks: 1 },
      stages: { researching: 1, interviewing: 1 },
      tasks,
    };
  if (route === "agents/profiles")
    payload = [
      {
        id: "research",
        name: "Research",
        description: "Research companies and roles",
        model: "Synthetic preview",
        tools: [],
        skills: [],
      },
    ];
  if (route === "agent-runs")
    payload = {
      items: [
        {
          ...base,
          id: "run-1",
          profile: "research",
          title: "Northstar research",
          prompt: "Summarize this synthetic company.",
          state: "completed",
          output:
            "## Company brief\n\n**Northstar** builds developer tools.\n\n- Ask about the platform roadmap.\n- Review team responsibilities.",
          error: null,
        },
      ],
      total: 1,
    };
  if (route === "agent-runs/run-1/steps") payload = [];
  if (route === "integrations") payload = { openai_configured: true };
  return Response.json(payload);
};
window.fetch = fixtureFetch;
function Preview() {
  const path = usePathname();
  return (
    <Providers>
      <WorkspaceShell>
        {path === "/" ? (
          <Overview />
        ) : path === "/agents" ? (
          <Agents />
        ) : (
          <Records resource="opportunities" />
        )}
      </WorkspaceShell>
    </Providers>
  );
}
createRoot(document.getElementById("root")!).render(<Preview />);
