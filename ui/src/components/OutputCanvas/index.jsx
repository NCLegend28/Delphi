import { useEffect, useRef, useState } from "react";
import Prism from "prismjs";
import "prismjs/components/prism-python";
import "prismjs/components/prism-json";
import "prismjs/components/prism-markdown";
import "prismjs/components/prism-bash";
import { useChatStore } from "../../store/chatStore";
import { useDelphiStore } from "../../store/delphiStore";
import { useTypewriter } from "../../hooks/useTypewriter";

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

  // During the "send → first chunk" gap, ``lastAssistant`` still points at the
  // *previous* turn's reply. Showing it would mean staring at stale text
  // until the new bubble materializes. Instead, blank the canvas as soon as
  // the user hits send, so the typewriter starts from empty on the new turn.
  const currentAssistant =
    isStreaming && lastAssistant && lastAssistant.id !== streamingId ? null : lastAssistant;

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
  }, [currentAssistant?.content, lastUser?.id, preview, awaitingReply]);

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
            {(currentAssistant || awaitingReply) && (
              // ``key`` ensures the typewriter resets cleanly per turn —
              // when the assistant id changes (or the canvas blanks while
              // awaiting), React remounts ``OutputBlock`` and its
              // ``displayed`` state begins at the empty string.
              <OutputBlock
                key={currentAssistant?.id ?? `awaiting-${lastUser?.id ?? "none"}`}
                text={currentAssistant?.content ?? ""}
                streaming={awaitingReply}
              />
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
  // Reveal the assistant's text with a typewriter cadence so chunked SSE
  // arrivals feel like a continuous stream rather than block-paste updates.
  // The caret stays visible while ``streaming`` is true OR while the reveal
  // is still catching up to the full text after the stream finished.
  const displayed = useTypewriter(text);
  const stillRevealing = displayed.length < text.length;
  return (
    <div className="rounded-[0_4px_4px_0] border border-[var(--color-border-dim)] border-l-2 border-l-[var(--color-accent-cyan)] bg-[var(--color-bg-surface)]/80 px-4 py-3">
      <span className="mb-1.5 block text-[8px] tracking-[0.2em] text-[var(--color-accent-cyan)]">DELPHI OUTPUT ──</span>
      <span className="whitespace-pre-wrap break-words text-xs leading-relaxed text-[var(--color-text-primary)]">
        {displayed}
        {(streaming || stillRevealing) && <Caret />}
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
    preview.kind === "code"
      ? `CODE · ${preview.language ?? "PLAIN"}`.toUpperCase()
      : preview.kind === "media"
        ? "MEDIA"
        : "DOCUMENT";
  // Media previews are external references (URL or data URL) — download/copy
  // affordances don't apply the same way; skip the toolbar for them.
  const hasToolbar = preview.kind === "code" || preview.kind === "document";
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <span className="text-[8px] tracking-[0.2em] text-[var(--color-accent-amber)]">{label} ──</span>
        <span className="h-px flex-1 bg-[var(--color-border-dim)]" />
        {hasToolbar && <PreviewToolbar preview={preview} />}
      </div>
      <div className="overflow-auto rounded-sm border border-[var(--color-border-dim)] border-l-2 border-l-[var(--color-accent-amber)] bg-[var(--color-bg-surface)]/80">
        {preview.kind === "code" ? (
          <CodeBlock language={preview.language} content={preview.content} />
        ) : preview.kind === "media" ? (
          <MediaBlock url={preview.url} alt={preview.alt} mimeType={preview.mimeType} />
        ) : (
          <div className="whitespace-pre-wrap break-words p-4 text-xs leading-relaxed text-[var(--color-text-primary)]">
            {preview.content}
          </div>
        )}
      </div>
    </div>
  );
}

/** Download + Copy affordances for the preview pane.
 *
 * Both actions are purely client-side — the preview body already lives in
 * memory. Save-to-vault is a separate (deferred) task because it needs a
 * backend endpoint with auth and path validation. */
function PreviewToolbar({ preview }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(preview.content ?? "");
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard API can fail in insecure contexts or when permission is
      // denied; the failure is silent so the UI doesn't show a useless
      // error toast. The button stays clickable for the user to retry.
    }
  };

  const handleDownload = () => {
    const { content = "", kind, language } = preview;
    const ext = downloadExtension(kind, language);
    const filename = `delphi-preview-${timestampSlug()}.${ext}`;
    const blob = new Blob([content], { type: mimeForExt(ext) });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    // Some browsers (Safari) need the anchor mounted to honor `download`.
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    // Defer revocation a tick so the click has a chance to dispatch.
    setTimeout(() => URL.revokeObjectURL(url), 0);
  };

  return (
    <div className="ml-1 flex items-center gap-1">
      <ToolbarButton onClick={handleCopy} ariaLabel="Copy preview to clipboard">
        {copied ? "COPIED" : "COPY"}
      </ToolbarButton>
      <ToolbarButton onClick={handleDownload} ariaLabel="Download preview as a file">
        DOWNLOAD
      </ToolbarButton>
    </div>
  );
}

