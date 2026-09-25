"use client";

import { useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowUpRight,
  Bot,
  BookOpen,
  Puzzle,
  Search,
  Workflow,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { api, label, type AgentProfile } from "@/lib/api";
import { cn } from "@/lib/utils";
import { deferView } from "./deferred-view";
import { ErrorState, LoadingRows, PageHeading } from "./primitives";

const Connections = deferView<Record<string, never>>(
  () =>
    import("./connected-accounts").then((module) => ({
      default: module.ConnectedAccounts,
    })),
  "connectors",
);
const Memory = deferView<Record<string, never>>(
  () => import("./memory").then((module) => ({ default: module.MemoryPage })),
  "memory",
);
type Profile = AgentProfile & { skills: string[] };
const tabs = ["agents", "connectors", "skills", "workflows", "memory"] as const;

export function AgentSettings() {
  const params = useSearchParams();
  const requested = params.get("tab") ?? "agents";
  const tab = tabs.find((item) => item === requested) ?? "agents";
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Profile>();
  const profiles = useQuery({
    queryKey: ["profiles"],
    queryFn: () => api<Profile[]>("agents/profiles"),
  });
  const skills = [
    ...new Set(profiles.data?.flatMap((profile) => profile.skills) ?? []),
  ];
  const matches = (text: string) =>
    text.toLowerCase().includes(search.toLowerCase());
  return (
    <>
      <PageHeading
        title="Agents"
        description="The people, knowledge, and tools behind your work."
        action={
          <Button variant="outline" asChild>
            <Link href="/">
              Open Home <ArrowUpRight />
            </Link>
          </Button>
        }
      />
      <nav
        aria-label="Agent configuration"
        className="flex flex-wrap gap-x-6 gap-y-1 border-b border-border px-5 md:px-9"
      >
        {tabs.map((item) => (
          <Link
            key={item}
            href={`/agent-settings?tab=${item}`}
            aria-current={tab === item ? "page" : undefined}
            className={cn(
              "shrink-0 border-b-2 py-3 text-sm",
              tab === item
                ? "border-foreground font-medium text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {label(item)}
          </Link>
        ))}
      </nav>
      {tab === "connectors" ? (
        <Connections />
      ) : tab === "memory" ? (
        <Memory />
      ) : (
        <div className="mx-auto max-w-6xl px-5 py-8 md:px-9">
          <h2 className="text-xl font-medium">
            {tab === "agents"
              ? "Your agents"
              : tab === "skills"
                ? "Available skills"
                : "Workflows"}
          </h2>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
            {tab === "agents"
              ? "See each agent’s model, skills, and allowed tools. Choose an agent when you start a conversation."
              : tab === "skills"
                ? "Reusable instructions assigned to your agents. Each run keeps the skills it started with."
                : "Start an existing workflow from its workspace. Scheduled workflows are not available yet."}
          </p>
          {tab !== "workflows" && (
            <div className="relative my-6">
              <Search className="absolute start-3 top-3 size-4 text-muted-foreground" />
              <Input
                aria-label={`Search ${tab}`}
                placeholder={`Search ${tab}…`}
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                className="ps-9"
              />
            </div>
          )}
          {profiles.error && tab !== "workflows" && (
            <ErrorState
              error={profiles.error}
              retry={() => profiles.refetch()}
            />
          )}
          {profiles.isPending && tab !== "workflows" ? (
            <LoadingRows />
          ) : (
            <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {tab === "agents" &&
                profiles.data
                  ?.filter((profile) =>
                    matches(`${profile.name} ${profile.description}`),
                  )
                  .map((profile) => (
                    <button
                      key={profile.id}
                      onClick={() => setSelected(profile)}
                      className="min-w-0 rounded-xl shadow-surface bg-card p-6 text-start transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      <Bot className="mb-6 size-6 text-muted-foreground" />
                      <h3 className="font-medium">{profile.name}</h3>
                      <p className="mt-2 text-sm leading-6 text-muted-foreground">
                        {profile.description}
                      </p>
                      <div className="mt-5 flex flex-wrap gap-2">
                        <Badge variant="secondary">{profile.model}</Badge>
                        <Badge variant="outline">
                          {profile.ready ? "Ready" : "Setup required"}
                        </Badge>
                      </div>
                    </button>
                  ))}
              {tab === "skills" &&
                skills.filter(matches).map((skill) => (
                  <article
                    key={skill}
                    className="min-w-0 rounded-xl shadow-surface bg-card p-6"
                  >
                    <Puzzle className="mb-6 size-6 text-muted-foreground" />
                    <h3 className="font-medium">{label(skill)}</h3>
                    <p className="mt-2 text-sm leading-6 text-muted-foreground">
                      Used by{" "}
                      {profiles.data
                        ?.filter((profile) => profile.skills.includes(skill))
                        .map((profile) => profile.name)
                        .join(", ")}
                    </p>
                  </article>
                ))}
              {tab === "workflows" &&
                [
                  {
                    title: "Explore an opportunity",
                    description:
                      "Research a lead, keep the evidence, and plan your next step.",
                    href: "/opportunities",
                    icon: Search,
                  },
                  {
                    title: "Follow up with someone",
                    description:
                      "Find your contact, draft a thoughtful message, and review it.",
                    href: "/contacts",
                    icon: Bot,
                  },
                  {
                    title: "Prepare an application",
                    description:
                      "Bring the role, résumé, answers, and next task together.",
                    href: "/applications",
                    icon: Workflow,
                  },
                  {
                    title: "Review agent outputs",
                    description:
                      "Read saved work and record your review of an exact version.",
                    href: "/library?view=generated",
                    icon: BookOpen,
                  },
                ].map((item) => (
                  <Link
                    key={item.href}
                    href={item.href}
                    className="min-w-0 rounded-xl shadow-surface bg-card p-6 transition-colors hover:bg-muted/40"
                  >
                    <item.icon className="mb-6 size-6 text-muted-foreground" />
                    <h3 className="font-medium">{item.title}</h3>
                    <p className="mt-2 text-sm leading-6 text-muted-foreground">
                      {item.description}
                    </p>
                    <span className="mt-5 inline-flex items-center gap-1 text-xs">
                      Open workspace <ArrowUpRight className="size-3" />
                    </span>
                  </Link>
                ))}
            </div>
          )}
          {!profiles.isPending &&
            !profiles.error &&
            ((tab === "skills" && !skills.filter(matches).length) ||
              (tab === "agents" &&
                !profiles.data?.some((profile) =>
                  matches(`${profile.name} ${profile.description}`),
                ))) && (
              <p className="py-12 text-center text-sm text-muted-foreground">
                {search
                  ? "No matches. Try another search."
                  : "No configured items yet."}
              </p>
            )}
        </div>
      )}
      <Dialog
        open={!!selected}
        onOpenChange={(open) => {
          if (!open) setSelected(undefined);
        }}
      >
        <DialogContent className="max-h-[85dvh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{selected?.name}</DialogTitle>
            <DialogDescription>{selected?.description}</DialogDescription>
          </DialogHeader>
          {selected && (
            <div className="space-y-6 text-sm">
              <div>
                <h3 className="mb-2 font-medium">Model</h3>
                <p className="text-muted-foreground">
                  {label(selected.provider)} · {selected.model}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  You can choose a model in your conversation.
                </p>
              </div>
              <div>
                <h3 className="mb-2 font-medium">Skills</h3>
                <div className="flex flex-wrap gap-2">
                  {selected.skills.length ? (
                    selected.skills.map((skill) => (
                      <Badge variant="secondary" key={skill}>
                        {label(skill)}
                      </Badge>
                    ))
                  ) : (
                    <p className="text-muted-foreground">No skills assigned.</p>
                  )}
                </div>
              </div>
              <div>
                <h3 className="mb-2 font-medium">Allowed tools</h3>
                <div className="flex flex-wrap gap-2">
                  {selected.tools.map((tool) => (
                    <Badge variant="outline" key={tool}>
                      {label(tool)}
                    </Badge>
                  ))}
                </div>
              </div>
              {!selected.ready && (
                <p className="text-muted-foreground">
                  Setup needed: {selected.missing_credentials.join(", ")}.{" "}
                  <Link href="/settings" className="underline">
                    Open settings
                  </Link>
                </p>
              )}
              <Button asChild>
                <Link href={`/?agent=${encodeURIComponent(selected.id)}`}>
                  Start a conversation <ArrowUpRight />
                </Link>
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
