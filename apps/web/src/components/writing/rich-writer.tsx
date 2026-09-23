"use client";

import { useEffect, useRef, useState } from "react";
import {
  EditorContent,
  useEditor,
  useEditorState,
  type JSONContent,
} from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Placeholder from "@tiptap/extension-placeholder";
import { Markdown } from "@tiptap/markdown";
import {
  Bold,
  Italic,
  List,
  ListOrdered,
  Quote,
  Heading2,
  Link2,
  Undo2,
  Redo2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

export type WritingFormat = "text" | "html" | "markdown";
type Props = {
  id: string;
  label: string;
  value: string;
  format?: WritingFormat;
  onChange: (
    value: string,
    format: WritingFormat,
    document?: JSONContent,
  ) => void;
  placeholder?: string;
  disabled?: boolean;
  /** Increment when deliberately loading another copy, never for keystrokes. */
  revision?: number;
};

function textDocument(value: string): JSONContent {
  return {
    type: "doc",
    content: value.split("\n").map((line) => ({
      type: "paragraph",
      ...(line ? { content: [{ type: "text", text: line }] } : {}),
    })),
  };
}

// The shared writer supports these structures without changing their meaning.
// Keep unsupported legacy source intact instead of silently dropping it on import.
function needsSource(value: string, format: WritingFormat) {
  if (format === "text") return false;
  return (
    /<(?:table|img|video|audio|iframe|svg|style|script|figure|details)\b/i.test(
      value,
    ) ||
    (format === "markdown" &&
      (/!\[[^\]]*\]\(/.test(value) ||
        /^\s*\|.*\|\s*$/m.test(value) ||
        /^\s*[-*+]\s+\[[ xX]\]/m.test(value) ||
        /^\s*\[\^[^\]]+\]:/m.test(value) ||
        /^\s*\${2}/m.test(value) ||
        /<\/?[a-z][^>]*>/i.test(value)))
  );
}

export function RichWriter(props: Props) {
  const format = props.format ?? "text";
  if (needsSource(props.value, format))
    return (
      <div className="space-y-2">
        <p className="text-xs text-muted-foreground">
          This writing contains a layout that needs source editing. Its original
          formatting is preserved.
        </p>
        <Textarea
          id={props.id}
          aria-label={props.label}
          value={props.value}
          disabled={props.disabled}
          rows={10}
          onChange={(event) => props.onChange(event.target.value, format)}
        />
      </div>
    );
  return <TiptapWriter key={props.revision ?? 0} {...props} />;
}

