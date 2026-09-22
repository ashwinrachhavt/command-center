"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { UserButton } from "@clerk/nextjs";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  BookOpen,
  Bot,
  BriefcaseBusiness,
  Building2,
  CheckCheck,
  Command,
  Files,
  FileCheck,
  LayoutDashboard,
  Puzzle,
  Search,
  Settings2,
  Users,
} from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Sidebar,
  SidebarProvider,
  SidebarTrigger,
  SidebarInset,
  useSidebar,
} from "@/components/ui/sidebar";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { api, type Page, type Resources, type Profile } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Appearance } from "@/components/appearance";
import { WorkspaceContext, useWorkspaceContext, isResource } from "./context";

export const navigation = [
  { path: "/", name: "Overview", icon: LayoutDashboard },
  { path: "/opportunities", name: "Opportunities", icon: BriefcaseBusiness },
  { path: "/contacts", name: "Contacts", icon: Users },
  { path: "/companies", name: "Companies", icon: Building2 },
  { path: "/jobs", name: "Roles", icon: Search },
  { path: "/tasks", name: "Tasks", icon: CheckCheck },
  { path: "/artifacts", name: "Artifacts", icon: Files },
  { path: "/actions", name: "Reviewed actions", icon: FileCheck },
  { path: "/agents", name: "Agents", icon: Bot },
  { path: "/browser", name: "Browser companion", icon: Puzzle },
  { path: "/memory", name: "Memory", icon: BookOpen },
  { path: "/activity", name: "Activity", icon: Activity },
  { path: "/settings", name: "Settings", icon: Settings2 },
];

function Navigation({ onNavigate }: { onNavigate?: () => void }) {
  const path = usePathname();
  const profile = useQuery({
    queryKey: ["me"],
    queryFn: () => api<Profile>("me"),
  });
  return (
    <div className="flex h-full flex-col overflow-y-auto bg-sidebar p-3">
      <Link
        href="/"
        onClick={onNavigate}
        className="mb-6 flex items-center gap-2.5 px-2 py-3 text-sm font-semibold tracking-tight"
      >
        <span className="flex size-7 items-center justify-center rounded-lg border border-primary/25 bg-primary/10 text-primary">
          <Command className="size-4" />
        </span>
        Command Center
      </Link>
      <div className="mb-5 flex items-center gap-2.5 rounded-lg border border-border bg-background/40 px-3 py-2.5">
        <span className="flex size-6 items-center justify-center rounded-md bg-secondary text-xs font-medium">
          {(profile.data?.display_name ?? "My workspace")[0]}
        </span>
        <div className="min-w-0">
          <p className="truncate text-xs font-medium text-foreground">
            {profile.data?.display_name ?? "My workspace"}
          </p>
          <p className="mt-0.5 text-[10px] text-muted-foreground">
            Personal workspace
          </p>
        </div>
      </div>
      <nav
        className="flex flex-1 flex-col gap-0.5"
        aria-label="Main navigation"
      >
        {navigation.map((item, i) => (
          <div key={item.path}>
            {(item.path === "/" ||
              item.path === "/agents" ||
              item.path === "/activity") && (
              <p
                className={cn(
                  "px-3 pb-2 text-[10px] font-medium tracking-[0.08em] text-muted-foreground",
                  i > 0 && "mt-6",
                )}
              >
                {i === 0
                  ? "WORKSPACE"
                  : item.path === "/agents"
                    ? "ASSISTANTS"
                    : "MANAGE"}
              </p>
            )}
            <Link
              onClick={onNavigate}
              href={item.path}
              aria-current={path === item.path ? "page" : undefined}
              className={cn(
                "flex items-center gap-2.5 rounded-md px-3 py-2 text-[13px] transition-colors hover:bg-sidebar-accent hover:text-foreground",
                path === item.path
                  ? "bg-sidebar-accent text-sidebar-accent-foreground"
                  : "text-sidebar-foreground",
              )}
            >
              <item.icon
                className={cn("size-4", path === item.path && "text-primary")}
              />
              {item.name}
              {path === item.path && (
                <span className="ml-auto size-1 rounded-full bg-primary" />
              )}
            </Link>
          </div>
        ))}
      </nav>
      <div className="mt-4 flex items-center gap-2.5 border-t border-border px-2 pt-4">
        <UserButton />
        <div>
          <p className="text-xs">Your account</p>
          <p className="text-[10px] text-muted-foreground">Personal account</p>
        </div>
      </div>
    </div>
  );
}

