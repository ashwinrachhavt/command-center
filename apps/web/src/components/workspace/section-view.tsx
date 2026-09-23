"use client";

import type { Resource } from "@/lib/api";
import { deferView } from "./deferred-view";

const Records = deferView<{ resource: Resource }>(
  () => import("./records").then((module) => ({ default: module.Records })),
  "records",
);
const Library = deferView<{ notes?: boolean }>(
  () => import("./library").then((module) => ({ default: module.Library })),
  "library",
);
const Agents = deferView<Record<string, never>>(
  () => import("./agents").then((module) => ({ default: module.Agents })),
  "agents",
);
const Settings = deferView<Record<string, never>>(
  () => import("./settings").then((module) => ({ default: module.Settings })),
  "settings",
);
const Connections = deferView<Record<string, never>>(
  () =>
    import("./connected-accounts").then((module) => ({
      default: module.ConnectedAccounts,
    })),
  "connected apps",
);
const Memory = deferView<Record<string, never>>(
  () => import("./memory").then((module) => ({ default: module.MemoryPage })),
  "memory",
);
const Browser = deferView<Record<string, never>>(
  () => import("./browser").then((module) => ({ default: module.BrowserPage })),
  "browser",
);
const Applications = deferView<Record<string, never>>(
  () =>
    import("./applications").then((module) => ({
      default: module.Applications,
    })),
  "applications",
);
const Activity = deferView<Record<string, never>>(
  () =>
    import("./activity").then((module) => ({ default: module.ActivityPage })),
  "activity",
);
const Actions = deferView<Record<string, never>>(
  () =>
    import("./reviewed-actions").then((module) => ({
      default: module.ReviewedActions,
    })),
  "reviewed actions",
);

export type WorkspaceSection =
  | Resource
  | "agents"
  | "settings"
  | "connections"
  | "library"
  | "notes"
  | "memory"
  | "browser"
  | "applications"
  | "activity"
  | "actions";

export function SectionView({ section }: { section: WorkspaceSection }) {
  switch (section) {
    case "library":
      return <Library />;
    case "notes":
      return <Library key="notes" notes />;
    case "agents":
      return <Agents />;
    case "settings":
      return <Settings />;
    case "connections":
      return <Connections />;
    case "memory":
      return <Memory />;
    case "browser":
      return <Browser />;
    case "applications":
      return <Applications />;
    case "activity":
      return <Activity />;
    case "actions":
      return <Actions />;
    default:
      return <Records key={section} resource={section} />;
  }
}
