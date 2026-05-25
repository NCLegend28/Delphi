import { useEffect, useState } from "react";

/**
 * useSessionClock — elapsed time since the hook first mounted, as HH:MM:SS.
 *
 * Used by the header session clock and anywhere else a live uptime readout is
 * needed. One interval per consumer; cheap enough at 1 Hz.
 */
export function useSessionClock() {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const start = Date.now();
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - start) / 1000)), 1000);
    return () => clearInterval(id);
  }, []);
  return format(elapsed);
}

function format(s) {
  const h = String(Math.floor(s / 3600)).padStart(2, "0");
  const m = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
  const sec = String(s % 60).padStart(2, "0");
  return `${h}:${m}:${sec}`;
}
