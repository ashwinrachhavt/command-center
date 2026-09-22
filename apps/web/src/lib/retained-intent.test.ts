import { expect, it, vi } from "vitest";

import {
  canStartFreshConnectedRequest,
  RetainedRequestIntent,
  RetainedRequestIntents,
} from "./retained-intent";

it("retains one key for an unchanged request and separates ambiguous signatures", () => {
  vi.spyOn(crypto, "randomUUID")
    .mockReturnValueOnce("11111111-1111-4111-8111-111111111111")
    .mockReturnValueOnce("22222222-2222-4222-8222-222222222222")
    .mockReturnValueOnce("33333333-3333-4333-8333-333333333333")
    .mockReturnValueOnce("44444444-4444-4444-8444-444444444444");
  const intent = new RetainedRequestIntent();

  const first = intent.forRequest("POST", "records/ab", { value: "c" });
  expect(intent.forRequest("POST", "records/ab", { value: "c" })).toBe(first);
  expect(intent.forRequest("POST", "records/a", { value: "bc" }).key).not.toBe(
    first.key,
  );
  expect(intent.forRequest("PATCH", "records/a", { value: "bc" }).key).toBe(
    "33333333-3333-4333-8333-333333333333",
  );
  expect(
    intent.forRequest("PATCH", "records/a", { value: "b", suffix: "c" }).key,
  ).toBe("44444444-4444-4444-8444-444444444444");
});

it("only clears the exact request confirmed by the server", () => {
  const intent = new RetainedRequestIntent();
  const first = intent.forRequest("POST", "records", { title: "First" });
  const second = intent.forRequest("POST", "records", { title: "Second" });
  expect(second.key).not.toBe(first.key);

  intent.confirmRequest("POST", "records", { title: "First" });
  expect(intent.forRequest("POST", "records", { title: "Second" })).toBe(
    second,
  );
  intent.confirmRequest("POST", "records", { title: "Second" });
  const afterSuccess = intent.forRequest("POST", "records", {
    title: "Second",
  });
  expect(afterSuccess.key).not.toBe(second.key);
});

it("retains independent request slots while another request runs", () => {
  const intents = new RetainedRequestIntents();
  const firstA = intents.forRequest("refresh", "POST", "accounts/sync", {});
  const firstB = intents.forRequest("choose:b", "POST", "accounts/b/select", {
    expected_version: 2,
  });

  expect(intents.forRequest("refresh", "POST", "accounts/sync", {})).toBe(
    firstA,
  );
  expect(
    intents.forRequest("choose:b", "POST", "accounts/b/select", {
      expected_version: 2,
    }),
  ).toBe(firstB);
  expect(firstB.key).not.toBe(firstA.key);
});

it("permits a fresh request only after a definitive connected failure", () => {
  expect(
    canStartFreshConnectedRequest({ code: "connected_request_failed" }),
  ).toBe(true);
  expect(
    canStartFreshConnectedRequest({ code: "spending_limit_exceeded" }),
  ).toBe(true);
  expect(
    canStartFreshConnectedRequest({ code: "connected_request_running" }),
  ).toBe(false);
  expect(
    canStartFreshConnectedRequest({
      code: "connected_request_outcome_unknown",
    }),
  ).toBe(false);
  expect(canStartFreshConnectedRequest(new Error("Network failed"))).toBe(
    false,
  );
});
