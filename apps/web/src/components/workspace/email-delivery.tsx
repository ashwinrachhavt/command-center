"use client";

import { useQuery } from "@tanstack/react-query";
import { Input } from "@/components/ui/input";
import { api, type Page, type Schema } from "@/lib/api";

export type EmailTiming = {
  mode: "now" | "at" | "after_send";
  localTime: string;
  afterActionId: string;
  days: string;
};

function localDateTime(value: Date): string {
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}T${pad(value.getHours())}:${pad(value.getMinutes())}`;
}

export function emailTiming(
  delivery?: Schema["EmailDelivery"] | null,
): EmailTiming {
  return {
    mode: delivery?.mode ?? "now",
    localTime: delivery?.send_at
      ? localDateTime(new Date(delivery.send_at))
      : "",
    afterActionId: delivery?.after_action_id ?? "",
    days: delivery?.delay_days ? String(delivery.delay_days) : "",
  };
}

export function emailDelivery(
  timing?: EmailTiming,
): Schema["EmailDelivery"] | null {
  if (!timing || timing.mode === "now") return null;
  if (timing.mode === "at") {
    const date = new Date(timing.localTime);
    if (
      !Number.isFinite(date.getTime()) ||
      localDateTime(date) !== timing.localTime
    )
      throw new Error("Choose a valid local date and time.");
    if (date.getTime() <= Date.now())
      throw new Error("Choose a future send time.");
    return { mode: "at", send_at: date.toISOString() };
  }
  const days = Number(timing.days);
  if (!timing.afterActionId || !Number.isInteger(days) || days < 1 || days > 90)
    throw new Error("Choose a sent email and an interval from 1 to 90 days.");
  return {
    mode: "after_send",
    after_action_id: timing.afterActionId,
    delay_days: days,
  };
}

export function sendTimeLabel(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "long",
  }).format(new Date(value));
}

export function EmailDeliveryFields({
  timing,
  onChange,
  recipient,
  accountId,
}: {
  timing: EmailTiming;
  onChange: (timing: EmailTiming) => void;
  recipient: string;
  accountId: string;
}) {
  const previous = useQuery({
    queryKey: ["reviewed-actions", "cadence", accountId, recipient],
    enabled:
      timing.mode === "after_send" &&
      !!accountId &&
      /^[^\s@,]+@[^\s@,]+\.[^\s@,]+$/.test(recipient),
    queryFn: () =>
      api<Page<Schema["ActionRead"]>>(
        `reviewed-actions?${new URLSearchParams({
          kind: "gmail_send",
          state: "succeeded",
          recipient,
          account_id: accountId,
          limit: "50",
        })}`,
      ),
  });
  const prior = previous.data?.items.find(
    (item) => item.id === timing.afterActionId,
  );
  const days = Number(timing.days);
  const sentAt = prior?.attempt?.completed_at;
  const due =
    sentAt && days >= 1 && days <= 90
      ? new Date(new Date(sentAt).getTime() + days * 86400000).toISOString()
      : null;
  const style =
    "h-9 w-full rounded-lg border border-input bg-background px-3 text-sm";
  return (
    <fieldset className="space-y-3 rounded-lg border p-4">
      <legend className="px-1 text-sm font-medium">Delivery timing</legend>
      <label className="block space-y-2 text-sm">
        <span>When to send</span>
        <select
          className={style}
          value={timing.mode}
          onChange={(e) =>
            onChange({ ...timing, mode: e.target.value as EmailTiming["mode"] })
          }
        >
          <option value="now">Send after review</option>
          <option value="at">Schedule a date and time</option>
          <option value="after_send">Follow-up cadence</option>
        </select>
      </label>
      {timing.mode === "at" && (
        <label className="block space-y-2 text-sm">
          <span>
            Send at ({Intl.DateTimeFormat().resolvedOptions().timeZone})
          </span>
          <Input
            type="datetime-local"
            required
            value={timing.localTime}
            onChange={(e) => onChange({ ...timing, localTime: e.target.value })}
          />
        </label>
      )}
      {timing.mode === "after_send" && (
        <>
          <label className="block space-y-2 text-sm">
            <span>Previous sent email</span>
            <select
              required
              className={style}
              value={timing.afterActionId}
              onChange={(e) =>
                onChange({ ...timing, afterActionId: e.target.value })
              }
            >
              <option value="">Choose a confirmed send</option>
              {previous.data?.items.map((item) => (
                <option key={item.id} value={item.id}>
                  {String(item.current.payload.subject || "No subject")} ·{" "}
                  {item.attempt?.completed_at
                    ? sendTimeLabel(item.attempt.completed_at)
                    : "Sent"}
                </option>
              ))}
            </select>
          </label>
          <label className="block space-y-2 text-sm">
            <span>Days after that email</span>
            <Input
              type="number"
              min={1}
              max={90}
              step={1}
              required
              value={timing.days}
              onChange={(e) => onChange({ ...timing, days: e.target.value })}
            />
          </label>
          {due && <p className="text-sm">Scheduled for {sendTimeLabel(due)}</p>}
          {previous.isFetching && (
            <p role="status" className="text-xs">
              Loading sent emails…
            </p>
          )}
          {previous.error && (
            <p role="alert" className="text-xs text-destructive">
              {previous.error.message}
            </p>
          )}
          {!previous.isFetching && !previous.data?.items.length && (
            <p className="text-xs text-muted-foreground">
              Choose an account and one recipient with a confirmed Command
              Center send. You can also schedule a specific date.
            </p>
          )}
          <p className="text-xs text-muted-foreground">
            Each day is 24 hours after the confirmed send. This schedules one
            follow-up; every email needs its own review. Replies are not
            monitored automatically.
          </p>
        </>
      )}
      <p className="text-xs text-muted-foreground">
        Review the final message and time before delivery. Command Center must
        be running to send scheduled emails; delayed jobs send when it resumes.
      </p>
    </fieldset>
  );
}
