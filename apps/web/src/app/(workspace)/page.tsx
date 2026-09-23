import { auth } from "@clerk/nextjs/server";
import { SectionView } from "@/components/workspace/section-view";
export default async function HomePage() {
  await auth.protect();
  return <SectionView section="agents" />;
}
