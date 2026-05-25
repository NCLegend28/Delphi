import { useEffect, useRef } from "react";
import Prism from "prismjs";
import "prismjs/components/prism-python";
import "prismjs/components/prism-json";
import "prismjs/components/prism-markdown";
import "prismjs/components/prism-bash";
import { useChatStore } from "../../store/chatStore";
import { useDelphiStore } from "../../store/delphiStore";

/**
 * OutputCanvas — the "what Delphi is rendering" zone.
 *
 * Shows the directive-pushed preview (`[PREVIEW:code:…]…[/PREVIEW]` parsed in
 * useDelphiStream) when one exists; otherwise the awaiting glyph over the grid
 * backdrop. This is the React equivalent of the mission-control OUTPUT CANVAS,
 * wired to Delphi's real preview protocol rather than mirroring raw stream text.
 */
export function OutputCanvas() {
  const preview = useDelphiStore((s) => s.preview);
  const isStreaming = useChatStore((s) => s.isStreaming);

  const status = preview ? "PREVIEW" : isStreaming ? "STREAMING" : "IDLE";

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

      <div className="bg-grid relative flex min-h-0 flex-1 items-center justify-center overflow-hidden">
        {preview ? (
          <PreviewView preview={preview} />
        ) : (
          <Awaiting />
        )}
      </div>
    </div>
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

function PreviewView({ preview }) {
  const label =
    preview.kind === "code" ? `CODE · ${preview.language ?? "PLAIN"}`.toUpperCase() : "DOCUMENT";
  return (
    <div className="relative z-10 flex h-full w-full max-w-[760px] flex-col gap-2 p-5">
      <div className="flex items-center gap-2">
        <span className="text-[8px] tracking-[0.2em] text-[var(--color-accent-cyan)]">{label}</span>
        <span className="h-px flex-1 bg-[var(--color-border-dim)]" />
      </div>
      <div className="min-h-0 flex-1 overflow-auto rounded-sm border border-[var(--color-border-dim)] border-l-2 border-l-[var(--color-accent-cyan)] bg-[var(--color-bg-surface)]/80">
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
