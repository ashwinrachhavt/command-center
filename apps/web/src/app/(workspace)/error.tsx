"use client";

import { Button } from "@/components/ui/button";

export default function WorkspaceError() {
  return (
    <section className="mx-auto max-w-xl px-6 py-16" role="alert">
      <h1 className="text-xl font-semibold">This page couldn’t load</h1>
      <p className="mt-3 text-sm leading-6 text-muted-foreground">
        Your session or connection may need to refresh. Reload the page to try
        again. Your saved workspace records are still available.
      </p>
      <Button className="mt-5" onClick={() => window.location.reload()}>
        Reload page
      </Button>
    </section>
  );
}
