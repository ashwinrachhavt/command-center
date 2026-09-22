import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { Providers } from "./providers";

const auth = vi.hoisted(() => ({
  isLoaded: true,
  userId: "actor-a" as string | null,
}));
vi.mock("@clerk/nextjs", () => ({ useAuth: () => auth }));
beforeEach(() => {
  auth.isLoaded = true;
  auth.userId = "actor-a";
});

it("withholds private content until identity resolves", () => {
  auth.isLoaded = false;
  render(
    <Providers>
      <p>Private workspace</p>
    </Providers>,
  );
  expect(screen.queryByText("Private workspace")).not.toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("Loading workspace");
});

it("replaces the query cache and local UI on identity change, isolating late results", async () => {
  let finishA!: (value: string) => void;
  function Probe() {
    const actor = auth.userId;
    const query = useQuery({
      queryKey: ["same-record"],
      queryFn: () =>
        actor === "actor-a"
          ? new Promise<string>((resolve) => {
              finishA = resolve;
            })
          : Promise.resolve("Actor B record"),
    });
    return (
      <>
        <p>{query.data ?? "Loading record"}</p>
        <input aria-label="Private draft" defaultValue="" />
      </>
    );
  }
  const { rerender } = render(
    <Providers>
      <Probe />
    </Providers>,
  );
  const input = screen.getByLabelText("Private draft") as HTMLInputElement;
  input.value = "Actor A draft";
  auth.userId = "actor-b";
  rerender(
    <Providers>
      <Probe />
    </Providers>,
  );
  await screen.findByText("Actor B record");
  expect(screen.getByLabelText("Private draft")).toHaveValue("");
  await act(async () => {
    finishA("Actor A late result");
  });
  expect(screen.queryByText("Actor A late result")).not.toBeInTheDocument();
  expect(screen.getByText("Actor B record")).toBeInTheDocument();
});

it("retains cached data and local drafts for an unchanged identity", async () => {
  const read = vi.fn().mockResolvedValue("Actor A record");
  function Probe() {
    const query = useQuery({ queryKey: ["private-record"], queryFn: read });
    const [draft, setDraft] = useState("");
    return (
      <>
        <p>{query.data ?? "Loading record"}</p>
        <input
          aria-label="Private draft"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
      </>
    );
  }
  const { rerender } = render(
    <Providers>
      <Probe />
    </Providers>,
  );
  await screen.findByText("Actor A record");
  await userEvent.type(
    screen.getByLabelText("Private draft"),
    "Keep this draft",
  );
  rerender(
    <Providers>
      <Probe />
    </Providers>,
  );
  expect(screen.getByText("Actor A record")).toBeInTheDocument();
  expect(screen.getByLabelText("Private draft")).toHaveValue("Keep this draft");
  expect(read).toHaveBeenCalledTimes(1);
});

it("retires private state on sign-out and fetches fresh data after signing in again", async () => {
  const read = vi
    .fn()
    .mockResolvedValueOnce("Actor A old record")
    .mockResolvedValueOnce("Actor A fresh record");
  function Probe() {
    const query = useQuery({
      queryKey: ["private-record"],
      queryFn: read,
      enabled: !!auth.userId,
    });
    const [draft, setDraft] = useState("");
    return (
      <>
        <p>{query.data ?? "No private record"}</p>
        <input
          aria-label="Private draft"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
      </>
    );
  }
  const { rerender } = render(
    <Providers>
      <Probe />
    </Providers>,
  );
  await screen.findByText("Actor A old record");
  await userEvent.type(
    screen.getByLabelText("Private draft"),
    "Old private draft",
  );
  auth.userId = null;
  rerender(
    <Providers>
      <Probe />
    </Providers>,
  );
  expect(screen.queryByText("Actor A old record")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Private draft")).toHaveValue("");
  expect(read).toHaveBeenCalledTimes(1);
  auth.userId = "actor-a";
  rerender(
    <Providers>
      <Probe />
    </Providers>,
  );
  await screen.findByText("Actor A fresh record");
  expect(screen.queryByText("Actor A old record")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Private draft")).toHaveValue("");
  expect(read).toHaveBeenCalledTimes(2);
});
