import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";
import { SectionView } from "@/components/workspace/section-view";
export default async function HomePage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  await auth.protect();
  const params = await searchParams;
  if (params.session || params.run || params.agent || params.conversation) {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      for (const entry of Array.isArray(value)
        ? value
        : value === undefined
          ? []
          : [value])
        query.append(key, entry);
    }
    redirect(`/agents?${query}`);
  }
  return <SectionView section="briefing" />;
}
