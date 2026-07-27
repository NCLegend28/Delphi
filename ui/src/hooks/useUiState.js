import { useEffect, useMemo, useState } from "react";

const TOKEN = import.meta.env.VITE_DELPHI_BEARER_TOKEN ?? "";
const BASE = import.meta.env.VITE_DELPHI_BASE_URL ?? "";

export function useUiState({ intervalMs = 5000 } = {}) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const refresh = useMemo(() => {
    return async () => {
      try {
        setError(null);
        const resp = await fetch(`${BASE}/ui/state`, {
          headers: TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {},
        });
        if (!resp.ok) throw new Error(`UI state ${resp.status}`);
        setData(await resp.json());
      } catch (err) {
        setError(err?.message || String(err));
      } finally {
        setLoading(false);
      }
    };
  }, []);

  useEffect(() => {
    const first = setTimeout(refresh, 0);
    const id = setInterval(refresh, intervalMs);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, [intervalMs, refresh]);

  return { data, error, loading, refresh };
}
