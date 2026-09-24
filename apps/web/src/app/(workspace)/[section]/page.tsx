import { auth } from "@clerk/nextjs/server";
import { notFound } from "next/navigation";
import {
  SectionView,
  type WorkspaceSection,
} from "@/components/workspace/section-view";

export default async function SectionPage({
  params,
}: {
  params: Promise<{ section: string }>;
}) {
  const { section } = await params;
  if (
    ![
      "companies",
      "contacts",
      "jobs",
      "opportunities",
      "tasks",
      "spaces",
      "artifacts",
      "library",
      "documents",
      "agent-settings",
      "overview",
      "briefing",
      "notes",
      "agents",
      "settings",
      "connections",
      "memory",
      "browser",
      "applications",
      "activity",
      "actions",
    ].includes(section)
  )
    notFound();
  // Missing static assets can reach this dynamic route without passing the
  // authentication proxy. Reject unknown sections before accessing auth.
  await auth.protect();
  return <SectionView section={section as WorkspaceSection} />;
}
