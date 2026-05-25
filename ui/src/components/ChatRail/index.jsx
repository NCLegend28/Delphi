import { useEffect, useRef } from "react";
import { useChatStore } from "../../store/chatStore";
import { useDelphiStream } from "../../hooks/useDelphiStream";
import { MessageBubble } from "./MessageBubble";
import { InputBar } from "./InputBar";

/**
 * ChatRail — the COMMS channel. How you talk to Delphi.
 *
 * Reads message history from chatStore, sends new messages via
 * useDelphiStream. Auto-scrolls to the latest message on append (unless the
 * operator has scrolled up to read earlier traffic).
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
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    if (nearBottom) el.scrollTop = el.scrollHeight;
  }, [messages, isStreaming]);

  return (
    <div className="panel flex h-full min-h-0 w-full flex-col">
      <div className="panel-header">
        <span
          className={`h-[5px] w-[5px] rounded-full ${
            isStreaming ? "bg-[var(--color-accent-amber)] animate-pulse-fast" : "bg-[var(--color-accent-cyan)] animate-pulse-soft"
          }`}
          style={{ boxShadow: isStreaming ? "0 0 6px var(--color-accent-amber)" : "0 0 6px var(--color-accent-cyan)" }}
        />
        <span className="text-[9px] tracking-[0.2em] text-[var(--color-text-dim)]">COMMS</span>
        <span className="ml-auto text-[9px] tracking-[0.1em] text-[var(--color-text-dim)]">
          {isStreaming ? "RECEIVING" : "READY"}
        </span>
      </div>

      {error && (
        <div className="border-b border-[var(--color-accent-red)] bg-[var(--color-accent-red)]/10 px-3.5 py-1.5 text-[10px] tracking-[0.08em] text-[var(--color-accent-red)]">
          FAULT: {error}
        </div>
      )}

      <div ref={scrollerRef} className="flex min-h-0 flex-1 flex-col gap-1.5 overflow-y-auto px-3.5 py-2">
        {messages.length === 0 && !error && (
          <SystemLine>delphi online · awaiting input</SystemLine>
        )}
        {messages.map((m) => (
          <MessageBubble
            key={m.id}
            role={m.role}
            content={m.content}
            streaming={m.id === streamingId}
          />
        ))}
      </div>

      <InputBar onSubmit={send} />
    </div>
  );
}

function SystemLine({ children }) {
  return (
    <div className="flex items-center justify-center gap-3 text-[10px] tracking-[0.2em] text-[var(--color-text-faint)]">
      <span className="h-px flex-1 bg-[var(--color-border-dim)]" />
      <span>{children}</span>
      <span className="h-px flex-1 bg-[var(--color-border-dim)]" />
    </div>
  );
}
