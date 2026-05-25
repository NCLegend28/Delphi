import { create } from "zustand";

/**
 * chatStore — conversation history and streaming state.
 *
 * The backend is stateless (per Delphi/CLAUDE.md): we send the full history
 * on every request. Messages live entirely in this store; nothing persists
 * across reloads in Phase 2. (Persistence is a Phase 6 concern.)
 *
 * Shape of a message:
 *   { id: string, role: 'user' | 'assistant', content: string, ts: number }
 */
export const useChatStore = create((set, get) => ({
  messages: [],
  isStreaming: false,
  streamingId: null,
  error: null,

  /** Append a user message. Returns the new message object. */
  addUserMessage: (content) => {
    const msg = {
      id: crypto.randomUUID(),
      role: "user",
      content,
      ts: Date.now(),
    };
    set((s) => ({ messages: [...s.messages, msg], error: null }));
    return msg;
  },

  /**
   * Begin "in flight" state without creating an assistant bubble. Used to
   * disable the input the instant the user submits, before any bytes
   * arrive. Call `startAssistantMessage` once the first chunk lands.
   */
  beginRequest: () => set({ isStreaming: true, streamingId: null }),

  /** Begin a streaming assistant response. Creates an empty bubble. */
  startAssistantMessage: () => {
    const id = crypto.randomUUID();
    const msg = { id, role: "assistant", content: "", ts: Date.now() };
    set((s) => ({
      messages: [...s.messages, msg],
      isStreaming: true,
      streamingId: id,
    }));
    return id;
  },

  /** Append a delta to the currently streaming assistant message. */
  appendToStreaming: (text) => {
    if (!text) return;
    const { streamingId } = get();
    if (!streamingId) return;
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === streamingId ? { ...m, content: m.content + text } : m,
      ),
    }));
  },

  /** Mark streaming complete. */
  endStreaming: () => set({ isStreaming: false, streamingId: null }),

  /** Record a stream-level error. */
  setError: (msg) =>
    set({ error: msg, isStreaming: false, streamingId: null }),

  /** Wipe history. */
  clear: () =>
    set({ messages: [], isStreaming: false, streamingId: null, error: null }),
}));
