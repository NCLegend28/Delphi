import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useDelphiStream } from "./useDelphiStream";
import { useChatStore } from "../store/chatStore";
import { useDelphiStore } from "../store/delphiStore";

/**
 * useDelphiStream tests — exercise the wire format on the request body for
 * text-only, multimodal (text + images), and the audio transcription helper.
 *
 * SSE/cancel/parsing live in adjacent code paths and are intentionally not
 * re-tested here; we keep the response minimal and focus on what Task 6
 * adds.
 */

function sseStream(chunks) {
  // Build a ReadableStream that emits OpenAI-style SSE deltas.
  const encoder = new TextEncoder();
  const events = chunks
    .map((c) =>
      `data: ${JSON.stringify({ choices: [{ delta: { content: c } }] })}\n\n`,
    )
    .join("") + "data: [DONE]\n\n";
  return new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode(events));
      controller.close();
    },
  });
}

function mockChatResponse(chunks = ["ok"]) {
  return {
    ok: true,
    status: 200,
    body: sseStream(chunks),
    text: async () => "",
  };
}

beforeEach(() => {
  useChatStore.getState().clear();
  useDelphiStore.getState().reset();
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useDelphiStream.send", () => {
  it("sends plain string content for text-only legacy calls", async () => {
    const fetchMock = vi.fn().mockResolvedValue(mockChatResponse());
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useDelphiStream());
    await act(async () => {
      await result.current.send("hi there");
    });

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/v1\/chat\/completions$/);
    const body = JSON.parse(init.body);
    expect(body.messages).toHaveLength(1);
    expect(body.messages[0]).toEqual({ role: "user", content: "hi there" });
  });

  it("accepts the draft object and builds OpenAI content array when images present", async () => {
    const fetchMock = vi.fn().mockResolvedValue(mockChatResponse());
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useDelphiStream());
    await act(async () => {
      await result.current.send({
        text: "what is this?",
        images: [
          {
            mimeType: "image/png",
            dataUrl: "data:image/png;base64,AAA",
            width: 10,
            height: 10,
          },
        ],
      });
    });

    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.messages).toHaveLength(1);
    expect(body.messages[0].role).toBe("user");
    expect(body.messages[0].content).toEqual([
      { type: "text", text: "what is this?" },
      { type: "image_url", image_url: { url: "data:image/png;base64,AAA" } },
    ]);
  });

  it("rebuilds prior user attachments into content arrays for history", async () => {
    const fetchMock = vi.fn().mockResolvedValue(mockChatResponse());
    vi.stubGlobal("fetch", fetchMock);

    // Pre-seed history: a prior user turn with an image, then an assistant.
    useChatStore.getState().addUserMessage("look", {
      attachments: [
        { mimeType: "image/png", dataUrl: "data:image/png;base64,XYZ", width: 1, height: 1 },
      ],
    });
    useChatStore.getState().startAssistantMessage();
    useChatStore.getState().appendToStreaming("seen it");
    useChatStore.getState().endStreaming();

    const { result } = renderHook(() => useDelphiStream());
    await act(async () => {
      await result.current.send("more please");
    });

    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    // 3 messages: prior user (multimodal), prior assistant (string), new user (string).
    expect(body.messages).toHaveLength(3);
    expect(body.messages[0].role).toBe("user");
    expect(body.messages[0].content).toEqual([
      { type: "text", text: "look" },
      { type: "image_url", image_url: { url: "data:image/png;base64,XYZ" } },
    ]);
    expect(body.messages[1]).toEqual({ role: "assistant", content: "seen it" });
    expect(body.messages[2]).toEqual({ role: "user", content: "more please" });
  });
});

describe("useDelphiStream.transcribe", () => {
  it("POSTs multipart audio to /v1/audio/transcriptions and returns text", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ text: "hello world" }),
      text: async () => "",
    });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useDelphiStream());
    const blob = new Blob(["x"], { type: "audio/webm" });
    let out;
    await act(async () => {
      out = await result.current.transcribe(blob, "audio/webm");
    });
    expect(out).toBe("hello world");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/v1\/audio\/transcriptions$/);
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
    const file = init.body.get("file");
    expect(file).toBeInstanceOf(Blob);
    // No JSON content-type — multipart only.
    expect(init.headers?.["Content-Type"]).toBeUndefined();
    expect(init.headers?.Authorization).toMatch(/^Bearer /);
  });

  it("surfaces error from non-2xx as a thrown message", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 413,
      statusText: "Payload Too Large",
      text: async () => JSON.stringify({ detail: "file too big" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useDelphiStream());
    const blob = new Blob(["x"], { type: "audio/webm" });
    await expect(
      result.current.transcribe(blob, "audio/webm"),
    ).rejects.toThrow(/413/);
  });
});

