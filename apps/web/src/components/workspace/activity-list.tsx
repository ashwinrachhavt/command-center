import { dateLabel, label, type Activity } from "@/lib/api";

export function ActivityList({ events }: { events: Activity[] }) {
  return (
    <div className="flex flex-col">
      {events.map((event) => (
        <div
          key={event.id}
          className="flex gap-3 border-b border-border/60 py-4 last:border-0"
        >
          <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-primary/60" />
          <div className="min-w-0 flex-1">
            <p className="text-xs">
              {label(event.action.replaceAll(".", " "))}
            </p>
            <p className="mt-1 text-[11px] text-muted-foreground">
              {event.details.from_stage
                ? `${label(String(event.details.from_stage))} → ${label(String(event.details.to_stage))}`
                : event.details.version
                  ? `Version ${event.details.version}`
                  : event.details.fields
                    ? `Updated ${String(event.details.fields).replaceAll(",", ", ")}`
                    : "Saved to your workspace"}
            </p>
          </div>
          <time
            className="shrink-0 text-[10px] text-muted-foreground"
            dateTime={event.occurred_at}
          >
            {dateLabel(event.occurred_at)}
          </time>
        </div>
      ))}
      {events.length === 0 ? (
        <p className="py-8 text-sm text-muted-foreground">
          Activity will appear here as this record changes.
        </p>
      ) : null}
    </div>
  );
}
