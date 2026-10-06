import { Command, ArrowUpRight } from "lucide-react";

export function AuthShell({ children }: { children: React.ReactNode }) {
  return (
    <main className="grid min-h-svh lg:grid-cols-2">
      <section className="relative hidden flex-col justify-between border-e border-border bg-sidebar p-14 lg:flex xl:p-20">
        <div className="flex items-center gap-3 text-sm font-medium">
          <span className="flex size-9 items-center justify-center rounded-xl border border-primary/25 bg-primary/10 text-primary">
            <Command className="size-5" />
          </span>
          Command Center
        </div>
        <div className="max-w-lg py-16">
          <p className="mb-5 text-xs font-medium uppercase tracking-[0.16em] text-primary">
            Room to do your best work
          </p>
          <h1 className="text-5xl leading-[1.12] font-medium tracking-[-0.045em] xl:text-6xl">
            Everything in focus.
            <br />
            <span className="text-muted-foreground">
              Your next move,
              <br />a little clearer.
            </span>
          </h1>
          <p className="mt-7 max-w-sm text-sm leading-7 text-muted-foreground">
            A considered home for your opportunities, relationships, and the
            agents that help you move forward.
          </p>
          <div className="mt-12 flex items-center gap-4 border-t border-border pt-6 text-xs text-muted-foreground">
            <span className="size-1.5 rounded-full bg-primary" />
            One workspace. Yours to shape.
            <ArrowUpRight className="ms-auto size-4" />
          </div>
        </div>
        <p className="text-xs text-muted-foreground">
          Less overhead. More possibility.
        </p>
      </section>
      <section className="flex min-w-0 flex-col items-center justify-center gap-8 px-5 py-14">
        <div className="flex items-center gap-2 text-sm font-medium lg:hidden">
          <Command className="size-5 text-primary" />
          Command Center
        </div>
        {children}
        <p className="text-center text-xs text-muted-foreground">
          Your workspace starts with you.
        </p>
      </section>
    </main>
  );
}
