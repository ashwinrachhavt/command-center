import { act, render, screen } from "@testing-library/react";
import { useQuery } from "@tanstack/react-query";
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
