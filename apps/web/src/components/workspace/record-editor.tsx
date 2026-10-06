"use client";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { useEffect, useRef, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { RichWriter } from "@/components/writing/rich-writer";
import { DraftStatus } from "@/components/writing/draft-status";
import { useWorkingDraft } from "@/components/writing/use-working-draft";
import {
  Field,
  FieldGroup,
  FieldLabel,
  FieldDescription,
} from "@/components/ui/field";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  api,
  ApiError,
  label,
  type Resource,
  type WorkspaceRecord,
  type Page,
} from "@/lib/api";
import { Spinner } from "./primitives";

export const stages = [
  "researching",
  "preparing",
  "applied",
  "interviewing",
  "offer",
  "closed",
];
export const resourceNames: Record<
  Resource,
  { plural: string; singular: string; description: string }
> = {
  companies: {
    plural: "Companies",
    singular: "company",
    description: "Build a clear picture of the teams you want to work with.",
  },
  contacts: {
    plural: "Contacts",
    singular: "person",
    description: "Good opportunities start with meaningful relationships.",
  },
  jobs: {
    plural: "Roles",
    singular: "role",
    description: "Keep the roles worth exploring close at hand.",
  },
  opportunities: {
    plural: "Opportunities",
    singular: "opportunity",
    description: "Work, people, ideas, and possibilities worth your attention.",
  },
  tasks: {
    plural: "Tasks",
    singular: "task",
    description: "Small, deliberate steps that keep things moving.",
  },
  artifacts: {
    plural: "Library",
    singular: "document",
    description: "A home for your notes, source material and finished writing.",
  },
};
type FormValues = Record<string, string>;
type EditorField = {
  name: string;
  title: string;
  required?: boolean;
  kind?: "text" | "email" | "url" | "date" | "number" | "textarea" | "select";
  choices?: string[];
  lookup?: string;
  max?: number;
  initial?: string;
  createOnly?: boolean;
};
const title: EditorField = {
  name: "title",
  title: "Title",
  required: true,
  max: 300,
};
const company: EditorField = {
  name: "company_id",
  title: "Company",
  required: true,
  lookup: "companies",
};
const priority: EditorField = {
  name: "priority",
  title: "Priority",
  kind: "select",
  choices: ["0", "1", "2", "3"],
  initial: "1",
  required: true,
};
const notes: EditorField = {
  name: "notes",
  title: "Notes",
  kind: "textarea",
  max: 20000,
};
const location: EditorField = { name: "location", title: "Location", max: 200 };
const fields: Record<Resource, EditorField[]> = {
  companies: [
    { name: "name", title: "Company name", required: true, max: 200 },
    { name: "domain", title: "Website domain", max: 253 },
    { name: "industry", title: "Industry", max: 150 },
    location,
    { ...notes, name: "description", title: "About the company" },
  ],
  contacts: [
    { name: "name", title: "Full name", required: true, max: 200 },
    { name: "email", title: "Email", kind: "email", max: 320 },
    { ...title, required: false, title: "Job title", max: 200 },
    { ...company, required: false },
    { name: "linkedin_url", title: "LinkedIn URL", kind: "url" },
    {
      name: "relationship",
      title: "Relationship",
      kind: "select",
      choices: ["new", "connected", "warm", "advocate"],
      initial: "new",
      required: true,
    },
    notes,
  ],
  jobs: [
    title,
    { ...company, createOnly: true },
    location,
    {
      name: "work_mode",
      title: "Work arrangement",
      kind: "select",
      choices: ["unspecified", "remote", "hybrid", "onsite"],
      initial: "unspecified",
      required: true,
    },
    { name: "source_url", title: "Role URL", kind: "url" },
    { name: "salary_min", title: "Salary from", kind: "number" },
    { name: "salary_max", title: "Salary to", kind: "number" },
    {
      name: "currency",
      title: "Currency",
      initial: "USD",
      max: 3,
      required: true,
    },
    {
      name: "status",
      title: "Availability",
      kind: "select",
      choices: ["open", "closed", "unknown"],
      initial: "open",
      required: true,
    },
    { ...notes, name: "description", title: "Role description" },
  ],
  opportunities: [
    title,
    { ...company, createOnly: true },
    {
      name: "job_id",
      title: "Role (optional)",
      lookup: "jobs",
      createOnly: true,
    },
    { name: "contact_id", title: "Primary contact", lookup: "contacts" },
    {
      name: "stage",
      title: "Stage",
      kind: "select",
      choices: stages,
      initial: "researching",
      required: true,
    },
    priority,
    notes,
  ],
  tasks: [
    title,
    { name: "opportunity_id", title: "Opportunity", lookup: "opportunities" },
    priority,
    { name: "due_date", title: "Due date", kind: "date" },
    { ...notes, name: "rationale", title: "Details" },
  ],
  artifacts: [
    title,
    {
      name: "kind",
      title: "Kind",
      kind: "select",
      choices: ["document", "research", "message", "package", "source"],
      initial: "document",
      required: true,
      createOnly: true,
    },
    {
      name: "document_type_id",
      title: "Document type",
      lookup: "document-types",
      createOnly: true,
    },
    {
      name: "sensitivity",
      title: "Sensitivity",
      kind: "select",
      choices: ["private", "restricted", "public"],
      initial: "private",
      required: true,
    },
    {
      name: "text",
      title: "Content",
      kind: "textarea",
      max: 100000,
      createOnly: true,
    },
  ],
};