describe("useDelphiStream directive parsing", () => {
  it("parses [PREVIEW:media] with a JSON body into delphiStore", async () => {
    const body = JSON.stringify({
      url: "https://example.com/x.png",
      alt: "snapshot",
      mimeType: "image/png",
    });
    const fetchMock = vi.fn().mockResolvedValue(
      mockChatResponse([
        "hi ",
        `[PREVIEW:media]\n${body}\n[/PREVIEW]`,
        " done",
      ]),
    );
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useDelphiStream());
    await act(async () => {
      await result.current.send("show me");
    });

    const preview = useDelphiStore.getState().preview;
    expect(preview).toEqual({
      kind: "media",
      url: "https://example.com/x.png",
      alt: "snapshot",
      mimeType: "image/png",
    });
  });

  it("parses [PREVIEW:media] with a raw URL body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      mockChatResponse(["[PREVIEW:media]https://example.com/y.jpg[/PREVIEW]"]),
    );
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useDelphiStream());
    await act(async () => {
      await result.current.send("look");
    });

    const preview = useDelphiStore.getState().preview;
    expect(preview).toMatchObject({
      kind: "media",
      url: "https://example.com/y.jpg",
    });
    expect(preview.alt).toBeUndefined();
  });

  it("auto-sets a media preview from the user's first attached image at send time", async () => {
    const fetchMock = vi.fn().mockResolvedValue(mockChatResponse(["ack"]));
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useDelphiStream());
    await act(async () => {
      await result.current.send({
        text: "what is this?",
        images: [
          {
            mimeType: "image/png",
            dataUrl: "data:image/png;base64,ZZZ",
            width: 10,
            height: 10,
          },
        ],
      });
    });

    const preview = useDelphiStore.getState().preview;
    expect(preview).toMatchObject({
      kind: "media",
      url: "data:image/png;base64,ZZZ",
      mimeType: "image/png",
    });
  });

  it("preserves the user's mirrored media preview when the assistant opens an unknown PREVIEW kind", async () => {
    // Regression: small models sometimes emit garbage like "[PREVIEW:image:)"
    // or "[PREVIEW:snapshot]…[/PREVIEW]". Previously these fell through to
    // 'document' and clobbered the user's mirrored attachment on stream end.
    const fetchMock = vi.fn().mockResolvedValue(
      mockChatResponse(["hello [PREVIEW:image:) garbage [/PREVIEW] done"]),
    );
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useDelphiStream());
    await act(async () => {
      await result.current.send({
        text: "what is this?",
        images: [
          {
            mimeType: "image/png",
            dataUrl: "data:image/png;base64,KEEPME",
            width: 10,
            height: 10,
          },
        ],
      });
    });

    const preview = useDelphiStore.getState().preview;
    expect(preview).toMatchObject({
      kind: "media",
      url: "data:image/png;base64,KEEPME",
    });
  });

  it("preserves the mirrored media preview when [PREVIEW:document] is opened but never closed", async () => {
    // Regression: an unclosed preview directive used to commit on flush() and
    // overwrite whatever preview was already there with the buffered text.
    const fetchMock = vi.fn().mockResolvedValue(
      mockChatResponse(["intro [PREVIEW:document]forgot to close"]),
    );
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useDelphiStream());
    await act(async () => {
      await result.current.send({
        text: "what is this?",
        images: [
          {
            mimeType: "image/png",
            dataUrl: "data:image/png;base64,KEEPME2",
            width: 10,
            height: 10,
          },
        ],
      });
    });

    const preview = useDelphiStore.getState().preview;
    expect(preview).toMatchObject({
      kind: "media",
      url: "data:image/png;base64,KEEPME2",
    });
  });

  it("parses [PREVIEW:practice-test:<id>] and stashes the test_id", async () => {
    // The practice-test directive carries the test id in the slot the code
    // directive uses for language; the parser must surface it under
    // ``preview.testId`` so the form component can fetch + render.
    const body = "# GRE Practice Test\n\n1. The committee's decision was ___\n";
    const fetchMock = vi.fn().mockResolvedValue(
      mockChatResponse([
        "Here is your test. ",
        `[PREVIEW:practice-test:01HXTEST]\n${body}\n[/PREVIEW]`,
      ]),
    );
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useDelphiStream());
    await act(async () => {
      await result.current.send("give me a practice test");
    });

    const preview = useDelphiStore.getState().preview;
    expect(preview).toMatchObject({
      kind: "practice-test",
      testId: "01HXTEST",
    });
    expect(preview.content).toContain("The committee");
  });
});
