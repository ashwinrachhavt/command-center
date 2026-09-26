"use client";

import type { ComponentProps } from "react";
import { Bubble, BubbleContent } from "@/components/ui/bubble";
import { Message, MessageContent } from "@/components/ui/message";
import { MessageScrollerItem } from "@/components/ui/message-scroller";

// LiveKit's transcript composition, with our persisted messages and rich content.
export function ChatMessage({
  from,
  messageId,
  children,
  ...props
}: ComponentProps<"div"> & {
  from: "user" | "assistant";
  messageId?: string;
}) {
  return (
    // Keep actual heights for rich answers so instant scrolling lands accurately.
    <MessageScrollerItem
      messageId={messageId}
      className="[content-visibility:visible]"
    >
      <Message align={from === "user" ? "end" : "start"} {...props}>
        <MessageContent>{children}</MessageContent>
      </Message>
    </MessageScrollerItem>
  );
}

export function ChatMessageBody({
  from,
  ...props
}: ComponentProps<"div"> & { from: "user" | "assistant" }) {
  return (
    <Bubble
      align={from === "user" ? "end" : "start"}
      variant={from === "user" ? "secondary" : "ghost"}
    >
      <BubbleContent {...props} />
    </Bubble>
  );
}
