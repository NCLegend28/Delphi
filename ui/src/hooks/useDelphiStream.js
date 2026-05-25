import { useCallback, useRef } from "react";
import { useChatStore } from "../store/chatStore";
import { useDelphiStore } from "../store/delphiStore";

const TOKEN = import.meta.env.VITE_DELPHI_BEARER_TOKEN ?? "";
const BASE = import.meta.env.VITE_DELPHI_BASE_URL ?? "";

/**
 * useDelphiStream — the only path through which the UI talks to Delphi.
 *
 * Returns `{ send, cancel }`:
 *
 *   send(text)   — POST text + full prior history to /v1/chat/completions,
 *                  parse the SSE response, route plain text into chatStore
 *                  and inline directives into delphiStore.
 *   cancel()     — abort the in-flight request.
 *
 * The protocol the model emits is documented in `routing/soul.py` under
 * `UI_PROTOCOL_APPENDIX`. The parser strips these tokens from the rendered
 * chat text:
 *
 *   [MODE:THINKING|BUILDING|SEARCHING|IDLE]
 *   [TASK: short label]
 *   [PREVIEW:code:<lang>] ... body ... [/PREVIEW]
 *   [PREVIEW:document]    ... body ... [/PREVIEW]
 *
 * Why a hand-rolled parser instead of a regex pass: tokens can straddle
 * SSE chunks (e.g. one chunk ends with "[MO", the next begins with
 * "DE:THINKING]"). The parser keeps a tail buffer of bytes that might be
 * the start of a token and only commits them to the chat bubble when it's
 * sure they are not.
 */