function Lookup({
  field,
  value,
  onChange,
  companyId,
}: {
  field: EditorField;
  value: string;
  onChange: (value: string) => void;
  companyId?: string;
}) {
  const [q, setQ] = useState("");
  const settledQuery = useDebouncedValue(q.trim());
  const query = useQuery({
    queryKey: ["lookup", field.lookup, settledQuery, companyId],
    queryFn: async ({ signal }) => {
      const result = await api<
        | Page<{ id: string; name?: string; title?: string }>
        | { id: string; name: string }[]
      >(
        `${field.lookup}${field.lookup === "document-types" ? "" : `?limit=100&q=${encodeURIComponent(settledQuery)}${field.lookup === "jobs" && companyId ? `&company_id=${companyId}` : ""}`}`,
        { signal },
      );
      return Array.isArray(result) ? result : result.items;
    },
  });
  return (
    <div className="flex flex-col gap-2">
      {field.lookup !== "document-types" && (
        <Input
          aria-label={`Find ${field.title.toLowerCase()}`}
          placeholder={`Find ${field.title.toLowerCase()}…`}
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      )}
      <Select
        value={value || "none"}
        onValueChange={(v) => onChange(v === "none" ? "" : v)}
      >
        <SelectTrigger id={field.name} className="w-full">
          <SelectValue placeholder="Choose a record" />
        </SelectTrigger>
        <SelectContent>
          <SelectGroup>
            <SelectItem value="none">
              {field.required ? "Choose a record" : "None"}
            </SelectItem>
            {value && !query.data?.some((r) => r.id === value) && (
              <SelectItem value={value}>
                Selected record · {value.slice(0, 8)}
              </SelectItem>
            )}
            {query.data?.map((r) => (
              <SelectItem key={r.id} value={r.id}>
                {r.name ?? ("title" in r ? r.title : r.id)}
              </SelectItem>
            ))}
          </SelectGroup>
        </SelectContent>
      </Select>
      {query.error && (
        <p className="text-xs text-destructive">{query.error.message}</p>
      )}
    </div>
  );
}

type RecordEditorProps = {
  resource: Resource;
  record?: WorkspaceRecord;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved?: (record: WorkspaceRecord) => void;
  defaults?: FormValues;
  hiddenFields?: string[];
  noun?: string;
  draftKey?: string;
  sourceArtifactId?: string;
};
type RecordDraft = {
  form: FormValues;
  expectedVersion: number | null;
  dueAt: string | null;
};

