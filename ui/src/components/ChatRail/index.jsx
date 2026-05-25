import { useEffect, useRef } from "react";
import { useChatStore } from "../../store/chatStore";
import { useDelphiStream } from "../../hooks/useDelphiStream";
import { MessageBubble } from "./MessageBubble";
import { InputBar } from "./InputBar";

/**
 * ChatRail — how you talk to Delphi.
 *
 * Reads message history from chatStore, sends new messages via
 * useDelphiStream. Auto-scrolls to the latest message on append.
 */
export function ChatRail() {
  const messages = useChatStore((s) => s.messages);
  const isStreaming = useChatStore((s) => s.isStreaming);
  const streamingId = useChatStore((s) => s.streamingId);
  const error = useChatStore((s) => s.error);
  const { send } = useDelphiStream();

  const scrollerRef = useRef(null);
  useEffect(() => {
    const el = scrollerRef.current;
    if (!el) return;
    // Only auto-scroll if the user is already near the bottom — preserves
    // scroll position when they're reading earlier messages.
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    if (nearBottom) el.scrollTop = el.scrollHeight;
  }, [messages, isStreaming]);

  return (
    <div className="panel relative flex h-full w-full flex-col rounded-sm">
      <header className="flex items-center justify-between border-b border-[var(--color-border-glow)] px-4 py-2">
        <div className="flex items-center gap-2">
          <span
            className={`h-1.5 w-1.5 rounded-full ${
              isStreaming
                ? "bg-[var(--color-accent-amber)] shadow-[0_0_6px_rgba(255,149,0,0.8)] animate-pulse-soft"
                : "bg-[var(--color-accent-cyan)] animate-pulse-soft"
            }`}
          />
          <span className="font-display text-xs tracking-[0.3em] text-[var(--color-text-muted)]">
            CHAT
          </span>
        </div>
        <span className="font-mono text-[10px] uppercase tracking-widest text-[var(--color-text-dim)]">
          ⌘K to focus · esc to collapse preview
        </span>
      </header>

      <div
        ref={scrollerRef}
        className="flex-1 space-y-3 overflow-y-auto px-4 py-3"
      >
        {messages.length === 0 && (
          <SystemLine>delphi online · awaiting input</SystemLine>
        )}
        {messages.map((m) => (
          <MessageBubble
            key={m.id}
            role={m.role}
            content={m.content}
            ts={m.ts}
            streaming={m.id === streamingId}
          />
        ))}
        {error && <ErrorLine message={error} />}
      </div>

      <InputBar onSubmit={send} />
    </div>
  );
}

function SystemLine({ children }) {
  return (
    <div className="flex items-center justify-center gap-3 font-mono text-[10px] uppercase tracking-widest text-[var(--color-text-dim)]">
      <span className="h-px flex-1 bg-[var(--color-border-glow)]" />
      <span>{children}</span>
      <span className="h-px flex-1 bg-[var(--color-border-glow)]" />
    </div>
  );
}

function ErrorLine({ message }) {
  return (
    <div className="rounded-sm border border-[var(--color-accent-amber)]/40 bg-[var(--color-accent-amber)]/5 px-3 py-2 font-mono text-xs text-[var(--color-accent-amber)] text-glow-amber">
      {message}
    </div>
  );
}
