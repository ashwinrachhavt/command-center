import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import type { Schema, WorkspaceRecord } from "@/lib/api";
import { ArtifactContent } from "./record-detail";

const artifact = {
  id: "artifact-1",
  row_version: 1,
  created_at: "2026-09-21T10:00:00Z",
  updated_at: "2026-09-21T10:00:00Z",
  title: "Synthetic artifact",
  kind: "research",
  sensitivity: "private",
  archived_at: null,
  latest_version: 1,
} as WorkspaceRecord;
const v1: Schema["VersionRead"] = {
  id: "version-1",
  artifact_id: "artifact-1",
  version: 1,
  payload: { text: "Version one content" },
  content_sha256: "sha-version-one",
  input_version_ids: [],
  created_at: "2026-09-21T10:00:00Z",
};
const v2: Schema["VersionRead"] = {
  ...v1,
  id: "version-2",
  version: 2,
  payload: { text: "Version two content" },
  content_sha256: "sha-version-two",
  created_at: "2026-09-21T11:00:00Z",
};

function mount(
  reviewResponses: Array<Response | Promise<Response>> = [
    Response.json({ id: "review-1" }),
  ],
  reviewReads: Response[] = [Response.json([])],
) {
  const posts: [RequestInfo | URL, RequestInit | undefined][] = [];
  vi.spyOn(global, "fetch").mockImplementation(async (input, init) => {
    const route = String(input);
    if (
      init?.method === "GET" &&
      route.endsWith("/artifacts/artifact-1/versions")
    )
      return Response.json([v1]);
    if (init?.method === "GET" && route.endsWith("/versions/version-1/reviews"))
      return reviewReads.shift() ?? Response.json([]);
    if (init?.method === "GET" && route.endsWith("/versions/version-2/reviews"))
      return Response.json([]);
    if (init?.method === "POST") {
      posts.push([input, init]);
      return reviewResponses.shift() ?? Response.json({ id: "review-2" });
    }
    throw new Error(`Unexpected synthetic request: ${route}`);
  });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <ArtifactContent record={artifact} />
    </QueryClientProvider>,
  );
  return { client, posts };
}

function postBody(call: [RequestInfo | URL, RequestInit | undefined]) {
  return JSON.parse(String(call[1]?.body));
}

function postKey(call: [RequestInfo | URL, RequestInit | undefined]) {
  return new Headers(call[1]?.headers).get("Idempotency-Key");
}

it("pins the displayed version, content hash, reason, and submitted review through refetch", async () => {
  const { client, posts } = mount();
  await screen.findByText("Version one content", {}, { timeout: 3000 });
  fireEvent.change(screen.getByLabelText("Review reason"), {
    target: { value: "Checked exact version one" },
  });

  client.setQueryData(["versions", "artifact-1"], [v2, v1]);
  await screen.findByText(/newer version 2 is available/i);
  expect(screen.getByText("Version one content")).toBeVisible();
  expect(screen.getByText(/sha-version-one/i)).toBeVisible();
  expect(screen.getByLabelText("Review reason")).toHaveValue(
    "Checked exact version one",
  );

  fireEvent.click(screen.getByRole("button", { name: "Record review" }));
  await waitFor(() => expect(posts).toHaveLength(1));
  expect(String(posts[0][0])).toContain("/versions/version-1/reviews");
  expect(postBody(posts[0])).toEqual({
    decision: "approved",
    reason: "Checked exact version one",
  });
});

it("requires explicit discard before moving an unsaved review to newer content", async () => {
  const { client } = mount();
  await screen.findByText("Version one content");
  fireEvent.change(screen.getByLabelText("Review reason"), {
    target: { value: "Reason belongs to version one" },
  });
  client.setQueryData(["versions", "artifact-1"], [v2, v1]);

  fireEvent.click(
    await screen.findByRole("button", { name: "Review version 2" }),
  );
  expect(
    screen.getByText(/unsaved review belongs to version 1/i),
  ).toBeVisible();
  expect(screen.getByText("Version one content")).toBeVisible();
  expect(screen.getByLabelText("Review reason")).toHaveValue(
    "Reason belongs to version one",
  );

  fireEvent.click(
    screen.getByRole("button", { name: "Discard review and switch" }),
  );
  await screen.findByText("Version two content");
  expect(screen.getByLabelText("Review reason")).toHaveValue("");
  expect(screen.getByText(/sha-version-two/i)).toBeVisible();
});

