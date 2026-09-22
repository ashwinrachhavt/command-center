import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import type { Profile } from "@/lib/api";
import { ProfileForm, Settings } from "./settings";

vi.mock("./profile-facts", () => ({ ProfileFacts: () => null }));
vi.mock("./connected-accounts", () => ({ ConnectedAccounts: () => null }));
vi.mock("./spending", () => ({ SpendingSettings: () => null }));

const profile = (rowVersion: number, displayName = "Original profile") => ({
  actor_id: "11111111-1111-4111-8111-111111111111",
  display_name: displayName,
  headline: "Original headline",
  location: "Original location",
  timezone: "America/Los_Angeles",
  row_version: rowVersion,
});

function mount(value: Profile) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const ui = (next: Profile) => (
    <QueryClientProvider client={client}>
      <ProfileForm profile={next} />
    </QueryClientProvider>
  );
  return { ...render(ui(value)), client, ui };
}

function body(call: unknown[]) {
  return JSON.parse(String((call[1] as RequestInit).body));
}

function receipt(call: unknown[]) {
  return new Headers((call[1] as RequestInit).headers).get("Idempotency-Key");
}

it("preserves a dirty profile and its opening revision through a refetch", async () => {
  const fetch = vi
    .spyOn(global, "fetch")
    .mockResolvedValue(Response.json(profile(3, "Draft name")));
  const { rerender, ui } = mount(profile(1));
  fireEvent.change(screen.getByLabelText("Workspace name"), {
    target: { value: "Draft name" },
  });

  rerender(ui(profile(2, "Server name")));
  expect(screen.getByLabelText("Workspace name")).toHaveValue("Draft name");
  fireEvent.click(screen.getByRole("button", { name: "Save profile" }));

  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
  expect(body(fetch.mock.calls[0])).toMatchObject({
    display_name: "Draft name",
    expected_version: 1,
  });
});

it("keeps edits made during save and advances the pinned revision", async () => {
  let finish!: (response: Response) => void;
  const fetch = vi
    .spyOn(global, "fetch")
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    )
    .mockResolvedValue(Response.json(profile(3, "Newer draft")));
  mount(profile(1));
  fireEvent.change(screen.getByLabelText("Workspace name"), {
    target: { value: "Submitted draft" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save profile" }));
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));

  fireEvent.change(screen.getByLabelText("Workspace name"), {
    target: { value: "Newer draft" },
  });
  finish(Response.json(profile(2, "Submitted draft")));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Save profile" })).toBeEnabled(),
  );
  expect(screen.getByLabelText("Workspace name")).toHaveValue("Newer draft");

  fireEvent.click(screen.getByRole("button", { name: "Save profile" }));
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  expect(body(fetch.mock.calls[1])).toMatchObject({
    display_name: "Newer draft",
    expected_version: 2,
  });
});

it("retains the write intent on retry and offers explicit conflict reload choices", async () => {
  const latest = profile(2, "Server name");
  const fetch = vi
    .spyOn(global, "fetch")
    .mockResolvedValueOnce(
      Response.json(
        { detail: "Profile changed. Reload before saving." },
        { status: 409 },
      ),
    )
    .mockResolvedValueOnce(
      Response.json(
        { detail: "Profile changed. Reload before saving." },
        { status: 409 },
      ),
    )
    .mockResolvedValueOnce(Response.json(latest));
  mount(profile(1));
  fireEvent.change(screen.getByLabelText("Workspace name"), {
    target: { value: "Draft name" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save profile" }));
  await screen.findByText("Profile changed. Reload before saving.");
  expect(
    screen.getByRole("button", { name: "Reload latest and keep draft" }),
  ).toBeVisible();
  expect(
    screen.getByRole("button", { name: "Discard draft and reload" }),
  ).toBeVisible();

  fireEvent.click(screen.getByRole("button", { name: "Save profile" }));
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Save profile" })).toBeEnabled(),
  );
  expect(receipt(fetch.mock.calls[1])).toBe(receipt(fetch.mock.calls[0]));
  expect(body(fetch.mock.calls[1])).toEqual(body(fetch.mock.calls[0]));

  fireEvent.change(screen.getByLabelText("Workspace name"), {
    target: { value: "Another local draft" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Discard draft and reload" }),
  );
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(3));
  await waitFor(() =>
    expect(screen.getByLabelText("Workspace name")).toHaveValue("Server name"),
  );
});

it("keeps the mounted settings draft when a background profile refetch fails", async () => {
  let profileReads = 0;
  const fetch = vi.spyOn(global, "fetch").mockImplementation((input) => {
    const route = String(input);
    if (route.endsWith("/me")) {
      profileReads += 1;
      return Promise.resolve(
        profileReads === 1
          ? Response.json(profile(1))
          : Response.json(
              { detail: "Profile refresh unavailable" },
              { status: 503 },
            ),
      );
    }
    if (route.endsWith("/integrations")) {
      return Promise.resolve(
        Response.json({
          auth: "clerk",
          model_providers: {
            openai: false,
            gemini: false,
            mistral: false,
            cohere: false,
          },
          openai_configured: false,
          composio_configured: false,
          composio_toolkits: [],
          services: [],
        }),
      );
    }
    throw new Error(`Unexpected settings request: ${route}`);
  });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <Settings />
    </QueryClientProvider>,
  );
  const name = await screen.findByLabelText("Workspace name");
  fireEvent.change(name, { target: { value: "Unsaved workspace draft" } });

  await client.invalidateQueries({ queryKey: ["me"] });

  expect(await screen.findByText("Profile refresh unavailable")).toBeVisible();
  expect(screen.getByLabelText("Workspace name")).toHaveValue(
    "Unsaved workspace draft",
  );
  expect(screen.getByRole("button", { name: "Try again" })).toBeVisible();
  expect(fetch).toHaveBeenCalled();
});
