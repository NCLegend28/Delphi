import { useCallback, useEffect, useRef, useState } from "react";

/**
 * useRecorder — thin React wrapper around MediaRecorder.
 *
 * Lifecycle:
 *   idle → requesting → recording → stopped
 *                       ↓
 *                     denied | error
 *
 * The hook never auto-uploads; the consumer reads `blob` / `blobUrl` from
 * the returned draft and ships it during send (Task 6). On unmount/cancel
 * the blob URL is revoked.
 */

// Preference order — Opus in WebM is best for whisper-style ASR; mp4/ogg are
// Safari/Firefox fallbacks. The first one MediaRecorder.isTypeSupported()
// accepts wins.
const MIME_CANDIDATES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/mp4",
  "audio/ogg;codecs=opus",
  "audio/ogg",
];

function pickMimeType() {
  const MR = typeof window !== "undefined" ? window.MediaRecorder : undefined;
  if (!MR || typeof MR.isTypeSupported !== "function") return "";
  for (const candidate of MIME_CANDIDATES) {
    try {
      if (MR.isTypeSupported(candidate)) return candidate;
    } catch {
      // Ignore — some implementations throw on unknown MIME.
    }
  }
  return "";
}

function isSupported() {
  if (typeof window === "undefined") return false;
  return Boolean(
    window.MediaRecorder &&
      window.navigator?.mediaDevices &&
      typeof window.navigator.mediaDevices.getUserMedia === "function",
  );
}

export function useRecorder() {
  const [status, setStatus] = useState("idle");
  const [error, setError] = useState(null);
  const [blob, setBlob] = useState(null);
  const [blobUrl, setBlobUrl] = useState(null);
  const [mimeType, setMimeType] = useState("");
  const [durationMs, setDurationMs] = useState(0);

  const recorderRef = useRef(null);
  const streamRef = useRef(null);
  const chunksRef = useRef([]);
  const startedAtRef = useRef(0);
  const blobUrlRef = useRef(null);

  const supported = isSupported();

  const releaseStream = useCallback(() => {
    const stream = streamRef.current;
    if (stream) {
      for (const track of stream.getTracks()) {
        try {
          track.stop();
        } catch {
          /* noop */
        }
      }
      streamRef.current = null;
    }
    recorderRef.current = null;
  }, []);

  const revokeBlobUrl = useCallback(() => {
    if (blobUrlRef.current) {
      try {
        URL.revokeObjectURL(blobUrlRef.current);
      } catch {
        /* noop */
      }
      blobUrlRef.current = null;
    }
  }, []);

  const start = useCallback(async () => {
    if (!supported) {
      setStatus("error");
      setError(new Error("MediaRecorder not supported"));
      return;
    }
    if (recorderRef.current) return;

    revokeBlobUrl();
    setBlob(null);
    setBlobUrl(null);
    setDurationMs(0);
    setError(null);
    setStatus("requesting");

    let stream;
    try {
      stream = await window.navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      const denied =
        err && (err.name === "NotAllowedError" || err.name === "SecurityError");
      setStatus(denied ? "denied" : "error");
      setError(err);
      return;
    }

    const chosen = pickMimeType();
    let recorder;
    try {
      recorder = chosen
        ? new window.MediaRecorder(stream, { mimeType: chosen })
        : new window.MediaRecorder(stream);
    } catch (err) {
      setStatus("error");
      setError(err);
      for (const track of stream.getTracks()) track.stop();
      return;
    }

    streamRef.current = stream;
    recorderRef.current = recorder;
    chunksRef.current = [];
    setMimeType(recorder.mimeType || chosen || "");

    recorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) chunksRef.current.push(event.data);
    };
    recorder.onerror = (event) => {
      setStatus("error");
      setError(event?.error ?? new Error("MediaRecorder error"));
      releaseStream();
    };
    recorder.onstop = () => {
      const finalType = recorder.mimeType || chosen || "audio/webm";
      const final = new Blob(chunksRef.current, { type: finalType });
      chunksRef.current = [];
      const url = URL.createObjectURL(final);
      blobUrlRef.current = url;
      setBlob(final);
      setBlobUrl(url);
      setMimeType(finalType);
      setDurationMs(Date.now() - startedAtRef.current);
      setStatus("stopped");
      releaseStream();
    };

    startedAtRef.current = Date.now();
    try {
      recorder.start();
      setStatus("recording");
    } catch (err) {
      setStatus("error");
      setError(err);
      releaseStream();
    }
  }, [supported, releaseStream, revokeBlobUrl]);

  const stop = useCallback(() => {
    const recorder = recorderRef.current;
    if (!recorder) return;
    if (recorder.state === "inactive") return;
    try {
      recorder.stop();
    } catch (err) {
      setStatus("error");
      setError(err);
      releaseStream();
    }
  }, [releaseStream]);

  const cancel = useCallback(() => {
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== "inactive") {
      // Suppress onstop so we don't surface the cancelled clip.
      recorder.onstop = null;
      try {
        recorder.stop();
      } catch {
        /* noop */
      }
    }
    chunksRef.current = [];
    releaseStream();
    revokeBlobUrl();
    setBlob(null);
    setBlobUrl(null);
    setDurationMs(0);
    setStatus("idle");
    setError(null);
  }, [releaseStream, revokeBlobUrl]);

  // Tidy up on unmount.
  useEffect(() => {
    return () => {
      const recorder = recorderRef.current;
      if (recorder && recorder.state !== "inactive") {
        recorder.onstop = null;
        try {
          recorder.stop();
        } catch {
          /* noop */
        }
      }
      releaseStream();
      revokeBlobUrl();
    };
  }, [releaseStream, revokeBlobUrl]);

  return {
    supported,
    status,
    start,
    stop,
    cancel,
    blob,
    blobUrl,
    mimeType,
    durationMs,
    error,
  };
}
