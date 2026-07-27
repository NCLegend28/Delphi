import { useEffect, useRef, useState } from "react";
import { useChatStore } from "../../store/chatStore";
import { useRecorder } from "../../hooks/useRecorder";
import { processImage } from "../../lib/attachments";
import { uid } from "../../lib/uid";

/**
 * InputBar — prompt mark + auto-growing textarea + SEND.
 *
 * Holds the local draft (text + image attachments + recorded audio) before
 * dispatching it via `onSubmit`. Draft state is intentionally component-local:
 * it's ephemeral, per-input, and the chatStore only sees the finalized
 * message. Task 6 widens the network path to actually transmit attachments.
 *
 *   Enter         → send (calls onSubmit)
 *   Shift+Enter   → newline
 *   Esc           → blur
 *
 * Listens for the window `delphi:focus-input` event (dispatched by the ⌘K
 * shortcut in App) so the operator can jump to the prompt from anywhere.
 *
 * Speech-to-text (Task 6): when the recorder stops and yields a blob, we
 * fire `transcribe(blob, mime)` from useDelphiStream automatically and drop
 * the returned text into the textarea for the operator to edit. The audio
 * draft is then cleared. If transcription fails the inline error is shown
 * and the audio chip is kept so the operator can retry or discard.
 */
export function InputBar({ onSubmit, onTranscribe, recorderHook = useRecorder }) {
  const [value, setValue] = useState("");
  const [attachments, setAttachments] = useState([]);
  const [attachError, setAttachError] = useState(null);
  const [transcribing, setTranscribing] = useState(false);
  const [transcribeError, setTranscribeError] = useState(null);
  const taRef = useRef(null);
  const fileInputRef = useRef(null);
  const transcribedBlobRef = useRef(null);
  const isStreaming = useChatStore((s) => s.isStreaming);
  const recorder = recorderHook();

  useEffect(() => {
    const focus = () => taRef.current?.focus();
    window.addEventListener("delphi:focus-input", focus);
    return () => window.removeEventListener("delphi:focus-input", focus);
  }, []);

  // Auto-transcribe when a new recording lands. We dedupe by blob identity
  // so re-renders don't refire on the same clip. Transcribe failures keep
  // the audio chip so the user can retry by re-recording or just discard.
  useEffect(() => {
    if (!recorder.blob || !onTranscribe) return;
    if (transcribedBlobRef.current === recorder.blob) return;
    transcribedBlobRef.current = recorder.blob;

    let cancelled = false;
    setTranscribing(true);
    setTranscribeError(null);
    (async () => {
      try {
        const text = await onTranscribe(recorder.blob, recorder.mimeType);
        if (cancelled) return;
        const clean = (text ?? "").trim();
        if (clean) {
          setValue((prev) => {
            const next = prev ? `${prev.replace(/\s+$/, "")} ${clean}` : clean;
            queueMicrotask(() => autosize(taRef.current, next));
            return next;
          });
        }
        // Clear the audio chip — the textarea is now the source of truth.
        recorder.cancel();
        // Focus so the operator can edit before sending.
        taRef.current?.focus();
      } catch (err) {
        if (cancelled) return;
        setTranscribeError(err?.message ?? "transcription failed");
      } finally {
        if (!cancelled) setTranscribing(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [recorder.blob, recorder.mimeType, onTranscribe, recorder]);

  const submit = () => {
    const text = value.trim();
    const hasAudio = Boolean(recorder.blob);
    if (!text && attachments.length === 0 && !hasAudio) return;
    if (isStreaming) return;
    if (transcribing) return;

    const draft = {
      text,
      images: attachments.map((a) => ({
        mimeType: a.mimeType,
        dataUrl: a.dataUrl,
        width: a.width,
        height: a.height,
      })),
      audio: hasAudio
        ? {
            blob: recorder.blob,
            blobUrl: recorder.blobUrl,
            mimeType: recorder.mimeType,
            durationMs: recorder.durationMs,
          }
        : null,
    };

    autosize(taRef.current, "");
    // Two-arg shape: legacy callers (text-only send) keep working, Task 6
    // upgrades the hook to read the full draft.
    onSubmit(text, draft);
    setValue("");
    setAttachments([]);
    setAttachError(null);
    setTranscribeError(null);
    transcribedBlobRef.current = null;
    if (hasAudio) recorder.cancel();
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

  const onFilesPicked = async (e) => {
    const files = Array.from(e.target.files ?? []);
    e.target.value = ""; // allow re-picking the same file
    if (files.length === 0) return;
    setAttachError(null);
    for (const file of files) {
      try {
        const processed = await processImage(file);
        setAttachments((prev) => [
          ...prev,
          { id: uid(), kind: "image", ...processed },
        ]);
      } catch (err) {
        setAttachError(err?.message ?? "could not attach image");
      }
    }
  };

  const removeAttachment = (id) => {
    setAttachments((prev) => prev.filter((a) => a.id !== id));
  };

  const onMicClick = () => {
    if (recorder.status === "recording") {
      recorder.stop();
    } else if (recorder.status === "stopped") {
      recorder.cancel();
      transcribedBlobRef.current = null;
      setTranscribeError(null);
    } else {
      setTranscribeError(null);
      recorder.start();
    }
  };

  const hasDraft =
    value.trim().length > 0 || attachments.length > 0 || Boolean(recorder.blob);

  return (
    <form
      className="flex flex-col gap-1.5 border-t border-[var(--color-border-dim)] px-3.5 py-2"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      {(attachments.length > 0 ||
        recorder.blob ||
        attachError ||
        transcribing ||
        transcribeError) && (
        <div className="flex flex-wrap items-center gap-1.5">
          {attachments.map((a) => (
            <div
              key={a.id}
              data-testid="thumb"
              className="relative h-12 w-12 overflow-hidden rounded-[2px] border border-[var(--color-border-dim)]"
            >
              <img
                src={a.dataUrl}
                alt="attachment preview"
                className="h-full w-full object-cover"
              />
              <button
                type="button"
                aria-label="remove attachment"
                onClick={() => removeAttachment(a.id)}
                className="absolute top-0 right-0 flex h-4 w-4 items-center justify-center bg-[var(--color-bg-void)]/80 text-[10px] leading-none text-[var(--color-accent-red)] hover:bg-[var(--color-accent-red)]/20"
              >
                ×
              </button>
            </div>
          ))}
          {recorder.blob && (
            <div
              data-testid="audio-preview"
              className="flex items-center gap-1.5 border border-[var(--color-border-dim)] px-2 py-1 text-[9px] tracking-[0.15em] text-[var(--color-accent-cyan)]"
            >
              <span aria-hidden="true">🎙</span>
              <span>{formatDuration(recorder.durationMs)}</span>
              <button
                type="button"
                aria-label="discard recording"
                onClick={() => {
                  recorder.cancel();
                  transcribedBlobRef.current = null;
                  setTranscribeError(null);
                }}
                className="text-[var(--color-accent-red)] hover:opacity-80"
              >
                ×
              </button>
            </div>
          )}
          {transcribing && (
            <span
              data-testid="transcribing"
              className="text-[9px] tracking-[0.15em] text-[var(--color-accent-amber)] animate-pulse"
            >
              transcribing…
            </span>
          )}
          {transcribeError && !transcribing && (
            <span
              data-testid="transcribe-error"
              className="text-[9px] tracking-[0.1em] text-[var(--color-accent-red)]"
            >
              {transcribeError}
            </span>
          )}
          {attachError && (
            <span className="text-[9px] tracking-[0.1em] text-[var(--color-accent-red)]">
              {attachError}
            </span>
          )}
        </div>
      )}

      <div className="flex items-center gap-2">
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

        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          multiple
          className="hidden"
          onChange={onFilesPicked}
          data-testid="file-input"
        />
        <button
          type="button"
          aria-label="attach image"
          disabled={isStreaming}
          onClick={() => fileInputRef.current?.click()}
          className="shrink-0 border border-[var(--color-border-dim)] px-2 py-[5px] text-[11px] leading-none text-[var(--color-text-muted)] transition hover:border-[var(--color-accent-cyan)] hover:text-[var(--color-accent-cyan)] disabled:cursor-not-allowed disabled:opacity-30"
        >
          📎
        </button>

        {recorder.supported && (
          <button
            type="button"
            aria-label={
              recorder.status === "recording"
                ? "stop recording"
                : recorder.status === "stopped"
                ? "discard recording"
                : "record audio"
            }
            disabled={isStreaming || recorder.status === "requesting" || transcribing}
            onClick={onMicClick}
            data-testid="mic-button"
            className={[
              "shrink-0 border px-2 py-[5px] text-[11px] leading-none transition disabled:cursor-not-allowed disabled:opacity-30",
              recorder.status === "recording"
                ? "border-[var(--color-accent-red)] text-[var(--color-accent-red)] animate-pulse"
                : recorder.status === "stopped"
                ? "border-[var(--color-accent-amber)] text-[var(--color-accent-amber)]"
                : "border-[var(--color-border-dim)] text-[var(--color-text-muted)] hover:border-[var(--color-accent-cyan)] hover:text-[var(--color-accent-cyan)]",
            ].join(" ")}
          >
            {recorder.status === "recording" ? "■" : "●"}
          </button>
        )}

        <button
          type="submit"
          disabled={isStreaming || !hasDraft || transcribing}
          className="shrink-0 border border-[var(--color-border-strong)] px-3 py-[5px] text-[9px] tracking-[0.2em] text-[var(--color-text-muted)] transition hover:border-[var(--color-accent-cyan)] hover:bg-[var(--color-accent-cyan)]/10 hover:text-[var(--color-accent-cyan)] hover:shadow-[var(--shadow-glow-cyan)] disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:border-[var(--color-border-strong)] disabled:hover:bg-transparent disabled:hover:text-[var(--color-text-muted)] disabled:hover:shadow-none"
        >
          SEND
        </button>
      </div>

      {recorder.status === "denied" && (
        <span className="text-[9px] tracking-[0.1em] text-[var(--color-accent-red)]">
          microphone access denied
        </span>
      )}
    </form>
  );
}

function autosize(el, value) {
  if (!el) return;
  el.style.height = "auto";
  el.style.height = `${Math.min(el.scrollHeight, 128)}px`;
  if (!value) el.style.height = "";
}

function formatDuration(ms) {
  const total = Math.max(0, Math.round(ms / 1000));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}
