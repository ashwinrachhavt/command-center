import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import {
  EmailDeliveryFields,
  emailDelivery,
  emailTiming,
} from "./email-delivery";
import * as apiModule from "@/lib/api";

it("saves an aware instant from local time and rejects a past or absent date", () => {
  const time = {
    ...emailTiming(),
    mode: "at" as const,
    localTime: "2035-02-03T09:45",
  };
  const delivery = emailDelivery(time);
  expect(delivery).toEqual({
    mode: "at",
    send_at: new Date("2035-02-03T09:45").toISOString(),
  });
  expect(emailTiming(delivery)).toEqual(time);
  expect(() =>
    emailDelivery({ ...time, localTime: "2020-01-01T10:00" }),
  ).toThrow("future");
  expect(() => emailDelivery({ ...time, localTime: "" })).toThrow("valid");
  expect(emailDelivery(emailTiming())).toBeNull();
});

it("requires a specific confirmed send and an explicit cadence", () => {
  const time = {
    ...emailTiming(),
    mode: "after_send" as const,
    afterActionId: "sent-action",
    days: "4",
  };
  expect(emailDelivery(time)).toEqual({
    mode: "after_send",
    after_action_id: "sent-action",
    delay_days: 4,
  });
  for (const days of ["", "0", "1.5", "91"])
    expect(() => emailDelivery({ ...time, days })).toThrow();
  expect(() => emailDelivery({ ...time, afterActionId: "" })).toThrow();
});

it("loads only sent emails for the selected recipient and account, then previews the cadence date", async () => {
  const api = vi.spyOn(apiModule, "api").mockResolvedValue({
    items: [
      {
        id: "sent-action",
        current: { payload: { subject: "Synthetic first email" } },
        attempt: { completed_at: "2035-02-03T12:00:00Z" },
      },
    ],
    total: 1,
  });
  function Harness() {
    const [timing, setTiming] = useState(emailTiming());
    return (
      <EmailDeliveryFields
        timing={timing}
        onChange={setTiming}
        recipient="recipient@example.com"
        accountId="selected-account"
      />
    );
  }
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <Harness />
    </QueryClientProvider>,
  );
  expect(api).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("When to send"), {
    target: { value: "after_send" },
  });
  await waitFor(() =>
    expect(
      screen.getByRole("option", { name: /Synthetic first email/ }),
    ).toBeVisible(),
  );
  expect(api.mock.calls[0][0]).toContain("state=succeeded");
  expect(api.mock.calls[0][0]).toContain("account_id=selected-account");
  expect(api.mock.calls[0][0]).toContain("recipient=recipient%40example.com");
  fireEvent.change(screen.getByLabelText("Previous sent email"), {
    target: { value: "sent-action" },
  });
  fireEvent.change(screen.getByLabelText("Days after that email"), {
    target: { value: "3" },
  });
  expect(screen.getByText(/Scheduled for/)).toBeVisible();
  expect(screen.getByText(/every email needs its own review/)).toBeVisible();
  expect(api).toHaveBeenCalledTimes(1);
});
