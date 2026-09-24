"use client";
import { AlertCircle, Inbox, LoaderCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  EmptyDescription,
  EmptyContent,
} from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { label } from "@/lib/api";
import { cn } from "@/lib/utils";

export function Status({ value }: { value: string }) {
  return (
    <Badge
      variant="outline"
      className={cn(
        "gap-1.5 rounded-full px-2.5 py-1 font-medium text-xs transition-colors",
        `stage-${value}`,
      )}
    >
      <span className="size-1.5 rounded-full bg-current" />
      {label(value)}
    </Badge>
  );
}
export function Mark({
  name,
  className,
}: {
  name: string;
  className?: string;
}) {
  const initials = name
    .split(" ")
    .slice(0, 2)
    .map((w) => w[0])
    .join("")
    .toUpperCase();

  const hue =
    name.split("").reduce((acc, char) => acc + char.charCodeAt(0), 0) % 360;

  return (
    <span
      aria-hidden
      className={cn(
        "flex size-10 shrink-0 items-center justify-center rounded-lg text-xs font-semibold tracking-tight transition-transform hover:scale-105",
        className,
      )}
      style={{
        backgroundColor: `hsl(${hue} 70% 95%)`,
        color: `hsl(${hue} 70% 35%)`,
      }}
    >
      {initials}
    </span>
  );
}
export function Priority({ value }: { value: number }) {
  const labels = ["Low", "Normal", "High", "Urgent"];
  const colors = [
    "var(--muted-foreground)",
    "var(--muted-foreground)",
    "var(--status-amber)",
    "var(--status-red)",
  ];

  return (
    <span title={labels[value]} className="inline-flex items-center gap-1.5">
      <span className="sr-only">{labels[value]} priority</span>
      <span className="inline-flex items-end gap-0.5">
        {[0, 1, 2, 3].map((i) => (
          <span
            key={i}
            className={cn(
              "w-1 rounded-sm transition-all",
              i <= value ? "opacity-100" : "opacity-20",
            )}
            style={{
              height: 4 + i * 3,
              backgroundColor: i <= value ? colors[value] : "var(--border)",
            }}
          />
        ))}
      </span>
      <span className="text-xs font-medium" style={{ color: colors[value] }}>
        {labels[value]}
      </span>
    </span>
  );
}
export function LoadingRows() {
  return (
    <div className="flex flex-col gap-6 p-6" aria-label="Loading records">
      {Array.from({ length: 5 }, (_, i) => (
        <div className="flex gap-5" key={i}>
          <Skeleton className="size-8" />
          <Skeleton className="h-8 w-1/3" />
          <Skeleton className="ml-auto h-8 w-1/5" />
        </div>
      ))}
    </div>
  );
}
export function ErrorState({
  error,
  retry,
}: {
  error: Error;
  retry?: () => void;
}) {
  return (
    <Alert variant="destructive" className="my-5">
      <AlertCircle />
      <AlertTitle>Couldn’t load your workspace</AlertTitle>
      <AlertDescription>
        {error.message}
        {retry && (
          <Button variant="outline" className="mt-3 w-fit" onClick={retry}>
            Try again
          </Button>
        )}
      </AlertDescription>
    </Alert>
  );
}
export function EmptyState({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children?: React.ReactNode;
}) {
  return (
    <Empty className="min-h-72">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <Inbox />
        </EmptyMedia>
        <EmptyTitle>{title}</EmptyTitle>
        <EmptyDescription>{description}</EmptyDescription>
      </EmptyHeader>
      {children && <EmptyContent>{children}</EmptyContent>}
    </Empty>
  );
}
export function Spinner() {
  return <LoaderCircle className="animate-spin" aria-hidden />;
}
export function PageHeading({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-5 px-5 py-7 md:px-9 md:py-8">
      <div>
        {eyebrow && (
          <p className="mb-2 text-xs text-muted-foreground">{eyebrow}</p>
        )}
        <h1 className="text-2xl font-medium tracking-tight">{title}</h1>
        {description && (
          <p className="mt-2 text-sm text-muted-foreground">{description}</p>
        )}
      </div>
      {action}
    </div>
  );
}
