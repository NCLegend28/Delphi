import { useEffect, useState } from "react";
import {
  isSupported as speechIsSupported,
  isPlaying as speechIsPlaying,
  subscribe as speechSubscribe,
  speak as speechSpeak,
  stop as speechStop,
} from "../lib/speech";

/**
 * useSpeechPlayback — React-side view of the singleton speech controller
 * (lib/speech.js). Exposes `{ supported, playing, speak, stop }`.
 *
 * The actual engine lives in lib/speech.js so the streaming hook (autoplay
 * on stream complete) and the per-bubble SPEAK button share one queue. This
 * hook just mirrors its `playing` state into React.
 *
 * Server-TTS seam: when the backend gains a TTS endpoint, swap the body of
 * lib/speech.js' `speak()` and this hook stays as-is.
 */
export function useSpeechPlayback() {
  const supported = speechIsSupported();
  const [playing, setPlaying] = useState(speechIsPlaying());

  useEffect(() => {
    const unsub = speechSubscribe(setPlaying);
    return () => {
      unsub();
    };
  }, []);

  return {
    supported,
    playing,
    speak: speechSpeak,
    stop: speechStop,
  };
}
