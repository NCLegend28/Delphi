import { useRef, useState } from "react";
import { useChatStore } from "../../store/chatStore";

/**
 * InputBar — textarea + send button.
 *
 *   Enter         → send (calls onSubmit)
 *   Shift+Enter   → newline (default textarea behavior)
 *   Esc           → blur (lets keyboard shortcuts re-take focus)
 *
 * Auto-grows up to ~6 lines, then scrolls internally.
 */
export function InputBar({ onSubmit }) {
  const [value, setValue] = useState("");
  const taRef = useRef(null);
  const isStreaming = useChatStore((s) => s.isStreaming);

  const submit = () => {
    const text = value.trim();
    if (!text || isStreaming) return;
    setValue("");
    autosize(taRef.current, "");
    onSubmit(text);
  };

  const onKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    } else if (e.key === "Escape") {
      taRef.current?.blur();
    }
  };

  const onChange = (e) => {
    setValue(e.target.value);
    autosize(e.target, e.target.value);
  };

  return (
    <form
      className="flex items-end gap-2 border-t border-[var(--color-border-glow)] px-3 py-2"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <span className="pb-1 font-mono text-xs text-[var(--color-accent-cyan)] text-glow-cyan">
        &gt;
      </span>
      <textarea
        ref={taRef}
        rows={1}
        value={value}
        onChange={onChange}
        onKeyDown={onKeyDown}
        placeholder={isStreaming ? "delphi is responding…" : "message delphi…"}
        disabled={isStreaming}
        className="max-h-40 flex-1 resize-none bg-transparent font-mono text-sm leading-relaxed text-[var(--color-text-primary)] placeholder:text-[var(--color-text-dim)] focus:outline-none disabled:opacity-50"
      />
      <button
        type="submit"
        disabled={isStreaming || !value.trim()}
        className="rounded-sm border border-[var(--color-border-strong)] px-3 py-1 font-display text-[10px] tracking-[0.3em] text-[var(--color-accent-cyan)] transition hover:bg-[var(--color-accent-cyan)]/10 hover:shadow-[var(--shadow-glow-cyan)] disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:shadow-none"
      >
        SEND
      </button>
    </form>
  );
}

function autosize(el, value) {
  if (!el) return;
  el.style.height = "auto";
  // Use scrollHeight to fit content; cap is enforced by max-h-40 in CSS.
  el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  if (!value) el.style.height = "";
}
