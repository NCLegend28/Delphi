import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useTypewriter } from "./useTypewriter";

/**
 * useTypewriter tests focus on the *behavior* (catch-up, snap-on-shrink,
 * reduced-motion bypass), not the exact rate — rendering timing is testable
 * but brittle. We drive ``requestAnimationFrame`` ourselves so each tick is
 * deterministic.
 */

beforeEach(() => {
  // Replace rAF with a queue we step through manually.
  let nextId = 1;
  const callbacks = new Map();
  globalThis.requestAnimationFrame = (cb) => {
    const id = nextId++;
    callbacks.set(id, cb);
    return id;
  };
  globalThis.cancelAnimationFrame = (id) => {
    callbacks.delete(id);
  };
  globalThis.__flushRaf = (timestamp = performance.now()) => {
    const pending = [...callbacks.entries()];
    callbacks.clear();
    for (const [, cb] of pending) cb(timestamp);
  };
  // Force the reduced-motion query to resolve as `false` (animation on).
  globalThis.matchMedia = vi.fn().mockImplementation((q) => ({
    matches: false,
    media: q,
    addEventListener: () => {},
    removeEventListener: () => {},
  }));
});

describe("useTypewriter", () => {
  it("starts empty and reveals the source over successive frames", () => {
    const { result } = renderHook(({ t }) => useTypewriter(t, { charsPerSecond: 100 }), {
      initialProps: { t: "hello world" },
    });
    expect(result.current).toBe("");

    // Advance ~1s of animation → all 11 chars should be revealed at 100 cps.
    act(() => {
      globalThis.__flushRaf(performance.now() + 200);
    });
    // One step at 200ms × 100cps = 20 chars worth, clamped to text length.
    expect(result.current).toBe("hello world");
  });

  it("snaps to a shorter source instead of backspacing", () => {
    const { result, rerender } = renderHook(({ t }) => useTypewriter(t, { charsPerSecond: 1000 }), {
      initialProps: { t: "long original answer with lots of words" },
    });
    act(() => {
      globalThis.__flushRaf(performance.now() + 1000);
    });
    expect(result.current).toBe("long original answer with lots of words");

    // New (shorter) turn: shrink → snap, no deletion animation.
    rerender({ t: "ok" });
    expect(result.current).toBe("ok");
  });

  it("returns text unchanged when prefers-reduced-motion is set", () => {
    globalThis.matchMedia = vi.fn().mockImplementation((q) => ({
      matches: true,
      media: q,
      addEventListener: () => {},
      removeEventListener: () => {},
    }));
    const { result } = renderHook(() => useTypewriter("instant reveal"));
    expect(result.current).toBe("instant reveal");
  });

  it("accelerates reveal when a fat chunk would otherwise stall it", () => {
    // 600 chars dropped at once with maxLagMs=200 → rate must scale to at
    // least 3000 cps to keep the lag under the ceiling.
    const big = "x".repeat(600);
    const { result } = renderHook(() => useTypewriter(big, { charsPerSecond: 60, maxLagMs: 200 }));
    act(() => {
      globalThis.__flushRaf(performance.now() + 200);
    });
    // At 60 cps the reveal would have shown ~12 chars in 200ms; with the
    // ceiling kicking in we expect the full 600 to land.
    expect(result.current.length).toBe(600);
  });
});
