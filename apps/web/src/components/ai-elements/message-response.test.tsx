import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { MessageResponse } from "./message-response";

vi.mock("@streamdown/cjk", () => ({ cjk: {} }));
vi.mock("@streamdown/code", () => ({ code: {} }));
vi.mock("@streamdown/math", () => ({ math: {} }));
vi.mock("@streamdown/mermaid", () => ({ mermaid: {} }));
vi.mock("streamdown", () => ({
  Streamdown: ({
    children,
    mode,
    skipHtml,
  }: {
    children: string;
    mode: string;
    skipHtml: boolean;
  }) => (
    <div data-mode={mode} data-skip-html={String(skipHtml)}>
      {children}
    </div>
  ),
}));

it("applies rendering and safety changes even when the response text is unchanged", () => {
  const view = render(
    <MessageResponse mode="streaming" skipHtml={false}>
      Same saved text
    </MessageResponse>,
  );
  view.rerender(
    <MessageResponse mode="static" skipHtml>
      Same saved text
    </MessageResponse>,
  );
  expect(screen.getByText("Same saved text")).toHaveAttribute(
    "data-mode",
    "static",
  );
  expect(screen.getByText("Same saved text")).toHaveAttribute(
    "data-skip-html",
    "true",
  );
});
