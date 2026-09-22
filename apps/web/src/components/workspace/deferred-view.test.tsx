import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { expect, it, vi } from "vitest";
import { deferView } from "./deferred-view";

function LoadedView() {
  const [count, setCount] = useState(0);
  return (
    <button onClick={() => setCount(count + 1)}>Loaded view {count}</button>
  );
}

it("loads only when shown and preserves loaded state through ordinary rerenders", async () => {
  let finish!: (module: { default: typeof LoadedView }) => void;
  const load = vi.fn(
    () =>
      new Promise<{ default: typeof LoadedView }>((resolve) => {
        finish = resolve;
      }),
  );
  const Deferred = deferView(load, "research");
  const { rerender } = render(<div>Ordinary records</div>);
  expect(load).not.toHaveBeenCalled();
  rerender(<Deferred />);
  expect(screen.getByRole("status")).toHaveTextContent("Loading research");
  await act(async () => {
    finish({ default: LoadedView });
  });
  await userEvent.click(screen.getByRole("button", { name: "Loaded view 0" }));
  rerender(<Deferred />);
  expect(
    screen.getByRole("button", { name: "Loaded view 1" }),
  ).toBeInTheDocument();
  expect(load).toHaveBeenCalledTimes(1);
});

it("retries a failed import without discarding surrounding user input", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  const load = vi
    .fn()
    .mockRejectedValueOnce(new Error("Synthetic unavailable feature"))
    .mockResolvedValueOnce({ default: LoadedView });
  const Deferred = deferView(load, "research");
  render(
    <>
      <input aria-label="Draft" />
      <Deferred />
    </>,
  );
  await userEvent.type(screen.getByLabelText("Draft"), "Keep these notes");
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Could not load research",
  );
  await userEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(
    await screen.findByRole("button", { name: "Loaded view 0" }),
  ).toBeInTheDocument();
  expect(screen.getByLabelText("Draft")).toHaveValue("Keep these notes");
  expect(load).toHaveBeenCalledTimes(2);
});
