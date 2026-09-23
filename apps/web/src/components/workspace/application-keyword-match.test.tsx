import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import * as apiModule from "@/lib/api";
import type { ComponentProps } from "react";
import { ApplicationKeywordMatch } from "./application-keyword-match";

const openSource = vi.hoisted(() => vi.fn());
vi.mock("./context", () => ({
  useWorkspaceContext: () => ({ open: openSource }),
}));

type Props = ComponentProps<typeof ApplicationKeywordMatch>;
type Report = apiModule.Schema["ApplicationKeywordMatchRead"];
const initial: Props = {
  actor: "actor-1",
  taskId: "task-1",
  resumeVersionId: "resume-version-3",
  jobVersionId: "job-version-2",
};
const source = (kind: string, version: number) => ({
  artifact_id: `${kind}-artifact`,
  version_id: `${kind}-version-${version}`,
  version,
  title: `${kind} source`,
  archived: false,
});
function report(overrides: Partial<Report> = {}): Report {
  return {
    job: source("job", 2),
    resume: source("resume", 3),
    resume_source: source("extracted", 1),
    job_truncated: false,
    analysis: {
      algorithm: "keyword-coverage.v1",
      mode: "detected",
      score: 67,
      matched_count: 2,
      keyword_count: 3,
      keywords: [
        { term: "Python", matched: true },
        { term: "customer research", matched: true },
        { term: "SQL", matched: false },
      ],
      limit_reached: false,
    },
    ...overrides,
  };
}

function mount(props: Partial<Props> = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const ui = (next: Partial<Props> = {}) => (
    <QueryClientProvider client={client}>
      <ApplicationKeywordMatch {...initial} {...props} {...next} />
    </QueryClientProvider>
  );
  return { ...render(ui()), ui };
}

function editKeywords(value: string) {
  fireEvent.change(screen.getByLabelText("Keywords to check"), {
    target: { value },
  });
}

beforeEach(() => openSource.mockReset());

