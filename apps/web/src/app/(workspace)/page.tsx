import { auth } from "@clerk/nextjs/server";
import { Overview } from "@/components/workspace/overview";
export default async function HomePage() {
  await auth.protect();
  return <Overview />;
}
