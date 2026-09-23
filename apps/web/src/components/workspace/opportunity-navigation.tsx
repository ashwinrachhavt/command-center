"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

export function OpportunityNavigation() {
  const path = usePathname();
  return (
    <nav
      aria-label="Opportunity views"
      className="flex gap-6 overflow-x-auto border-b border-border px-5 md:px-9"
    >
      {[
        { href: "/opportunities", label: "All opportunities" },
        { href: "/applications", label: "Applications" },
        { href: "/jobs", label: "Saved roles" },
      ].map((item) => (
        <Link
          key={item.href}
          href={item.href}
          aria-current={path === item.href ? "page" : undefined}
          className={cn(
            "shrink-0 border-b-2 py-3 text-sm",
            path === item.href
              ? "border-foreground font-medium"
              : "border-transparent text-muted-foreground hover:text-foreground",
          )}
        >
          {item.label}
        </Link>
      ))}
    </nav>
  );
}
