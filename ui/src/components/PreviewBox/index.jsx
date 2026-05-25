import { useEffect, useRef } from "react";
import Prism from "prismjs";
import "prismjs/components/prism-python";
import "prismjs/components/prism-json";
import "prismjs/components/prism-markdown";
import "prismjs/components/prism-bash";
import { useDelphiStore } from "../../store/delphiStore";

/**
 * PreviewBox — what Delphi is currently building or reading.
 *
 * Renders one of three states from delphiStore.preview:
 *   - null              → empty/awaiting state
 *   - kind: 'code'      → syntax-highlighted block (Prism)
 *   - kind: 'document'  → monospace text block
 */
export function PreviewBox() {
  const preview = useDelphiStore((s) => s.preview);

  return (
    <div className="panel panel-corner-tl panel-corner-br relative h-full w-full overflow-hidden rounded-sm">
      <header className="flex items-center justify-between border-b border-[var(--color-border-glow)] px-4 py-2">
        <div className="flex items-center gap-2">
          <span
            className={`h-1.5 w-1.5 rounded-full ${
              preview
                ? "bg-[var(--color-accent-amber)] shadow-[0_0_6px_rgba(255,149,0,0.8)] animate-pulse-soft"
                : "bg-[var(--color-accent-cyan)] animate-pulse-soft"
            }`}
          />
          <span className="font-display text-xs tracking-[0.3em] text-[var(--color-text-muted)]">
            PREVIEW
          </span>
        </div>
        <span className="font-mono text-[10px] uppercase tracking-widest text-[var(--color-text-dim)]">
          {preview
            ? preview.kind === "code"
              ? `code · ${preview.language ?? "plain"}`
              : "document"
            : "idle"}
        </span>
      </header>

      <div className="h-[calc(100%-2.5rem)] overflow-auto">
        {preview ? (
          preview.kind === "code" ? (
            <CodePreview language={preview.language} content={preview.content} />
          ) : (
            <DocumentPreview content={preview.content} />
          )
        ) : (
          <Empty />
        )}
      </div>
    </div>
  );
}

function Empty() {
  return (
    <div className="flex h-full items-center justify-center">
      <div className="text-center">
        <div className="font-display text-sm tracking-[0.4em] text-[var(--color-text-dim)]">
          AWAITING
        </div>
        <div className="mt-1 font-mono text-xs text-[var(--color-text-dim)]">
          Delphi will push content here as it works.
        </div>
      </div>
    </div>
  );
}

function CodePreview({ language, content }) {
  const ref = useRef(null);
  useEffect(() => {
    if (ref.current) Prism.highlightElement(ref.current);
  }, [content, language]);

  return (
    <pre className="m-0 h-full overflow-auto bg-transparent px-4 py-3 text-xs leading-relaxed">
      <code
        ref={ref}
        className={`language-${language || "plaintext"} font-mono`}
      >
        {content}
      </code>
    </pre>
  );
}

function DocumentPreview({ content }) {
  return (
    <div className="whitespace-pre-wrap break-words px-4 py-3 font-mono text-xs leading-relaxed text-[var(--color-text-primary)]">
      {content}
    </div>
  );
}
