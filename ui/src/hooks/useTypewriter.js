import { useEffect, useRef, useState } from "react";

/**
 * useTypewriter — render a string with a "typing" reveal that keeps up with
 * a growing source.
 *
 * The Delphi backend already streams SSE chunks into the assistant message,
 * so the source text grows as bytes arrive. Without this hook the chunks
 * just *appear* in steps (sometimes 80+ chars at a time), which feels like
 * a hard cut. This hook lags the rendered string behind the live one by a
 * configurable rate so the reveal feels continuous — like watching a
 * teletype rather than a series of screen refreshes.
 *
 * Behavior:
 * - On mount: ``displayed`` starts empty; the animation catches up to the
 *   current ``text`` at ``charsPerSecond``.
 * - As ``text`` grows (new SSE chunks), the catch-up rate auto-scales so a
 *   large chunk doesn't visibly stall: there is a hard ceiling of
 *   ``maxLagMs`` between the source and the rendered text. A 500-char chunk
 *   that arrives at once gets revealed over ~600 ms, not 8 s.
 * - If ``text`` shrinks (the parent reset or swapped messages), the hook
 *   snaps ``displayed`` to the new value rather than backspacing. Pair with
 *   a ``key`` reset on the consuming component for clean turn boundaries.
 * - Honors ``prefers-reduced-motion``: returns ``text`` unchanged so users
 *   with motion sensitivity see the same instant render they see today.
 *
 * @param {string} text — the live source string, typically a streaming
 *     assistant message ``content``.
 * @param {object} [opts]
 * @param {number} [opts.charsPerSecond=240] — baseline reveal rate.
 * @param {number} [opts.maxLagMs=600] — hard ceiling on how far the reveal
 *     may trail the source. When the gap exceeds this, the reveal speeds
 *     up to close it.
 * @returns {string} the currently-revealed prefix of ``text``.
 */
export function useTypewriter(text, opts = {}) {
  const { charsPerSecond = 240, maxLagMs = 600 } = opts;
  const [displayed, setDisplayed] = useState("");
  const rafRef = useRef(0);
  const reduceMotion = usePrefersReducedMotion();

  useEffect(() => {
    if (reduceMotion) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setDisplayed(text);
      return undefined;
    }

    // Shrink → snap. Avoids a "deleting" effect when the parent swaps in a
    // shorter source (e.g. between turns if the consumer didn't reset).
    if (text.length < displayed.length) {
      setDisplayed(text);
      return undefined;
    }
    // Already caught up.
    if (displayed.length >= text.length) {
      return undefined;
    }

    const startTime = performance.now();
    const startLen = displayed.length;
    const remaining = text.length - startLen;
    // Scale rate so the lag never exceeds maxLagMs even on a fat chunk.
    const requiredRate = (remaining / maxLagMs) * 1000;
    const rate = Math.max(charsPerSecond, requiredRate);

    const step = (now) => {
      const elapsed = now - startTime;
      const target = Math.min(text.length, startLen + Math.floor((elapsed * rate) / 1000));
      setDisplayed(text.slice(0, target));
      if (target < text.length) {
        rafRef.current = requestAnimationFrame(step);
      }
    };
    rafRef.current = requestAnimationFrame(step);

    return () => cancelAnimationFrame(rafRef.current);
    // ``displayed`` intentionally excluded — including it would cancel the
    // animation on every paint and starve forward progress.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, reduceMotion, charsPerSecond, maxLagMs]);

  return displayed;
}

/** Track the user's ``prefers-reduced-motion`` setting reactively. */
function usePrefersReducedMotion() {
  const [reduce, setReduce] = useState(() => {
    if (typeof window === "undefined" || !window.matchMedia) return false;
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  });
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return undefined;
    const mql = window.matchMedia("(prefers-reduced-motion: reduce)");
    const onChange = (e) => setReduce(e.matches);
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);
  return reduce;
}