function WorkspaceSearch({
  open,
  setOpen,
}: {
  open: boolean;
  setOpen: (open: boolean) => void;
}) {
  const context = useWorkspaceContext();
  const [q, setQ] = useState("");
  const query = useQuery({
    queryKey: ["search", q],
    enabled: open && q.trim().length > 1,
    queryFn: async ({ signal }) => {
      const [companies, opportunities, people] = await Promise.all([
        api<Page<Resources["companies"]>>(
          `companies?q=${encodeURIComponent(q)}&limit=5`,
          { signal },
        ),
        api<Page<Resources["opportunities"]>>(
          `opportunities?q=${encodeURIComponent(q)}&limit=5`,
          { signal },
        ),
        api<Page<Resources["contacts"]>>(
          `contacts?q=${encodeURIComponent(q)}&limit=5`,
          { signal },
        ),
      ]);
      return [
        ...companies.items.map((r) => ({
          title: r.name,
          group: "Company",
          href: `/companies?record=${r.id}`,
        })),
        ...opportunities.items.map((r) => ({
          title: r.title,
          group: "Opportunity",
          href: `/opportunities?record=${r.id}`,
        })),
        ...people.items.map((r) => ({
          title: r.name,
          group: "Person",
          href: `/contacts?record=${r.id}`,
        })),
      ];
    },
  });
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Search your workspace</DialogTitle>
          <DialogDescription>
            Find companies, people and opportunities.
          </DialogDescription>
        </DialogHeader>
        <Input
          aria-label="Search your workspace"
          placeholder="Start typing a name or role…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          autoFocus
        />
        <div className="max-h-80 overflow-auto">
          {query.isFetching ? (
            <p className="py-4 text-muted-foreground">Searching…</p>
          ) : query.error ? (
            <p role="alert" className="text-destructive">
              {query.error.message}
            </p>
          ) : query.data?.length === 0 ? (
            <p className="py-4 text-muted-foreground">No matching records.</p>
          ) : (
            query.data?.map((r) => (
              <Link
                onClick={(event) => {
                  if (
                    context &&
                    !event.metaKey &&
                    !event.ctrlKey &&
                    !event.shiftKey &&
                    !event.altKey
                  ) {
                    event.preventDefault();
                    const [target, params] = r.href.slice(1).split("?");
                    if (isResource(target))
                      context.open(
                        target,
                        new URLSearchParams(params).get("record") ?? undefined,
                      );
                  }
                  setOpen(false);
                }}
                key={r.href}
                href={r.href}
                className="flex items-center justify-between rounded-md p-3 hover:bg-muted"
              >
                <span>{r.title}</span>
                <span className="text-xs text-muted-foreground">{r.group}</span>
              </Link>
            ))
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function SidebarNavigation() {
  const { setOpenMobile } = useSidebar();
  return <Navigation onNavigate={() => setOpenMobile(false)} />;
}

export function WorkspaceShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const [searchOpen, setSearchOpen] = useState(false);
  return (
    <WorkspaceContext>
      <SidebarProvider
        style={{ "--sidebar-width": "14rem" } as React.CSSProperties}
      >
        <Sidebar collapsible="offcanvas" className="border-r border-border">
          <SidebarNavigation />
        </Sidebar>
        <SidebarInset className="min-w-0 bg-background">
          <header className="sticky top-0 z-20 flex h-14 shrink-0 items-center gap-3 border-b border-border bg-background/95 px-5 backdrop-blur-md md:px-7">
            <SidebarTrigger className="text-muted-foreground" />
            <Breadcrumb>
              <BreadcrumbList className="text-xs">
                <BreadcrumbItem className="hidden sm:block">
                  Workspace
                </BreadcrumbItem>
                <BreadcrumbSeparator className="hidden sm:block" />
                <BreadcrumbItem>
                  <BreadcrumbPage>
                    {navigation.find((n) => n.path === path)?.name ??
                      "Workspace"}
                  </BreadcrumbPage>
                </BreadcrumbItem>
              </BreadcrumbList>
            </Breadcrumb>
            <div className="ml-auto flex items-center gap-2">
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Search workspace"
                onClick={() => setSearchOpen(true)}
              >
                <Search />
              </Button>
              <Appearance />
            </div>
          </header>
          <main className="min-w-0 flex-1">{children}</main>
        </SidebarInset>
        <WorkspaceSearch open={searchOpen} setOpen={setSearchOpen} />
      </SidebarProvider>
    </WorkspaceContext>
  );
}