it("retains the immutable artifact review intent across a manual retry", async () => {
  const { posts } = mount([
    Response.json({ detail: "Review conflict" }, { status: 409 }),
    Response.json({ id: "review-1" }),
  ]);
  await screen.findByText("Version one content");
  fireEvent.change(screen.getByLabelText("Review reason"), {
    target: { value: "Retry this exact review" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Record review" }));
  await screen.findByText("Review conflict");
  fireEvent.click(screen.getByRole("button", { name: "Record review" }));
  await waitFor(() => expect(posts).toHaveLength(2));

  expect(String(posts[0][0])).toBe(String(posts[1][0]));
  expect(postBody(posts[0])).toEqual(postBody(posts[1]));
  expect(postKey(posts[0])).toBe(postKey(posts[1]));
});

it("preserves a newer review draft when an older submitted snapshot succeeds", async () => {
  let finish!: (response: Response) => void;
  const pending = new Promise<Response>((resolve) => {
    finish = resolve;
  });
  const { posts } = mount([pending, Response.json({ id: "review-2" })]);
  await screen.findByText("Version one content");
  fireEvent.change(screen.getByLabelText("Review reason"), {
    target: { value: "Submitted reason" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Record review" }));
  await waitFor(() => expect(posts).toHaveLength(1));

  fireEvent.change(screen.getByLabelText("Review reason"), {
    target: { value: "New reason written during save" },
  });
  finish(Response.json({ id: "review-1" }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Record review" })).toBeEnabled(),
  );
  expect(screen.getByLabelText("Review reason")).toHaveValue(
    "New reason written during save",
  );
  expect(postBody(posts[0])).toEqual({
    decision: "approved",
    reason: "Submitted reason",
  });

  fireEvent.click(screen.getByRole("button", { name: "Record review" }));
  await waitFor(() => expect(posts).toHaveLength(2));
  expect(postBody(posts[1])).toEqual({
    decision: "approved",
    reason: "New reason written during save",
  });
  expect(postKey(posts[1])).not.toBe(postKey(posts[0]));
});

it("keeps cached review history visible through a failed refresh and local retry", async () => {
  const priorReview: Schema["ReviewRead"] = {
    id: "review-prior",
    artifact_version_id: v1.id,
    decision: "approved",
    reason: "Previously checked",
    created_at: "2026-09-21T10:30:00Z",
  };
  const { client } = mount(undefined, [
    Response.json([priorReview]),
    Response.json({ detail: "Review refresh failed" }, { status: 409 }),
    Response.json([]),
  ]);
  expect(await screen.findByText("Previously checked")).toBeVisible();

  await client.invalidateQueries({ queryKey: ["reviews", v1.id] });

  expect(await screen.findByText("Review refresh failed")).toBeVisible();
  expect(screen.getByText("Previously checked")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(
    await screen.findByText("No reviews recorded for this version."),
  ).toBeVisible();
});

it("does not discard version edits made while an earlier append is saving", async () => {
  let finish!: (response: Response) => void;
  const pending = new Promise<Response>((resolve) => {
    finish = resolve;
  });
  const { posts } = mount([pending]);
  await screen.findByText("Version one content");
  fireEvent.click(screen.getByRole("button", { name: "New version" }));
  fireEvent.change(screen.getByLabelText("New version content"), {
    target: { value: "Submitted version content" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save version" }));
  await waitFor(() => expect(posts).toHaveLength(1));

  fireEvent.change(screen.getByLabelText("New version content"), {
    target: { value: "Newer edit made during save" },
  });
  finish(Response.json(v2));

  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Save version" })).toBeEnabled(),
  );
  expect(screen.getByLabelText("New version content")).toHaveValue(
    "Newer edit made during save",
  );
  expect(postBody(posts[0])).toMatchObject({
    based_on_version_id: v1.id,
    text: "Submitted version content",
  });
});