it("checks only on click with exact saved sources and shows partial coverage with pinned links", async () => {
  const api = vi.spyOn(apiModule, "api").mockResolvedValue(report());
  mount();
  expect(api).not.toHaveBeenCalled();
  expect(
    screen.getByText(/not an employer ATS ranking or an eligibility decision/),
  ).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Check job keywords" }));
  expect(
    await screen.findByText("67% · 2 of 3 keywords found"),
  ).toBeInTheDocument();
  expect(api).toHaveBeenCalledExactlyOnceWith(
    "applications/task-1/keyword-match",
    {
      method: "POST",
      body: {
        resume_version_id: "resume-version-3",
        job_version_id: "job-version-2",
        keywords: null,
      },
    },
  );
  expect(
    within(screen.getByRole("list", { name: "Matched keywords" })).getByText(
      "Python",
    ),
  ).toBeInTheDocument();
  expect(
    within(screen.getByRole("list", { name: "Missing keywords" })).getByText(
      "SQL",
    ),
  ).toBeInTheDocument();

  fireEvent.click(
    screen.getByRole("button", {
      name: "Job description: job source · version 2",
    }),
  );
  expect(openSource).toHaveBeenLastCalledWith("artifacts", "job-artifact", {
    tab: "content",
    versionId: "job-version-2",
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Résumé: resume source · version 3" }),
  );
  expect(openSource).toHaveBeenLastCalledWith("artifacts", "resume-artifact", {
    tab: "content",
    versionId: "resume-version-3",
  });
  fireEvent.click(
    screen.getByRole("button", {
      name: "Résumé text: extracted source · version 1",
    }),
  );
  expect(openSource).toHaveBeenLastCalledWith(
    "artifacts",
    "extracted-artifact",
    { tab: "content", versionId: "extracted-version-1" },
  );
});

it("freezes custom terms and the exact request while pending, then clears the report on editing", async () => {
  let finish!: (result: Report) => void;
  const api = vi.spyOn(apiModule, "api").mockImplementation(
    () =>
      new Promise<Report>((resolve) => {
        finish = resolve;
      }),
  );
  const onPendingChange = vi.fn();
  mount({ onPendingChange });
  editKeywords(" Python,\ncustomer research, SQL ");
  fireEvent.click(screen.getByRole("button", { name: "Check job keywords" }));
  await waitFor(() => expect(onPendingChange).toHaveBeenLastCalledWith(true));
  expect(
    screen.getByRole("button", { name: "Checking keywords…" }),
  ).toBeDisabled();
  expect(screen.getByLabelText("Keywords to check")).toBeDisabled();
  editKeywords("changed while pending");
  expect(screen.getByLabelText("Keywords to check")).toHaveValue(
    " Python,\ncustomer research, SQL ",
  );
  expect(api).toHaveBeenCalledExactlyOnceWith(
    "applications/task-1/keyword-match",
    {
      method: "POST",
      body: {
        resume_version_id: "resume-version-3",
        job_version_id: "job-version-2",
        keywords: ["Python", "customer research", "SQL"],
      },
    },
  );

  finish(report({ analysis: { ...report().analysis, mode: "selected" } }));
  expect(
    await screen.findByText("Checked your selected keywords."),
  ).toBeInTheDocument();
  await waitFor(() => expect(onPendingChange).toHaveBeenLastCalledWith(false));
  editKeywords("new keyword");
  expect(
    screen.queryByText("67% · 2 of 3 keywords found"),
  ).not.toBeInTheDocument();
  expect(api).toHaveBeenCalledTimes(1);
});

it("treats an empty editor as automatic detection and invites custom terms when none are detected", async () => {
  const empty = report({
    analysis: {
      ...report().analysis,
      score: null,
      matched_count: 0,
      keyword_count: 0,
      keywords: [],
    },
  });
  const api = vi.spyOn(apiModule, "api").mockResolvedValue(empty);
  mount();
  editKeywords(" ,\n \n,");
  fireEvent.click(screen.getByRole("button", { name: "Check job keywords" }));
  expect(
    await screen.findByText(
      "No keywords were detected. Add your own list above to check coverage.",
    ),
  ).toBeInTheDocument();
  expect(api).toHaveBeenCalledWith(
    expect.any(String),
    expect.objectContaining({
      body: expect.objectContaining({ keywords: null }),
    }),
  );
  expect(screen.queryByText(/0%/)).not.toBeInTheDocument();
});

it("shows zero coverage, missing terms and shortened-source and detection-limit notes honestly", async () => {
  vi.spyOn(apiModule, "api").mockResolvedValue(
    report({
      job_truncated: true,
      analysis: {
        ...report().analysis,
        score: 0,
        matched_count: 0,
        keyword_count: 1,
        keywords: [{ term: "SQL", matched: false }],
        limit_reached: true,
      },
    }),
  );
  mount();
  fireEvent.click(screen.getByRole("button", { name: "Check job keywords" }));
  expect(
    await screen.findByText("0% · 0 of 1 keywords found"),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("heading", { name: "Matched (0)" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("heading", { name: "Missing (1)" }),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/saved, shortened job description/),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/detected keyword list reached its limit/),
  ).toBeInTheDocument();
});

it("preserves custom terms after failure and retries only when requested", async () => {
  const api = vi
    .spyOn(apiModule, "api")
    .mockRejectedValueOnce(new Error("Résumé text is not ready."))
    .mockResolvedValue(report());
  mount();
  editKeywords("Python, SQL");
  fireEvent.click(screen.getByRole("button", { name: "Check job keywords" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Résumé text is not ready.",
  );
  expect(screen.getByLabelText("Keywords to check")).toHaveValue("Python, SQL");
  expect(api).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "Retry keyword check" }));
  expect(
    await screen.findByText("67% · 2 of 3 keywords found"),
  ).toBeInTheDocument();
  expect(api.mock.calls[1]).toEqual(api.mock.calls[0]);
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it.each(["actor", "taskId", "resumeVersionId", "jobVersionId"] as const)(
  "ignores an outstanding result when %s changes",
  async (field) => {
    let finish!: (result: Report) => void;
    const api = vi.spyOn(apiModule, "api").mockImplementationOnce(
      () =>
        new Promise<Report>((resolve) => {
          finish = resolve;
        }),
    );
    const onPendingChange = vi.fn();
    const { rerender, ui } = mount({ onPendingChange });
    fireEvent.click(screen.getByRole("button", { name: "Check job keywords" }));
    await waitFor(() => expect(api).toHaveBeenCalledTimes(1));
    rerender(ui({ [field]: "another-source" }));
    expect(
      screen.getByRole("button", { name: "Check job keywords" }),
    ).toBeEnabled();
    await act(async () => finish(report()));
    expect(
      screen.queryByText("67% · 2 of 3 keywords found"),
    ).not.toBeInTheDocument();
    expect(onPendingChange).toHaveBeenLastCalledWith(false);
    expect(api).toHaveBeenCalledTimes(1);
  },
);

it.each(["actor", "taskId", "resumeVersionId", "jobVersionId"] as const)(
  "clears a completed report when %s changes",
  async (field) => {
    const api = vi.spyOn(apiModule, "api").mockResolvedValue(report());
    const { rerender, ui } = mount();
    fireEvent.click(screen.getByRole("button", { name: "Check job keywords" }));
    await screen.findByText("67% · 2 of 3 keywords found");
    rerender(ui({ [field]: "another-source" }));
    expect(
      screen.queryByText("67% · 2 of 3 keywords found"),
    ).not.toBeInTheDocument();
    expect(api).toHaveBeenCalledTimes(1);
  },
);

it("rejects a report for a different source version", async () => {
  vi.spyOn(apiModule, "api").mockResolvedValue(
    report({ resume: source("resume", 4) }),
  );
  mount();
  fireEvent.click(screen.getByRole("button", { name: "Check job keywords" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "The report did not match the selected source versions.",
  );
  expect(
    screen.queryByText("67% · 2 of 3 keywords found"),
  ).not.toBeInTheDocument();
});

it.each([
  {
    props: { resumeVersionId: undefined },
    message: "Choose a saved résumé to check keyword coverage.",
  },
  {
    props: { jobVersionId: undefined },
    message: "Save a job-description checkpoint to check keyword coverage.",
  },
  {
    props: { resumeVersionId: undefined, jobVersionId: undefined },
    message:
      "Save a job description and choose a résumé to check keyword coverage.",
  },
])("explains missing prerequisites: $message", ({ props, message }) => {
  const api = vi.spyOn(apiModule, "api");
  mount(props);
  expect(screen.getByText(message)).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Check job keywords" }),
  ).toBeDisabled();
  expect(api).not.toHaveBeenCalled();
});

it("validates keyword count and length without sending or truncating terms", () => {
  const api = vi.spyOn(apiModule, "api");
  mount();
  editKeywords(Array.from({ length: 51 }, (_, i) => `keyword-${i}`).join(","));
  expect(screen.getByRole("alert")).toHaveTextContent("Use up to 50 keywords.");
  expect(
    screen.getByRole("button", { name: "Check job keywords" }),
  ).toBeDisabled();
  editKeywords("a".repeat(81));
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Keep each keyword to 80 characters or fewer.",
  );
  expect(
    screen.getByRole("button", { name: "Check job keywords" }),
  ).toBeDisabled();
  expect(screen.getByLabelText("Keywords to check")).toHaveValue(
    "a".repeat(81),
  );
  editKeywords("a".repeat(80));
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Check job keywords" }),
  ).toBeEnabled();
  expect(api).not.toHaveBeenCalled();
});
