import { useSpeechPlayback } from "../../hooks/useSpeechPlayback";

/**
 * MessageBubble — one message in the COMMS feed.
 *
 * `user` bubbles are right-aligned with a cyan-tinted border; `delphi` bubbles
 * are left-aligned on a raised surface and animate a caret while streaming.
 *
 * User bubbles may carry optional `attachments` (image thumbnails) and a
 * `transcript`/`audioUrl` pair for audio-origin messages.
 *
 * Assistant bubbles, when not actively streaming and with non-empty text,
 * show a SPEAK / STOP toggle wired to the singleton speech engine
 * (lib/speech.js). The toggle reflects engine state — so STOP shows while
 * ANY utterance is speaking, regardless of which bubble started it; that's
 * intentional, since only one utterance ever plays at a time.
 */
export function MessageBubble({
  role,
  content,
  streaming,
  attachments,
  transcript,
  audioUrl,
}) {
  const isUser = role === "user";
  const isAssistant = role === "assistant";
  const images = isUser && Array.isArray(attachments)
    ? attachments.filter((a) => a?.kind === "image" && a.dataUrl)
    : [];
  const hasAudio = isUser && (transcript != null || audioUrl);
  const displayText = content || (transcript ?? "");

  const speech = useSpeechPlayback();
  const canSpeak =
    isAssistant && !streaming && typeof content === "string" && content.trim().length > 0;

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
        {images.length > 0 && (
          <div
            data-testid="bubble-thumbs"
            className="mb-1.5 flex flex-wrap gap-1.5"
          >
            {images.map((img) => (
              <img
                key={img.id}
                src={img.dataUrl}
                alt={img.alt ?? "attachment"}
                className="h-16 w-16 rounded-[2px] border border-[var(--color-border-dim)] object-cover"
              />
            ))}
          </div>
        )}
        {hasAudio && (
          <div className="mb-1 flex items-center gap-1 text-[8px] tracking-[0.18em] text-[var(--color-accent-cyan)]">
            <span aria-hidden="true">🎙</span>
            <span>TRANSCRIPT</span>
          </div>
        )}
        {(displayText || streaming) && (
          <span className="whitespace-pre-wrap">{displayText}</span>
        )}
        {streaming && <Caret />}
        {canSpeak && (
          <div className="mt-1 flex justify-end">
            {speech.playing ? (
              <button
                type="button"
                onClick={() => speech.stop()}
                disabled={!speech.supported}
                aria-label="Stop spoken response"
                title="Stop spoken response"
                className="rounded-sm border border-[var(--color-accent-amber)]/40 bg-[var(--color-accent-amber)]/[0.08] px-1.5 py-[1px] text-[8px] tracking-[0.18em] text-[var(--color-accent-amber)] disabled:opacity-40 disabled:cursor-not-allowed"
              >
                ■ STOP
              </button>
            ) : (
              <button
                type="button"
                onClick={() => speech.speak(content)}
                disabled={!speech.supported}
                aria-label="Speak response"
                title={speech.supported ? "Speak response" : "Speech unsupported"}
                className="rounded-sm border border-[var(--color-border-dim)] bg-transparent px-1.5 py-[1px] text-[8px] tracking-[0.18em] text-[var(--color-text-faint)] hover:text-[var(--color-accent-cyan)] hover:border-[var(--color-accent-cyan)]/40 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                ♪ SPEAK
              </button>
            )}
          </div>
        )}
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
