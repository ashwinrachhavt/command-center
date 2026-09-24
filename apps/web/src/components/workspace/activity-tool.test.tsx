import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { ActivityTool } from "./activity-tool";

it("collapses a running tool on completion and opens an error for recovery", () => {
  const { rerender } = render(
    <ActivityTool
      name="document_read"
      state="input-available"
      input={{ version_id: "synthetic" }}
    />,
  );
  const toggle = screen.getByRole("button", {
    name: "Reading document Running",
  });
  fireEvent.click(toggle);
  expect(toggle).toHaveAttribute("aria-expanded", "true");
  rerender(
    <ActivityTool
      name="document_read"
      state="output-available"
      output="Saved text"
      summary="Read the pinned interview brief."
    />,
  );
  expect(
    screen.getByRole("button", { name: "Reading document Completed" }),
  ).toHaveAttribute("aria-expanded", "false");
  expect(screen.queryByText("Saved text")).not.toBeInTheDocument();
  expect(
    screen.queryByText("Read the pinned interview brief."),
  ).not.toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "Reading document Completed" }),
  );
  expect(screen.getByText("Read the pinned interview brief.")).toBeVisible();
  expect(screen.getByText("Saved text")).toBeVisible();
  rerender(
    <ActivityTool
      name="document_read"
      state="output-error"
      errorText="Document unavailable. Retry the extraction."
    />,
  );
  expect(
    screen.getByRole("button", { name: "Reading document Error" }),
  ).toHaveAttribute("aria-expanded", "true");
  expect(
    screen.getByText("Document unavailable. Retry the extraction."),
  ).toBeVisible();
});
