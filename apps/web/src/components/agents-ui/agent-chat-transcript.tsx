"use client";

import { type ComponentProps } from "react";
import {
  type AgentState,
  type ReceivedMessage,
} from "@livekit/components-react";
import { Streamdown } from "streamdown";
import { Bubble, BubbleContent } from "@/components/ui/bubble";
import { Message, MessageContent } from "@/components/ui/message";
import { Marker, MarkerContent, MarkerIcon } from "@/components/ui/marker";
import {
  MessageScroller,
  MessageScrollerButton,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerProvider,
  MessageScrollerViewport,
} from "@/components/ui/message-scroller";
import { useReducedMotion } from "@/hooks/use-reduced-motion";
import { AgentChatIndicator } from "@/components/agents-ui/agent-chat-indicator";

/**
 * Props for the AgentChatTranscript component.
 */
export interface AgentChatTranscriptProps
  extends
    ComponentProps<"div">,
    ComponentProps<typeof MessageScrollerProvider>,
    ComponentProps<typeof MessageScrollerViewport>,
    ComponentProps<typeof MessageScrollerContent> {
  /**
   * Whether to automatically scroll to the bottom of the transcript when new messages are added.
   * @defaultValue true
   */
  autoScroll?: boolean;
  /** Compose persisted messages, checkpoints, and run activity in the transcript. */
  contentClassName?: string;
  /**
   * The scroll anchor to use when auto-scrolling.
   * @defaultValue false
   */
  scrollAnchor?: boolean | "user" | "other" | "any";
  /**
   * The scroll button render function
   */
  scrollButtonRender?: ComponentProps<typeof MessageScrollerButton>["render"];
  /**
   * The scroll button behavior
   */
  scrollButtonBehavior?: ComponentProps<
    typeof MessageScrollerButton
  >["behavior"];
  /**
   * The scroll button direction
   */
  scrollButtonDirection?: ComponentProps<
    typeof MessageScrollerButton
  >["direction"];
  /**
   * The current state of the agent. When 'thinking', displays a loading indicator.
   */
  agentState?: AgentState;
  /**
   * Array of messages to display in the transcript.
   * @defaultValue []
   */
  messages?: ReceivedMessage[];
  /**
   * Additional CSS class names to apply to the conversation container.
   */
  className?: string;
}

/**
 * A chat transcript component that displays a conversation between the user and agent.
 * Shows messages with timestamps and origin indicators, plus a thinking indicator
 * when the agent is processing.
 *
 * @extends ComponentProps<'div'>, ComponentProps<typeof MessageScrollerProvider>, ComponentProps<typeof MessageScrollerViewport>, ComponentProps<typeof MessageScrollerContent>
 *
 *
 * @example
 * ```tsx
 * <AgentChatTranscript
 *   agentState={agentState}
 *   messages={chatMessages}
 * />
 * ```
 */
export function AgentChatTranscript({
  scrollAnchor,
  autoScroll = true,
  scrollMargin,
  scrollEdgeThreshold,
  preserveScrollOnPrepend,
  scrollPreviousItemPeek,
  defaultScrollPosition = "last-anchor",
  scrollButtonRender,
  scrollButtonBehavior,
  scrollButtonDirection,
  spacerClassName,
  agentState,
  messages = [],
  className,
  contentClassName,
  children,
  ...props
}: AgentChatTranscriptProps) {
  const reducedMotion = useReducedMotion();
  return (
    <MessageScrollerProvider
      autoScroll={autoScroll}
      scrollMargin={scrollMargin}
      defaultScrollPosition={defaultScrollPosition}
      scrollEdgeThreshold={scrollEdgeThreshold}
      scrollPreviousItemPeek={scrollPreviousItemPeek}
    >
      <MessageScroller className={className} {...props}>
        <MessageScrollerViewport
          aria-label="Conversation messages"
          className="focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring"
          preserveScrollOnPrepend={preserveScrollOnPrepend}
        >
          <MessageScrollerContent
            className={contentClassName}
            spacerClassName={spacerClassName}
            aria-busy={agentState === "thinking"}
          >
            {children ??
              messages.map((receivedMessage) => {
                const { id, timestamp, from, message } = receivedMessage;
                const time = new Date(timestamp);
                const isUser = from?.isLocal;
                const locale =
                  typeof navigator !== "undefined"
                    ? navigator.language
                    : "en-US";
                const title = time.toLocaleTimeString(locale, {
                  timeStyle: "full",
                });
                let _scrollAnchor = false;

                if (
                  scrollAnchor === "any" ||
                  (scrollAnchor === "user" && isUser) ||
                  (scrollAnchor === "other" && !isUser)
                ) {
                  _scrollAnchor = true;
                }

                return (
                  <MessageScrollerItem
                    key={id}
                    messageId={id}
                    scrollAnchor={_scrollAnchor}
                  >
                    <Message align={isUser ? "end" : "start"} title={title}>
                      <MessageContent>
                        <Bubble
                          align={isUser ? "end" : "start"}
                          variant={isUser ? "secondary" : "ghost"}
                        >
                          <BubbleContent>
                            <Streamdown>{message}</Streamdown>
                          </BubbleContent>
                        </Bubble>
                      </MessageContent>
                    </Message>
                  </MessageScrollerItem>
                );
              })}

            {/* Agent is thinking indicator */}
            {agentState === "thinking" && (
              <MessageScrollerItem>
                <Marker role="status">
                  <MarkerIcon>
                    <AgentChatIndicator size="sm" />
                  </MarkerIcon>
                  <MarkerContent className="shimmer">Thinking...</MarkerContent>
                </Marker>
              </MessageScrollerItem>
            )}
          </MessageScrollerContent>
        </MessageScrollerViewport>

        {/* Scroll to bottom button */}
        <MessageScrollerButton
          variant="outline"
          className="rounded-full"
          render={scrollButtonRender}
          aria-label="Scroll to latest message"
          behavior={reducedMotion ? "instant" : scrollButtonBehavior}
          direction={scrollButtonDirection}
        />
      </MessageScroller>
    </MessageScrollerProvider>
  );
}
