import { useEffect, useRef, useState } from "react";
import { useChatStore } from "../../store/chatStore";

/**
 * InputBar — prompt mark + auto-growing textarea + SEND.
 *
 *   Enter         → send (calls onSubmit)
 *   Shift+Enter   → newline
 *   Esc           → blur
 *
 * Listens for the window `delphi:focus-input` event (dispatched by the ⌘K
 * shortcut in App) so the operator can jump to the prompt from anywhere.
 */
export function InputBar({ onSubmit }) {
  const [value, setValue] = useState("");
  const taRef = useRef(null);
  const isStreaming = useChatStore((s) => s.isStreaming);

  useEffect(() => {
    const focus = () => taRef.current?.focus();
    window.addEventListener("delphi:focus-input", focus);
    return () => window.removeEventListener("delphi:focus-input", focus);
  }, []);

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
      className="flex items-center gap-2 border-t border-[var(--color-border-dim)] px-3.5 py-2"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <span className="shrink-0 text-xs text-[var(--color-accent-cyan)] text-glow-cyan">&gt;</span>
      <textarea
        ref={taRef}
        rows={1}
        value={value}
        onChange={onChange}
        onKeyDown={onKeyDown}
        placeholder={isStreaming ? "delphi is responding…" : "message delphi…"}
        disabled={isStreaming}
        autoComplete="off"
        spellCheck={false}
        className="max-h-32 flex-1 resize-none bg-transparent text-xs leading-relaxed tracking-[0.04em] text-[var(--color-text-primary)] caret-[var(--color-accent-cyan)] placeholder:text-[var(--color-text-faint)] focus:outline-none disabled:opacity-40"
      />
      <button
        type="submit"
        disabled={isStreaming || !value.trim()}
        className="shrink-0 border border-[var(--color-border-strong)] px-3 py-[5px] text-[9px] tracking-[0.2em] text-[var(--color-text-muted)] transition hover:border-[var(--color-accent-cyan)] hover:bg-[var(--color-accent-cyan)]/10 hover:text-[var(--color-accent-cyan)] hover:shadow-[var(--shadow-glow-cyan)] disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:border-[var(--color-border-strong)] disabled:hover:bg-transparent disabled:hover:text-[var(--color-text-muted)] disabled:hover:shadow-none"
      >
        SEND
      </button>
    </form>
  );
}

function autosize(el, value) {
  if (!el) return;
  el.style.height = "auto";
  el.style.height = `${Math.min(el.scrollHeight, 128)}px`;
  if (!value) el.style.height = "";
}
