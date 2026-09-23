import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { OpportunityResearch } from "./opportunity-research";

it("opens pasted lead evidence through its saved version without creating an external URN link", async () => {
  vi.spyOn(global, "fetch").mockResolvedValue(
    Response.json({
      items: [
        {
          id: "source-1",
          artifact_id: "artifact-1",
          version_id: "version-1",
          version: 1,
          title: "Pasted source",
          provider: "pasted_text",
          url: "urn:command-center:pasted:synthetic",
          excerpt: "Synthetic private text",
          retrieved_at: "2026-09-23T00:00:00Z",
        },
      ],
      total: 1,
    }),
  );
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <OpportunityResearch
        opportunityId="opportunity-1"
        onOpenConversation={() => {}}
      />
    </QueryClientProvider>,
  );
  expect(
    await screen.findByRole("button", { name: "View saved version 1" }),
  ).toBeVisible();
  expect(screen.getByText("Pasted or saved source")).toBeVisible();
  expect(
    screen.queryByRole("link", { name: "Public page" }),
  ).not.toBeInTheDocument();
});
