import { useEffect, useRef } from "react";
import Prism from "prismjs";
import "prismjs/components/prism-python";
import "prismjs/components/prism-json";
import "prismjs/components/prism-markdown";
import "prismjs/components/prism-bash";
import { useChatStore } from "../../store/chatStore";
import { useDelphiStore } from "../../store/delphiStore";

/**
 * OutputCanvas — the live render surface.
 *
 * Mirrors the current exchange (the "dual-render trick" from the mission
 * control mockup): the moment you send, your QUERY appears here and Delphi's
 * response streams in beneath it, in real time, fed by the same SSE deltas
 * that drive COMMS. When the model pushes a `[PREVIEW:…]` directive, the
 * built/read artifact renders below the output. Empty state is the AWAITING
 * glyph over the grid.
 */
export function OutputCanvas() {
  const preview = useDelphiStore((s) => s.preview);
  const messages = useChatStore((s) => s.messages);
  const isStreaming = useChatStore((s) => s.isStreaming);
  const streamingId = useChatStore((s) => s.streamingId);

  const lastUser = findLast(messages, (m) => m.role === "user");
  const lastAssistant = findLast(messages, (m) => m.role === "assistant");
  const hasExchange = Boolean(lastUser || lastAssistant);
  // True between send and the first byte (assistant bubble not created yet),
  // or while the latest assistant message is the one still streaming.
  const awaitingReply = isStreaming && (lastAssistant == null || lastAssistant.id === streamingId);

  const status = preview
    ? "PREVIEW"
    : isStreaming
      ? "STREAMING"
      : hasExchange
        ? "OUTPUT"
        : "IDLE";

  // Follow the stream — scroll to the newest output as it grows.
  const scrollRef = useRef(null);
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lastAssistant?.content, lastUser?.id, preview, awaitingReply]);

  return (
    <div className="panel relative flex h-full min-h-0 flex-col overflow-hidden">
      <div className="panel-header">
        <span
          className="h-[5px] w-[5px] rounded-full bg-[var(--color-accent-cyan)]"
          style={{ boxShadow: "0 0 6px var(--color-accent-cyan)" }}
        />
        <span className="text-[9px] tracking-[0.2em] text-[var(--color-text-dim)]">OUTPUT CANVAS</span>
        <span className="ml-auto text-[9px] tracking-[0.1em] text-[var(--color-text-dim)]">{status}</span>
      </div>

      <div className="bg-grid relative min-h-0 flex-1 overflow-hidden">
        {hasExchange || preview ? (
          <div ref={scrollRef} className="relative z-10 mx-auto flex h-full max-w-[760px] flex-col gap-2 overflow-y-auto p-5">
            {lastUser && <QueryBlock text={lastUser.content} />}
            {(lastAssistant || awaitingReply) && (
              <OutputBlock text={lastAssistant?.content ?? ""} streaming={awaitingReply} />
            )}
            {preview && <PreviewBlock preview={preview} />}
          </div>
        ) : (
          <div className="flex h-full items-center justify-center">
            <Awaiting />
          </div>
        )}
      </div>
    </div>
  );
}

function QueryBlock({ text }) {
  return (
    <div className="rounded-[0_4px_4px_0] border border-[var(--color-border-dim)] border-l-2 border-l-[var(--color-accent-violet)] bg-[var(--color-bg-surface)]/70 px-4 py-3">
      <span className="mb-1.5 block text-[8px] tracking-[0.2em] text-[var(--color-accent-violet)]">QUERY ──</span>
      <span className="whitespace-pre-wrap break-words text-xs leading-relaxed text-[var(--color-text-primary)]">
        {text}
      </span>
    </div>
  );
}

function OutputBlock({ text, streaming }) {
  return (
    <div className="rounded-[0_4px_4px_0] border border-[var(--color-border-dim)] border-l-2 border-l-[var(--color-accent-cyan)] bg-[var(--color-bg-surface)]/80 px-4 py-3">
      <span className="mb-1.5 block text-[8px] tracking-[0.2em] text-[var(--color-accent-cyan)]">DELPHI OUTPUT ──</span>
      <span className="whitespace-pre-wrap break-words text-xs leading-relaxed text-[var(--color-text-primary)]">
        {text}
        {streaming && <Caret />}
      </span>
    </div>
  );
}

function Caret() {
  return (
    <span
      aria-hidden="true"
      className="ml-0.5 inline-block h-[13px] w-[7px] translate-y-0.5 bg-[var(--color-accent-cyan)] align-middle animate-blink"
    />
  );
}

function Awaiting() {
  return (
    <div className="relative z-10 flex flex-col items-center gap-3 opacity-50">
      <div className="relative flex h-12 w-12 items-center justify-center rounded-full border border-[var(--color-border-strong)]">
        <span className="absolute -inset-1.5 rounded-full border border-[var(--color-border-dim)] animate-spin-slow" />
        <span className="absolute -inset-3 rounded-full border border-dashed border-[var(--color-border-dim)] animate-spin-slower" />
        <span
          className="h-2 w-2 rounded-full bg-[var(--color-accent-cyan)]"
          style={{ boxShadow: "0 0 12px var(--color-accent-cyan)" }}
        />
      </div>
      <span className="text-[10px] tracking-[0.25em] text-[var(--color-text-faint)]">AWAITING</span>
      <span className="text-[9px] tracking-[0.1em] text-[var(--color-text-faint)]">
        Delphi will render output here as it works.
      </span>
    </div>
  );
}

function PreviewBlock({ preview }) {
  const label =
    preview.kind === "code" ? `CODE · ${preview.language ?? "PLAIN"}`.toUpperCase() : "DOCUMENT";
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <span className="text-[8px] tracking-[0.2em] text-[var(--color-accent-amber)]">{label} ──</span>
        <span className="h-px flex-1 bg-[var(--color-border-dim)]" />
      </div>
      <div className="overflow-auto rounded-sm border border-[var(--color-border-dim)] border-l-2 border-l-[var(--color-accent-amber)] bg-[var(--color-bg-surface)]/80">
        {preview.kind === "code" ? (
          <CodeBlock language={preview.language} content={preview.content} />
        ) : (
          <div className="whitespace-pre-wrap break-words p-4 text-xs leading-relaxed text-[var(--color-text-primary)]">
            {preview.content}
          </div>
        )}
      </div>
    </div>
  );
}

function CodeBlock({ language, content }) {
  const ref = useRef(null);
  useEffect(() => {
    if (ref.current) Prism.highlightElement(ref.current);
  }, [content, language]);
  return (
    <pre className="m-0 overflow-auto bg-transparent p-4 text-xs leading-relaxed">
      <code ref={ref} className={`language-${language || "plaintext"} font-mono`}>
        {content}
      </code>
    </pre>
  );
}

/** Last element matching a predicate, without mutating the source array. */
function findLast(arr, pred) {
  for (let i = arr.length - 1; i >= 0; i--) {
    if (pred(arr[i])) return arr[i];
  }
  return null;
}