function ToolbarButton({ children, onClick, ariaLabel }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={ariaLabel}
      className="rounded-sm border border-[var(--color-border-dim)] bg-[var(--color-bg-surface)]/60 px-2 py-0.5 font-mono text-[8px] tracking-[0.2em] text-[var(--color-text-dim)] transition-colors hover:border-[var(--color-accent-amber)] hover:text-[var(--color-accent-amber)]"
    >
      {children}
    </button>
  );
}

/** Map a preview kind + language to a sensible file extension. */
function downloadExtension(kind, language) {
  if (kind === "document") return "md";
  if (kind !== "code") return "txt";
  const lang = (language || "").toLowerCase();
  const table = {
    python: "py",
    javascript: "js",
    typescript: "ts",
    jsx: "jsx",
    tsx: "tsx",
    json: "json",
    bash: "sh",
    shell: "sh",
    markdown: "md",
    yaml: "yaml",
    yml: "yaml",
    html: "html",
    css: "css",
    sql: "sql",
    go: "go",
    rust: "rs",
  };
  return table[lang] ?? "txt";
}

function mimeForExt(ext) {
  if (ext === "md") return "text/markdown";
  if (ext === "json") return "application/json";
  if (ext === "html") return "text/html";
  if (ext === "css") return "text/css";
  return "text/plain";
}

/** ISO-ish timestamp safe for filenames: 2026-06-01_15-42-08. */
function timestampSlug() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `_${pad(d.getHours())}-${pad(d.getMinutes())}-${pad(d.getSeconds())}`
  );
}

function MediaBlock({ url, alt, mimeType }) {
  const [failed, setFailed] = useState(false);
  const isImage = typeof mimeType === "string" && mimeType.startsWith("image/");
  // When mimeType is unknown, optimistically attempt image render; an onError
  // fallback handles unsupported / broken sources.
  const supported = isImage || !mimeType;
  const caption = alt || "media";

  if (!url || failed || !supported) {
    return (
      <div className="bg-grid flex items-center justify-center p-6">
        <span
          role="status"
          aria-label="media unavailable"
          className="rounded-full border border-[var(--color-border-strong)] bg-[var(--color-bg-surface)]/90 px-3 py-1 font-mono text-[10px] tracking-[0.2em] text-[var(--color-text-faint)]"
        >
          MEDIA UNAVAILABLE · {caption}
        </span>
      </div>
    );
  }
  return (
    <figure className="bg-grid flex flex-col items-center gap-2 p-3">
      <img
        src={url}
        alt={caption}
        onError={() => setFailed(true)}
        className="block max-h-[60vh] max-w-full"
        style={{ objectFit: "contain" }}
      />
      <figcaption className="font-mono text-[10px] tracking-[0.15em] text-[var(--color-text-faint)]">
        {caption}
      </figcaption>
    </figure>
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
