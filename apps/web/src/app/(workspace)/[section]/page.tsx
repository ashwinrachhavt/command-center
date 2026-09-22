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
  await auth.protect();
  const { section } = await params;
  if (
    ![
      "companies",
      "contacts",
      "jobs",
      "opportunities",
      "tasks",
      "artifacts",
      "agents",
      "settings",
      "memory",
      "browser",
      "activity",
      "actions",
    ].includes(section)
  )
    notFound();
  return <SectionView section={section as WorkspaceSection} />;
}
