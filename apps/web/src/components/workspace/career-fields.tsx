"use client";

import { Field, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { RichWriter } from "@/components/writing/rich-writer";
import type { Schema } from "@/lib/api";

export type CareerEntry = Schema["CareerEntry"];

export function careerSummary(entry: CareerEntry) {
  return [
    entry.organization,
    entry.role,
    [entry.degree, entry.field_of_study].filter(Boolean).join(" · "),
    entry.location,
    `${entry.start_date ?? "Start unknown"} — ${entry.current === true ? "Present" : (entry.end_date ?? "End unknown")}`,
    entry.description,
  ]
    .filter(Boolean)
    .join("\n");
}

export function CareerFields({
  entry,
  onChange,
  revision,
}: {
  entry: CareerEntry;
  onChange: (next: CareerEntry) => void;
  revision: number;
}) {
  const experience = entry.kind === "experience";
  const textFields = [
    ["organization", experience ? "Company" : "School"],
    ...(experience
      ? [["role", "Job title"]]
      : [
          ["degree", "Degree"],
          ["field_of_study", "Field of study"],
        ]),
    ["location", "Location"],
  ] as [
    "organization" | "role" | "degree" | "field_of_study" | "location",
    string,
  ][];
  return (
    <div className="space-y-4">
      <div className="grid min-w-0 gap-4 sm:grid-cols-2">
        {textFields.map(([field, name]) => (
          <Field key={field}>
            <FieldLabel htmlFor={`career-${field}`}>
              {name}
              {field === "organization" ? " (required)" : ""}
            </FieldLabel>
            <Input
              id={`career-${field}`}
              value={entry[field] ?? ""}
              maxLength={200}
              onChange={(event) =>
                onChange({
                  ...entry,
                  [field]:
                    event.target.value ||
                    (field === "organization" ? "" : null),
                })
              }
            />
          </Field>
        ))}
        <Field>
          <FieldLabel htmlFor="career-current">Current status</FieldLabel>
          <Select
            value={
              entry.current === true
                ? "current"
                : entry.current === false
                  ? "ended"
                  : "unknown"
            }
            onValueChange={(value) =>
              onChange({
                ...entry,
                current: value === "unknown" ? null : value === "current",
                ...(value === "current" ? { end_date: null } : {}),
              })
            }
          >
            <SelectTrigger id="career-current">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="unknown">Unknown</SelectItem>
              <SelectItem value="current">
                {experience
                  ? "I currently work here"
                  : "I currently study here"}
              </SelectItem>
              <SelectItem value="ended">
                {experience
                  ? "I no longer work here"
                  : "I no longer study here"}
              </SelectItem>
            </SelectContent>
          </Select>
        </Field>
      </div>
      <div className="grid min-w-0 gap-4 sm:grid-cols-2">
        {(["start_date", "end_date"] as const).map((field) => (
          <Field key={field}>
            <FieldLabel htmlFor={`career-${field}`}>
              {field === "start_date" ? "Start date" : "End date"}
            </FieldLabel>
            <Input
              id={`career-${field}`}
              value={entry[field] ?? ""}
              maxLength={10}
              placeholder="YYYY, YYYY-MM or YYYY-MM-DD"
              aria-describedby="career-date-help"
              disabled={field === "end_date" && entry.current === true}
              onChange={(event) =>
                onChange({ ...entry, [field]: event.target.value || null })
              }
            />
          </Field>
        ))}
      </div>
      <p id="career-date-help" className="text-xs text-muted-foreground">
        Keep the precision you know. Empty dates remain unknown; an empty end
        date does not mean current.
      </p>
      <Field>
        <FieldLabel htmlFor="career-description">
          {experience ? "Responsibilities and achievements" : "Education notes"}
        </FieldLabel>
        <RichWriter
          id="career-description"
          label={
            experience ? "Responsibilities and achievements" : "Education notes"
          }
          value={entry.description ?? ""}
          format="markdown"
          revision={revision}
          onChange={(description) => onChange({ ...entry, description })}
        />
        <p
          className={`text-xs ${(entry.description?.length ?? 0) > 2000 ? "text-destructive" : "text-muted-foreground"}`}
        >
          {entry.description?.length ?? 0} / 2,000 characters
        </p>
      </Field>
    </div>
  );
}
