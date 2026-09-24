"use client";

import { MessageResponse } from "@/components/ai-elements/message";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { memo, useRef } from "react";
import type { LinkSafetyConfig, LinkSafetyModalProps } from "streamdown";
import { useReducedMotion } from "@/hooks/use-reduced-motion";

function SourceLinkDialog({
  isOpen,
  onClose,
  onConfirm,
  url,
}: LinkSafetyModalProps) {
  const returnFocus = useRef<HTMLElement | null>(null);
  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        onOpenAutoFocus={() => {
          returnFocus.current = document.activeElement as HTMLElement;
        }}
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          returnFocus.current?.focus();
        }}
      >
        <DialogHeader>
          <DialogTitle>Open source</DialogTitle>
          <DialogDescription>This link opens in a new tab.</DialogDescription>
        </DialogHeader>
        <p className="break-all rounded-md bg-muted p-3 text-sm">{url}</p>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            onClick={() => {
              onConfirm();
              onClose();
            }}
          >
            Open link
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

const linkSafety: LinkSafetyConfig = {
  enabled: true,
  onLinkCheck: (url) => /^\/(?![\/\\])/.test(url),
  renderModal: (props) => <SourceLinkDialog {...props} />,
};

const streamAnimation = {
  animation: "fadeIn",
  duration: 120,
  easing: "ease-out",
  sep: "word",
  stagger: 8,
  maxBacklogMs: 80,
} as const;
const disallowedElements = ["img", "iframe", "script", "style"];

export const AgentResponse = memo(function AgentResponse({
  children,
  streaming = false,
}: {
  children: string;
  streaming?: boolean;
}) {
  const reducedMotion = useReducedMotion();
  return (
    <div aria-busy={streaming}>
      <MessageResponse
        mode={streaming ? "streaming" : "static"}
        parseIncompleteMarkdown={streaming}
        isAnimating={streaming && !reducedMotion}
        animated={streamAnimation}
        skipHtml
        disallowedElements={disallowedElements}
        linkSafety={linkSafety}
        className="text-sm leading-6 [&_a:visited]:text-primary/70"
      >
        {children}
      </MessageResponse>
    </div>
  );
});
