import { auth } from "@clerk/nextjs/server";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { Records } from "@/components/workspace/records";
import { Agents } from "@/components/workspace/agents";
import { Settings } from "@/components/workspace/settings";
import { MemoryPage } from "@/components/workspace/memory";
import { BrowserPage } from "@/components/workspace/browser";
import { ActivityPage } from "@/components/workspace/activity";
import { ReviewedActions } from "@/components/workspace/reviewed-actions";
import { LoadingRows } from "@/components/workspace/primitives";
import type { Resource } from "@/lib/api";

export default async function SectionPage({
  params,
}: {
  params: Promise<{ section: string }>;
}) {
  await auth.protect();
  const { section } = await params;
  if (
    [
      "companies",
      "contacts",
      "jobs",
      "opportunities",
      "tasks",
      "artifacts",
    ].includes(section)
  )
    return (
      <Suspense fallback={<LoadingRows />}>
        <Records key={section} resource={section as Resource} />
      </Suspense>
    );
  if (section === "agents") return <Agents />;
  if (section === "settings") return <Settings />;
  if (section === "memory") return <MemoryPage />;
  if (section === "browser") return <BrowserPage />;
  if (section === "activity") return <ActivityPage />;
  if (section === "actions") return <ReviewedActions />;
  notFound();
}