export function RecordEditor(props: RecordEditorProps) {
  const { isLoaded, userId } = useAuth();
  if (!props.open || !isLoaded || !userId) return null;
  return (
    <OwnedRecordEditor
      key={`${userId}-${props.resource}-${props.record?.id ?? props.draftKey ?? "new"}`}
      {...props}
      actor={userId}
    />
  );
}

function OwnedRecordEditor({
  resource,
  record,
  open,
  onOpenChange,
  onSaved,
  actor,
  defaults,
  sourceArtifactId,
  hiddenFields = [],
  noun = resourceNames[resource].singular,
  draftKey,
}: RecordEditorProps & { actor: string }) {
  const client = useQueryClient();
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  const initial = Object.fromEntries(
    fields[resource].map((f) => [
      f.name,
      record && f.name in record
        ? String((record as unknown as Record<string, unknown>)[f.name] ?? "")
        : (defaults?.[f.name] ?? f.initial ?? ""),
    ]),
  );
  const writing = useWorkingDraft<RecordDraft>(
    actor,
    `record-${resource}-${record?.id ?? draftKey ?? "new"}`,
    {
      form: initial,
      expectedVersion: record?.row_version ?? null,
      dueAt:
        record && "due_at" in record
          ? String(record.due_at ?? "") || null
          : null,
    },
  );
  const { draft } = writing;
  const form = writing.data.form;
  const setForm = (form: FormValues) =>
    draft.edit((current) => ({ ...current, form }));
  const mutation = useMutation({
    mutationFn: async () => {
      const snapshot = draft.getSnapshot().data;
      const submitted = snapshot.form;
      const body: Record<string, string | number | null> = {};
      for (const field of fields[resource]) {
        if (record && field.createOnly) continue;
        const raw = submitted[field.name] ?? "";
        if (field.max && raw.length > field.max)
          throw new Error(
            `${field.title} must be under ${field.max.toLocaleString()} characters.`,
          );
        if (field.required && !raw.trim())
          throw new Error(`${field.title} is required.`);
        body[field.name] =
          field.kind === "number" || field.name === "priority"
            ? raw
              ? Number(raw)
              : null
            : raw || (field.required || field.name === "text" ? "" : null);
      }
      if (resource === "artifacts" && !record && submitted.kind !== "document")
        body.document_type_id = null;
      if (snapshot.expectedVersion !== null)
        body.expected_version = snapshot.expectedVersion;
      if (
        resource === "tasks" &&
        record &&
        snapshot.dueAt &&
        submitted.due_date
      )
        body.due_at = null;
      const target =
        resource === "tasks" && !record && sourceArtifactId
          ? `artifacts/${sourceArtifactId}/tasks`
          : `${resource}${record ? `/${record.id}` : ""}`;
      const method = record ? "PATCH" : "POST";
      await draft.flush();
      const intent = draft.request(method, target, body, snapshot);
      const saved = await api<WorkspaceRecord>(intent.target, {
        method: intent.method,
        body: intent.body,
        key: intent.key,
      });
      return { saved, snapshot: intent.snapshot };
    },
    onSuccess: async ({ saved, snapshot }) => {
      void client.invalidateQueries();
      try {
        if (await draft.clearIfUnchanged(snapshot)) {
          draft.resetIntent();
          if (active.current) {
            onSaved?.(saved);
            onOpenChange(false);
          }
        } else {
          draft.resetIntent();
          draft.edit((current) => ({
            ...current,
            expectedVersion: saved.row_version,
            dueAt:
              "due_at" in saved ? String(saved.due_at ?? "") || null : null,
          }));
          toast.message("Saved. Your newer changes remain in the draft.");
        }
      } catch {
        toast.message(
          "Record saved. Your working copy remains available to recover.",
        );
      }
      toast.success(`${label(noun)} ${record ? "updated" : "created"}`);
    },
    onError: (error) => {
      if (error instanceof ApiError && [400, 413, 422].includes(error.status))
        draft.resetIntent();
      toast.error(error.message);
    },
  });
  const lockedCreation = !record && (mutation.isPending || draft.hasCheckpoint);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {record ? "Edit" : "New"} {noun}
          </DialogTitle>
          <DialogDescription>
            {record
              ? "Update the details. Your changes will appear in activity."
              : "Add the details that matter. You can fill in more as you learn."}
          </DialogDescription>
        </DialogHeader>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            mutation.mutate();
          }}
        >
          <DraftStatus
            draft={draft}
            state={writing}
            disabled={mutation.isPending || lockedCreation}
            preview={(copy) =>
              Object.entries(copy.form)
                .filter(([, value]) => value)
                .map(([key, value]) => `${label(key)}: ${value}`)
                .join("\n\n")
            }
          />
          <fieldset disabled={lockedCreation || writing.status === "loading"}>
            <FieldGroup className="gap-5 py-3">
              {fields[resource]
                .filter(
                  (f) =>
                    !hiddenFields.includes(f.name) &&
                    !(record && f.createOnly) &&
                    !(
                      f.name === "document_type_id" && form.kind !== "document"
                    ),
                )
                .map((f) => (
                  <Field key={f.name}>
                    <FieldLabel htmlFor={f.name}>
                      {f.title}
                      {f.required && (
                        <span className="text-muted-foreground">*</span>
                      )}
                    </FieldLabel>
                    {f.lookup ? (
                      <Lookup
                        field={f}
                        value={form[f.name]}
                        onChange={(v) => setForm({ ...form, [f.name]: v })}
                        companyId={form.company_id}
                      />
                    ) : f.kind === "select" ? (
                      <Select
                        value={form[f.name]}
                        onValueChange={(v) => setForm({ ...form, [f.name]: v })}
                      >
                        <SelectTrigger id={f.name} className="w-full">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectGroup>
                            {f.choices?.map((v) => (
                              <SelectItem key={v} value={v}>
                                {f.name === "priority"
                                  ? ["Low", "Normal", "High", "Urgent"][
                                      Number(v)
                                    ]
                                  : label(v)}
                              </SelectItem>
                            ))}
                          </SelectGroup>
                        </SelectContent>
                      </Select>
                    ) : f.kind === "textarea" ? (
                      <RichWriter
                        id={f.name}
                        label={f.title}
                        value={form[f.name] ?? ""}
                        format="markdown"
                        revision={writing.editorRevision}
                        disabled={
                          lockedCreation || writing.status === "loading"
                        }
                        onChange={(value) =>
                          draft.edit((current) => ({
                            ...current,
                            form: { ...current.form, [f.name]: value },
                          }))
                        }
                      />
                    ) : (
                      <Input
                        id={f.name}
                        type={f.kind ?? "text"}
                        required={f.required}
                        maxLength={f.max}
                        min={f.kind === "number" ? 0 : undefined}
                        value={form[f.name]}
                        onChange={(e) =>
                          setForm({ ...form, [f.name]: e.target.value })
                        }
                        placeholder={
                          f.name === "domain" ? "company.com" : undefined
                        }
                      />
                    )}
                    {f.name === "sensitivity" && (
                      <FieldDescription>
                        Controls classification. Your artifacts are always
                        private to this workspace.
                      </FieldDescription>
                    )}
                  </Field>
                ))}
            </FieldGroup>
          </fieldset>
          {lockedCreation && !mutation.isPending && (
            <p role="status" className="my-3 text-sm text-muted-foreground">
              The last creation request has no confirmed response. Retry to
              recover its result before editing further.
            </p>
          )}
          {mutation.error && (
            <p role="alert" className="mb-4 text-sm text-destructive">
              {mutation.error.message}
            </p>
          )}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Close writer
            </Button>
            <Button
              type="submit"
              disabled={
                mutation.isPending ||
                writing.status === "loading" ||
                writing.status === "conflict"
              }
            >
              {mutation.isPending && <Spinner />}
              {record ? "Save changes" : `Create ${noun}`}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
