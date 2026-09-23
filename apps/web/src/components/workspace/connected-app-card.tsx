import {
  ArrowUpRight,
  CalendarDays,
  Check,
  FileText,
  ListTodo,
  Mail,
  Plug,
  ShieldCheck,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { label, type Schema } from "@/lib/api";
import { Spinner } from "./primitives";

export const connectedApps = [
  {
    toolkit: "gmail",
    name: "Gmail",
    category: "Email",
    icon: Mail,
    description:
      "Bring chosen correspondence into your work and send reviewed outreach.",
    read: "Pull email when you ask",
    write: "Send messages after review",
  },
  {
    toolkit: "googlecalendar",
    name: "Google Calendar",
    category: "Calendar",
    icon: CalendarDays,
    description:
      "Use your schedule as context and prepare changes to calendar events.",
    read: "Read selected events and date ranges",
    write: "Create or update events after review",
  },
  {
    toolkit: "linear",
    name: "Linear",
    category: "Projects & issues",
    icon: ListTodo,
    description:
      "Connect project context to your work and prepare issue updates.",
    read: "Read linked issues",
    write: "Create or update issues after review",
  },
  {
    toolkit: "notion",
    name: "Notion",
    category: "Pages & knowledge",
    icon: FileText,
    description:
      "Use selected pages as sources and review changes before publishing.",
    read: "Read selected pages",
    write: "Publish or update pages after review",
  },
] as const;

export type ConnectedApp = (typeof connectedApps)[number];
export type ConnectedAccount = Schema["AccountRead"];

function verifiedAt(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Verification time unavailable"
    : `Verified ${date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}`;
}

export function ConnectedAppCard({
  app,
  accounts,
  configured,
  connecting,
  connectionPending,
  selecting,
  selectedAccountId,
  onConnect,
  onSetup,
  onSelect,
}: {
  app: ConnectedApp;
  accounts: ConnectedAccount[];
  configured: boolean;
  connecting: boolean;
  connectionPending: boolean;
  selecting: boolean;
  selectedAccountId?: string;
  onConnect: () => void;
  onSetup: () => void;
  onSelect: (account: ConnectedAccount) => void;
}) {
  const active = accounts.filter(
    (account) => account.connection_status === "ACTIVE",
  );
  const status = !configured
    ? "Setup required"
    : active.length
      ? "Connected"
      : accounts.length
        ? "Needs attention"
        : "Not connected";
  return (
    <Card role="region" aria-labelledby={`app-${app.toolkit}`}>
      <CardHeader>
        <div className="mb-4 flex items-center gap-3">
          <span className="flex size-11 shrink-0 items-center justify-center rounded-lg border border-border bg-background text-foreground">
            <app.icon className="size-5" aria-hidden />
          </span>
          <div className="min-w-0">
            <CardTitle>
              <h2 id={`app-${app.toolkit}`}>{app.name}</h2>
            </CardTitle>
            <CardDescription>{app.category}</CardDescription>
          </div>
        </div>
        <Badge variant="outline" className="w-fit">
          {configured && active.length > 0 && (
            <Check data-icon="inline-start" />
          )}
          {status}
        </Badge>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        <p className="text-sm leading-6 text-muted-foreground">
          {app.description}
        </p>
        {accounts.length > 0 && (
          <ul className="flex flex-col divide-y divide-border rounded-lg border border-border px-3">
            {accounts.map((account) => (
              <li key={account.id} className="flex min-w-0 flex-col gap-2 py-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <span className="min-w-0 break-all text-sm font-medium">
                    {account.display_name}
                  </span>
                  {account.connection_status !== "ACTIVE" && (
                    <Badge variant="outline">
                      {label(account.connection_status.toLowerCase())}
                    </Badge>
                  )}
                </div>
                <p className="text-xs text-muted-foreground">
                  {verifiedAt(account.identity_verified_at)}
                </p>
                {account.toolkit === "gmail" &&
                  (account.selected_purpose === "outreach" &&
                  account.connection_status === "ACTIVE" ? (
                    <Badge variant="secondary" className="w-fit">
                      <Check data-icon="inline-start" />
                      Outreach account
                    </Badge>
                  ) : (
                    <Button
                      className="w-fit"
                      variant="outline"
                      disabled={
                        !configured ||
                        selecting ||
                        account.connection_status !== "ACTIVE"
                      }
                      onClick={() => onSelect(account)}
                    >
                      {selecting && selectedAccountId === account.id && (
                        <Spinner />
                      )}
                      Use for outreach
                    </Button>
                  ))}
              </li>
            ))}
          </ul>
        )}
        <ul
          className="flex flex-col gap-2 text-sm text-muted-foreground"
          aria-label={`${app.name} supported actions`}
        >
          <li className="flex gap-2">
            <ArrowUpRight className="mt-0.5 size-4 shrink-0" aria-hidden />
            {app.read}
          </li>
          <li className="flex gap-2">
            <ShieldCheck className="mt-0.5 size-4 shrink-0" aria-hidden />
            {app.write}
          </li>
        </ul>
      </CardContent>
      <CardFooter>
        {configured ? (
          <Button
            variant={active.length ? "outline" : "default"}
            disabled={connectionPending}
            onClick={onConnect}
          >
            {connecting ? <Spinner /> : <Plug data-icon="inline-start" />}
            {connecting
              ? "Opening connection…"
              : active.length
                ? "Connect another account"
                : accounts.length
                  ? "Reconnect"
                  : "Connect"}
          </Button>
        ) : (
          <Button variant="outline" onClick={onSetup}>
            View setup
          </Button>
        )}
      </CardFooter>
    </Card>
  );
}
