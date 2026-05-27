/**
 * speech — singleton wrapper around the browser Web Speech API
 * (window.speechSynthesis).
 *
 * Why a singleton: both the explicit per-message SPEAK button and the
 * useDelphiStream autoplay path need to talk to the same engine. Two
 * independent hook instances would race their `speaking` state and could
 * double-cancel each other. One module-level controller, many listeners.
 *
 * Server-TTS seam: when api/speech.py lands, swap the body of `speak()` for
 * a fetch + HTMLAudioElement; the public surface
 * (isSupported / subscribe / speak / stop) stays the same so callers don't
 * change.
 */

const listeners = new Set();
let playing = false;

function setPlaying(next) {
  if (next === playing) return;
  playing = next;
  for (const l of listeners) l(playing);
}

export function isSupported() {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

export function isPlaying() {
  return playing;
}

/** Subscribe to playing-state changes. Returns an unsubscribe fn. */
export function subscribe(listener) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/**
 * Speak a string. Cancels any in-flight utterance first — a new request
 * always interrupts the old one. No-ops on empty/whitespace text or when
 * the browser doesn't support speechSynthesis.
 */
export function speak(text) {
  if (!isSupported()) return;
  const t = (text == null ? "" : String(text)).trim();
  if (!t) return;
  // Always cancel first — guarantees only one utterance is ever in flight.
  try {
    window.speechSynthesis.cancel();
  } catch {
    /* ignore */
  }
  const Ctor = window.SpeechSynthesisUtterance;
  if (typeof Ctor !== "function") return;
  const utter = new Ctor(t);
  utter.onstart = () => setPlaying(true);
  utter.onend = () => setPlaying(false);
  utter.onerror = () => setPlaying(false);
  try {
    window.speechSynthesis.speak(utter);
  } catch {
    setPlaying(false);
  }
}

/** Stop any in-flight speech and clear playing state. */
export function stop() {
  if (isSupported()) {
    try {
      window.speechSynthesis.cancel();
    } catch {
      /* ignore */
    }
  }
  setPlaying(false);
}
