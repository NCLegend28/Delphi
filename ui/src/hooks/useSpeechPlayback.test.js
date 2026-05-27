import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";

// Fake speechSynthesis + SpeechSynthesisUtterance. The fake captures the
// latest utterance so the test can manually fire its lifecycle callbacks.
class FakeUtterance {
  constructor(text) {
    this.text = text;
    this.onstart = null;
    this.onend = null;
    this.onerror = null;
    FakeUtterance.last = this;
  }
}

function makeSynth() {
  return {
    cancel: vi.fn(),
    speak: vi.fn((utter) => {
      // Default: do not auto-fire onstart — tests trigger it manually.
      makeSynth.last = utter;
    }),
    speaking: false,
  };
}

beforeEach(() => {
  vi.resetModules();
  FakeUtterance.last = null;
  window.SpeechSynthesisUtterance = FakeUtterance;
  window.speechSynthesis = makeSynth();
});

afterEach(() => {
  delete window.speechSynthesis;
  delete window.SpeechSynthesisUtterance;
});

describe("useSpeechPlayback", () => {
  it("reports supported=true when speechSynthesis exists", async () => {
    const { useSpeechPlayback } = await import("./useSpeechPlayback");
    const { result } = renderHook(() => useSpeechPlayback());
    expect(result.current.supported).toBe(true);
    expect(result.current.playing).toBe(false);
  });

  it("speak() creates an utterance, cancels prior, flips playing on start/end", async () => {
    const { useSpeechPlayback } = await import("./useSpeechPlayback");
    const { result } = renderHook(() => useSpeechPlayback());

    act(() => {
      result.current.speak("hello world");
    });
    expect(window.speechSynthesis.cancel).toHaveBeenCalled();
    expect(window.speechSynthesis.speak).toHaveBeenCalledTimes(1);
    expect(FakeUtterance.last).toBeInstanceOf(FakeUtterance);
    expect(FakeUtterance.last.text).toBe("hello world");

    act(() => {
      FakeUtterance.last.onstart?.();
    });
    expect(result.current.playing).toBe(true);

    act(() => {
      FakeUtterance.last.onend?.();
    });
    expect(result.current.playing).toBe(false);
  });

  it("speak() ignores empty/whitespace text", async () => {
    const { useSpeechPlayback } = await import("./useSpeechPlayback");
    const { result } = renderHook(() => useSpeechPlayback());
    act(() => {
      result.current.speak("   ");
    });
    expect(window.speechSynthesis.speak).not.toHaveBeenCalled();
  });

  it("stop() calls speechSynthesis.cancel and clears playing", async () => {
    const { useSpeechPlayback } = await import("./useSpeechPlayback");
    const { result } = renderHook(() => useSpeechPlayback());

    act(() => {
      result.current.speak("hi");
      FakeUtterance.last.onstart?.();
    });
    expect(result.current.playing).toBe(true);

    act(() => {
      result.current.stop();
    });
    expect(window.speechSynthesis.cancel).toHaveBeenCalled();
    expect(result.current.playing).toBe(false);
  });

  it("supported=false when speechSynthesis is missing", async () => {
    delete window.speechSynthesis;
    const { useSpeechPlayback } = await import("./useSpeechPlayback");
    const { result } = renderHook(() => useSpeechPlayback());
    expect(result.current.supported).toBe(false);
    // speak() is a no-op without throwing
    act(() => {
      result.current.speak("hi");
    });
    expect(result.current.playing).toBe(false);
  });

  it("onerror clears playing", async () => {
    const { useSpeechPlayback } = await import("./useSpeechPlayback");
    const { result } = renderHook(() => useSpeechPlayback());
    act(() => {
      result.current.speak("hi");
      FakeUtterance.last.onstart?.();
    });
    expect(result.current.playing).toBe(true);
    act(() => {
      FakeUtterance.last.onerror?.({ error: "oops" });
    });
    expect(result.current.playing).toBe(false);
  });
});
