/**
 * MessageBubble — one message in the COMMS feed.
 *
 * `user` bubbles are right-aligned with a cyan-tinted border; `delphi` bubbles
 * are left-aligned on a raised surface and animate a caret while streaming.
 */
export function MessageBubble({ role, content, streaming }) {
  const isUser = role === "user";
  return (
    <div className={`flex gap-2 animate-fade-up ${isUser ? "justify-end" : "justify-start"}`}>
      {!isUser && <Tag>DELPHI</Tag>}
      <div
        className={[
          "max-w-[75%] px-3 py-1.5 text-[11px] leading-relaxed break-words",
          isUser
            ? "rounded-[4px_0_4px_4px] border border-[var(--color-accent-cyan)]/30 bg-[var(--color-accent-cyan)]/[0.08] text-[var(--color-text-primary)]"
            : "rounded-[0_4px_4px_4px] border border-[var(--color-border-dim)] bg-[var(--color-bg-raised)] text-[var(--color-text-muted)]",
        ].join(" ")}
      >
        <span className="whitespace-pre-wrap">{content}</span>
        {streaming && <Caret />}
      </div>
      {isUser && <Tag>YOU</Tag>}
    </div>
  );
}

function Tag({ children }) {
  return (
    <span className="mb-0.5 shrink-0 self-end text-[8px] tracking-[0.15em] text-[var(--color-text-dim)]">
      {children}
    </span>
  );
}

function Caret() {
  return (
    <span
      aria-hidden="true"
      className="ml-0.5 inline-block h-3 w-[7px] -translate-y-0.5 bg-[var(--color-accent-cyan)] align-middle animate-blink"
    />
  );
}
