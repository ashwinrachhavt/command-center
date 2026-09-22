import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { BrowserPage } from "./browser";

it("keeps device and command history visible through local refresh failures", async () => {
  const deviceReads = [
    Response.json([
      {
        id: "device-1",
        name: "Synthetic browser",
        paired_at: "2026-09-21T10:00:00Z",
        last_seen_at: "2026-09-21T10:01:00Z",
        revoked_at: null,
      },
    ]),
    Response.json({ detail: "Devices refresh failed" }, { status: 409 }),
    Response.json([]),
  ];
  const commandReads = [
    Response.json([
      {
        id: "command-1",
        state: "pending",
        created_at: "2026-09-21T10:02:00Z",
        fields: { name: "Synthetic Person" },
        uploads: {},
      },
    ]),
    Response.json({ detail: "Commands refresh failed" }, { status: 409 }),
    Response.json([]),
  ];
  vi.spyOn(global, "fetch").mockImplementation((input, init) => {
    const route = String(input);
    if (init?.method !== "GET")
      throw new Error(`Unexpected browser write: ${route}`);
    if (route.endsWith("/browser/devices"))
      return Promise.resolve(deviceReads.shift() ?? Response.json([]));
    if (route.endsWith("/browser/commands"))
      return Promise.resolve(commandReads.shift() ?? Response.json([]));
    if (route.endsWith("/browser/snapshots"))
      return Promise.resolve(Response.json([]));
    if (route.endsWith("/browser/resumes"))
      return Promise.resolve(
        Response.json({ default_version_id: null, items: [] }),
      );
    if (route.endsWith("/opportunities?limit=100&offset=0"))
      return Promise.resolve(
        Response.json({ items: [], total: 0, limit: 100, offset: 0 }),
      );
    throw new Error(`Unexpected browser request: ${route}`);
  });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <BrowserPage />
    </QueryClientProvider>,
  );
  expect(await screen.findByText("Synthetic browser")).toBeVisible();
  expect(await screen.findByText(/1 answers/)).toBeVisible();

  await Promise.all([
    client.invalidateQueries({ queryKey: ["devices"] }),
    client.invalidateQueries({ queryKey: ["browser-commands"] }),
  ]);

  const deviceError = await screen.findByText("Devices refresh failed");
  const commandError = await screen.findByText("Commands refresh failed");
  expect(screen.getByText("Synthetic browser")).toBeVisible();
  expect(screen.getByText(/1 answers/)).toBeVisible();
  fireEvent.click(
    within(deviceError.closest('[role="alert"]')!).getByRole("button", {
      name: "Try again",
    }),
  );
  fireEvent.click(
    within(commandError.closest('[role="alert"]')!).getByRole("button", {
      name: "Try again",
    }),
  );
  expect(await screen.findByText("No browser paired yet.")).toBeVisible();
  expect(await screen.findByText("No proposals yet.")).toBeVisible();
});
