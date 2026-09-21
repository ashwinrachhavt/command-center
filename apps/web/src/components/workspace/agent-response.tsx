"use client";

import { MessageResponse } from "@/components/ai-elements/message";

export function AgentResponse({ children }: { children: string }) {
  return (
    <MessageResponse
      mode="static"
      skipHtml
      disallowedElements={["img", "iframe", "script", "style"]}
      className="text-base leading-7 [&_a:visited]:text-primary/70"
    >
      {children}
    </MessageResponse>
  );
}