export function useDelphiStream() {
  const abortRef = useRef(null);

  const send = useCallback(async (text) => {
    const trimmed = text.trim();
    if (!trimmed) return;

    const chat = useChatStore.getState();
    const delphi = useDelphiStore.getState();

    chat.addUserMessage(trimmed);
    delphi.clearPreview();
    delphi.setActiveTask(null);
    delphi.setError(null);
    delphi.setMode("THINKING");

    const history = useChatStore.getState().messages.map((m) => ({
      role: m.role,
      content: m.content,
    }));

    // Disable input immediately, but defer creating the assistant bubble
    // until we actually get content — an empty "DELPHI" bubble next to an
    // error line looks broken.
    chat.beginRequest();
    let assistantStarted = false;
    const ensureAssistantStarted = () => {
      if (!assistantStarted) {
        chat.startAssistantMessage();
        assistantStarted = true;
      }
    };

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const resp = await fetch(`${BASE}/v1/chat/completions`, {
        method: "POST",
        signal: controller.signal,
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${TOKEN}`,
          "x-client-id": "delphi-ui",
        },
        body: JSON.stringify({
          messages: history,
          stream: true,
          task_type: "auto",
        }),
      });

      if (!resp.ok) {
        const body = await resp.text().catch(() => "");
        throw new Error(
          `Delphi ${resp.status}: ${summariseErrorBody(body) || resp.statusText}`,
        );
      }
      if (!resp.body) throw new Error("Delphi: empty response body");

      const reader = resp.body.getReader();
      const decoder = new TextDecoder("utf-8");
      const parser = createTokenParser(ensureAssistantStarted);

      let sseBuffer = "";
      // eslint-disable-next-line no-constant-condition
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        sseBuffer += decoder.decode(value, { stream: true });
        sseBuffer = drainSse(sseBuffer, (chunk) => parser.feed(chunk));
      }
      parser.flush();
      delphi.setMode("IDLE");
    } catch (err) {
      if (err.name === "AbortError") return;
      const msg = err.message || String(err);
      chat.setError(msg);
      delphi.setError(msg);
      delphi.setMode("IDLE");
    } finally {
      useChatStore.getState().endStreaming();
      abortRef.current = null;
    }
  }, []);

  const cancel = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  return { send, cancel };
}

/**
 * Pull a short, human-readable summary out of an error body — strips HTML,
 * collapses whitespace, and caps to a single line. Keeps OpenAI-shaped JSON
 * error messages intact when the body parses.
 */
function summariseErrorBody(body) {
  if (!body) return "";
  const trimmed = body.trim();
  if (trimmed.startsWith("{")) {
    try {
      const obj = JSON.parse(trimmed);
      const msg = obj?.error?.message || obj?.detail || obj?.message;
      if (typeof msg === "string") return msg.slice(0, 200);
    } catch {
      /* fall through to text summary */
    }
  }
  // Strip tags, collapse whitespace, truncate.
  const text = trimmed
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return text.length > 200 ? `${text.slice(0, 197)}…` : text;
}

/**
 * Consume complete `data: { ... }` SSE events from a buffer.
 * Returns the unconsumed tail (a partial line that hasn't ended yet).
 */
function drainSse(buffer, onContent) {
  // SSE events are separated by blank lines. Within an event each line is
  // a field. We only care about `data:` lines on the OpenAI-shaped stream.
  const lines = buffer.split("\n");
  const tail = lines.pop() ?? "";

  for (const raw of lines) {
    const line = raw.trim();
    if (!line.startsWith("data:")) continue;
    const payload = line.slice(5).trim();
    if (!payload || payload === "[DONE]") continue;
    try {
      const obj = JSON.parse(payload);
      for (const choice of obj.choices ?? []) {
        const delta = choice?.delta?.content;
        if (typeof delta === "string" && delta.length) onContent(delta);
      }
    } catch {
      /* Tolerate junk; Ollama sometimes emits keep-alives. */
    }
  }
  return tail;
}

/**
 * Streaming parser that strips inline directives from response text and
 * routes them into delphiStore. Plain text goes to the assistant bubble.
 *
 * State machine:
 *   - "chat"     normal text; scan for `[` that begins a known directive
 *   - "preview"  inside a [PREVIEW:...]…[/PREVIEW] block; accumulate body
 *
 * Tail-buffering: when we see a `[` that *might* be the start of a token
 * but we don't yet have enough text to decide, keep the suffix in
 * `pending` until the next feed() or flush().
 */
export function createTokenParser(onFirstChatChunk) {
  const chat = useChatStore.getState();
  const delphi = useDelphiStore.getState();

  let state = "chat";
  let pending = "";
  let previewMeta = null; // { kind, language }
  let previewBuf = "";

  const TOKEN_OPENERS = ["[MODE:", "[TASK:", "[PREVIEW:", "[/PREVIEW"];

  /** Could `pending` still grow into one of the known token openers? */
  function isPrefixOfAnyOpener(s) {
    if (!s.startsWith("[")) return false;
    return TOKEN_OPENERS.some((op) => op.startsWith(s));
  }

  function emitChat(text) {
    if (!text.length) return;
    onFirstChatChunk?.();
    chat.appendToStreaming(text);
  }

  function commitPreview() {
    if (previewMeta) {
      delphi.setPreview({
        kind: previewMeta.kind,
        language: previewMeta.language ?? null,
        content: previewBuf.replace(/^\n+|\n+$/g, ""),
      });
    }
    previewMeta = null;
    previewBuf = "";
  }

  function handleDirective(open, close, raw) {
    // raw is e.g. "[MODE:THINKING]" or "[TASK: Refactoring foo]" or
    // "[PREVIEW:code:python]" or "[/PREVIEW]".
    const inner = raw.slice(open, close);

    if (raw.startsWith("[MODE:")) {
      const mode = inner.slice(5).trim().toUpperCase();
      if (["IDLE", "THINKING", "BUILDING", "SEARCHING"].includes(mode)) {
        delphi.setMode(mode);
      }
      return;
    }
    if (raw.startsWith("[TASK:")) {
      delphi.setActiveTask(inner.slice(5).trim() || null);
      return;
    }
    if (raw.startsWith("[/PREVIEW")) {
      if (state === "preview") {
        commitPreview();
        state = "chat";
      }
      return;
    }
    if (raw.startsWith("[PREVIEW:")) {
      // Forms: "[PREVIEW:code:python]" or "[PREVIEW:document]"
      const parts = inner.slice(8).trim().split(":");
      const kind = (parts[0] || "document").toLowerCase();
      const language = parts[1]?.trim() || null;
      previewMeta = {
        kind: kind === "code" ? "code" : "document",
        language,
      };
      previewBuf = "";
      state = "preview";
      return;
    }
  }

  function processChat(text) {
    let work = pending + text;
    pending = "";

    while (work.length) {
      const openIdx = work.indexOf("[");
      if (openIdx === -1) {
        emitChat(work);
        return;
      }
      // Emit everything before the bracket.
      if (openIdx > 0) {
        emitChat(work.slice(0, openIdx));
        work = work.slice(openIdx);
      }
      // Now `work` starts with '['. Try to match a complete token.
      const closeIdx = work.indexOf("]");
      if (closeIdx === -1) {
        // Incomplete token, or stray '['.
        if (isPrefixOfAnyOpener(work)) {
          pending = work; // wait for more
          return;
        }
        // Definitely not a token start — emit one char and continue.
        emitChat(work[0]);
        work = work.slice(1);
        continue;
      }
      const raw = work.slice(0, closeIdx + 1);
      const opener = TOKEN_OPENERS.find((op) => raw.startsWith(op));
      if (!opener) {
        // Bracketed text that isn't a known directive (e.g. "[1, 2]")
        emitChat(raw);
        work = work.slice(closeIdx + 1);
        continue;
      }
      handleDirective(0, closeIdx + 1, raw);
      work = work.slice(closeIdx + 1);
      if (state === "preview") {
        // The rest goes into the preview buffer, processed by processPreview
        processPreview(work);
        return;
      }
    }
  }

  function processPreview(text) {
    let work = pending + text;
    pending = "";

    while (work.length) {
      const closeIdx = work.indexOf("[/PREVIEW");
      if (closeIdx === -1) {
        // No closer yet. Watch for a partial closer at the end so we don't
        // accidentally commit "[/PREVIE" as preview body.
        const tailStart = Math.max(0, work.length - "[/PREVIEW".length);
        const tail = work.slice(tailStart);
        if ("[/PREVIEW".startsWith(tail) && tail.startsWith("[")) {
          previewBuf += work.slice(0, tailStart);
          pending = tail;
        } else {
          previewBuf += work;
        }
        return;
      }
      previewBuf += work.slice(0, closeIdx);
      const remainder = work.slice(closeIdx);
      const endBracket = remainder.indexOf("]");
      if (endBracket === -1) {
        // We have "[/PREVIEW" but not the "]" yet. Wait.
        pending = remainder;
        return;
      }
      // Consume "[/PREVIEW...]"
      commitPreview();
      state = "chat";
      work = remainder.slice(endBracket + 1);
      // Anything after the close-tag is chat again — recurse.
      if (work.length) {
        processChat(work);
        return;
      }
    }
  }

  return {
    feed(text) {
      if (state === "chat") processChat(text);
      else processPreview(text);
    },
    flush() {
      // End of stream — release any held pending text as plain chat.
      if (state === "preview") {
        // Stream ended mid-preview; commit what we have.
        previewBuf += pending;
        pending = "";
        commitPreview();
        state = "chat";
      } else if (pending) {
        emitChat(pending);
        pending = "";
      }
    },
  };
}