function TiptapWriter({
  id,
  label,
  value,
  format = "text",
  onChange,
  placeholder,
  disabled,
}: Props) {
  const callback = useRef(onChange);
  const currentFormat = useRef(format);
  useEffect(() => {
    callback.current = onChange;
    currentFormat.current = format;
  }, [onChange, format]);
  const editor = useEditor({
    immediatelyRender: false,
    shouldRerenderOnTransaction: false,
    extensions: [
      StarterKit.configure({
        link: {
          openOnClick: false,
          defaultProtocol: "https",
          protocols: ["https", "http", "mailto"],
        },
      }),
      Markdown,
      Placeholder.configure({ placeholder: placeholder ?? "Start writing…" }),
    ],
    content: format === "text" ? textDocument(value) : value,
    ...(format === "markdown" ? { contentType: "markdown" as const } : {}),
    editorProps: {
      attributes: {
        id,
        role: "textbox",
        "aria-label": label,
        "aria-multiline": "true",
        spellcheck: "true",
        class: "cc-writer min-h-44 px-4 py-3 outline-none",
      },
    },
    onUpdate: ({ editor }) => {
      const nextFormat =
        currentFormat.current === "markdown" ? "markdown" : "html";
      callback.current(
        nextFormat === "markdown" ? editor.getMarkdown() : editor.getHTML(),
        nextFormat,
        editor.getJSON(),
      );
    },
  });
  useEffect(() => {
    editor?.setEditable(!disabled, false);
  }, [editor, disabled]);
  const active = useEditorState({
    editor,
    selector: ({ editor }) =>
      editor
        ? {
            bold: editor.isActive("bold"),
            italic: editor.isActive("italic"),
            bullet: editor.isActive("bulletList"),
            ordered: editor.isActive("orderedList"),
            quote: editor.isActive("blockquote"),
            heading: editor.isActive("heading", { level: 2 }),
            link: editor.isActive("link"),
            undo: editor.can().undo(),
            redo: editor.can().redo(),
          }
        : null,
  });
  const [linkOpen, setLinkOpen] = useState(false);
  const [url, setUrl] = useState("");
  const [linkError, setLinkError] = useState("");
  const toolbar = [
    {
      title: "Bold",
      Icon: Bold,
      pressed: active?.bold,
      action: () => editor?.chain().focus().toggleBold().run(),
    },
    {
      title: "Italic",
      Icon: Italic,
      pressed: active?.italic,
      action: () => editor?.chain().focus().toggleItalic().run(),
    },
    {
      title: "Heading",
      Icon: Heading2,
      pressed: active?.heading,
      action: () => editor?.chain().focus().toggleHeading({ level: 2 }).run(),
    },
    {
      title: "Bullet list",
      Icon: List,
      pressed: active?.bullet,
      action: () => editor?.chain().focus().toggleBulletList().run(),
    },
    {
      title: "Numbered list",
      Icon: ListOrdered,
      pressed: active?.ordered,
      action: () => editor?.chain().focus().toggleOrderedList().run(),
    },
    {
      title: "Quote",
      Icon: Quote,
      pressed: active?.quote,
      action: () => editor?.chain().focus().toggleBlockquote().run(),
    },
  ];
  return (
    <div className="overflow-hidden rounded-lg border border-input bg-background focus-within:border-ring focus-within:ring-2 focus-within:ring-ring/20">
      <div
        role="group"
        aria-label={`${label} formatting`}
        className="flex flex-wrap gap-0.5 border-b bg-muted/30 px-2 py-1"
      >
        {toolbar.map(({ title, Icon, pressed, action }) => (
          <Button
            key={title}
            type="button"
            size="icon-sm"
            variant="ghost"
            aria-label={title}
            title={title}
            aria-pressed={!!pressed}
            disabled={!editor || disabled}
            className="aria-pressed:bg-accent"
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => {
              action();
              editor?.view.focus();
            }}
          >
            <Icon className="size-4" />
          </Button>
        ))}
        <Popover open={linkOpen} onOpenChange={setLinkOpen}>
          <PopoverTrigger asChild>
            <Button
              type="button"
              size="icon-sm"
              variant="ghost"
              aria-label="Add or edit link"
              title="Link"
              disabled={!editor || disabled}
              aria-pressed={!!active?.link}
              onClick={() => {
                setUrl(editor?.getAttributes("link").href ?? "");
                setLinkError("");
              }}
            >
              <Link2 className="size-4" />
            </Button>
          </PopoverTrigger>
          <PopoverContent
            className="w-72 space-y-2"
            onCloseAutoFocus={(event) => {
              event.preventDefault();
              editor?.commands.focus();
            }}
          >
            <label htmlFor={`${id}-link`} className="text-sm font-medium">
              Link address
            </label>
            <Input
              id={`${id}-link`}
              value={url}
              placeholder="https://example.com"
              onChange={(event) => setUrl(event.target.value)}
            />
            {linkError && (
              <p role="alert" className="text-xs text-destructive">
                {linkError}
              </p>
            )}
            <div className="flex gap-2">
              <Button
                type="button"
                size="sm"
                onClick={() => {
                  let href = url.trim();
                  if (href && !/^[a-z][a-z\d+.-]*:/i.test(href))
                    href = `https://${href}`;
                  if (href && !/^(https?:\/\/|mailto:)/i.test(href)) {
                    setLinkError("Use an https, http or email address.");
                    return;
                  }
                  if (href)
                    editor
                      ?.chain()
                      .focus()
                      .extendMarkRange("link")
                      .setLink({ href })
                      .run();
                  else
                    editor
                      ?.chain()
                      .focus()
                      .extendMarkRange("link")
                      .unsetLink()
                      .run();
                  setLinkOpen(false);
                }}
              >
                Apply link
              </Button>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={() => {
                  editor?.chain().focus().unsetLink().run();
                  setLinkOpen(false);
                }}
              >
                Remove
              </Button>
            </div>
          </PopoverContent>
        </Popover>
        <div className="mx-1 my-1 border-l" />
        <Button
          type="button"
          size="icon-sm"
          variant="ghost"
          aria-label="Undo"
          title="Undo"
          disabled={!active?.undo || disabled}
          onClick={() => editor?.chain().focus().undo().run()}
        >
          <Undo2 className="size-4" />
        </Button>
        <Button
          type="button"
          size="icon-sm"
          variant="ghost"
          aria-label="Redo"
          title="Redo"
          disabled={!active?.redo || disabled}
          onClick={() => editor?.chain().focus().redo().run()}
        >
          <Redo2 className="size-4" />
        </Button>
      </div>
      {editor ? (
        <EditorContent editor={editor} />
      ) : (
        <div className="min-h-44 p-4 text-sm text-muted-foreground">
          Opening writer…
        </div>
      )}
    </div>
  );
}
