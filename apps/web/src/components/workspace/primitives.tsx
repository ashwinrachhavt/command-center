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
        "gap-1.5 rounded-md px-2 py-0.5 font-normal",
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
  const palette = [
    "bg-emerald-400/10 text-emerald-200",
    "bg-indigo-400/10 text-indigo-200",
    "bg-amber-400/10 text-amber-200",
    "bg-rose-400/10 text-rose-200",
  ];
  return (
    <span
      aria-hidden
      className={cn(
        "flex size-8 shrink-0 items-center justify-center rounded-lg border border-white/5 text-xs font-medium",
        palette[(name.charCodeAt(0) || 0) % 4],
        className,
      )}
    >
      {name
        .split(" ")
        .slice(0, 2)
        .map((w) => w[0])
        .join("")
        .toUpperCase()}
    </span>
  );
}
export function Priority({ value }: { value: number }) {
  return (
    <span
      title={["Low", "Normal", "High", "Urgent"][value]}
      className="inline-flex items-end gap-0.5"
    >
      <span className="sr-only">
        {["Low", "Normal", "High", "Urgent"][value]} priority
      </span>
      {[0, 1, 2, 3].map((i) => (
        <span
          key={i}
          className={cn(
            "w-0.75 rounded-xs",
            i <= value
              ? value === 3
                ? "bg-amber-300"
                : "bg-muted-foreground"
              : "bg-border",
          )}
          style={{ height: 4 + i * 3 }}
        />
      ))}
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
