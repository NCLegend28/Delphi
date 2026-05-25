/**
 * MessageBubble — one message in the chat rail.
 *
 * `user` bubbles are right-aligned, muted-cyan border, no glow.
 * `assistant` bubbles are left-aligned, accent-cyan border, soft glow,
 * and animate a caret while streaming.
 */
export function MessageBubble({ role, content, ts, streaming }) {
  const isUser = role === "user";
  return (
    <div className={`flex w-full ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={[
          "max-w-[85%] rounded-sm border px-3 py-2",
          isUser
            ? "border-[var(--color-border-glow)] bg-[var(--color-bg-panel-elev)]/60"
            : "border-[var(--color-border-strong)] bg-[var(--color-bg-panel)]/80 shadow-[0_0_24px_-12px_rgba(0,212,255,0.6)]",
        ].join(" ")}
      >
        <div className="mb-1 flex items-center justify-between gap-3">
          <span
            className={[
              "font-display text-[10px] tracking-[0.3em]",
              isUser
                ? "text-[var(--color-text-muted)]"
                : "text-[var(--color-accent-cyan)]",
            ].join(" ")}
          >
            {isUser ? "YOU" : "DELPHI"}
          </span>
          <span className="font-mono text-[9px] text-[var(--color-text-dim)]">
            {formatTs(ts)}
          </span>
        </div>
        <div className="whitespace-pre-wrap break-words font-mono text-sm leading-relaxed text-[var(--color-text-primary)]">
          {content}
          {streaming && <Caret />}
        </div>
      </div>
    </div>
  );
}

function Caret() {
  return (
    <span
      aria-hidden="true"
      className="ml-0.5 inline-block h-3 w-1.5 -translate-y-0.5 bg-[var(--color-accent-cyan)] align-middle animate-pulse-soft"
    />
  );
}

function formatTs(ts) {
  if (!ts) return "";
  const d = new Date(ts);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
