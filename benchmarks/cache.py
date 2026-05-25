"""On-disk cache for leaderboard fetches.

Leaderboards update on the order of weeks; we cache aggressively so
repeated ranking calls during tuning don't hammer the source sites and
don't add network latency. Default TTL is 24 hours.

Storage is plain text files keyed by a sanitized name — these are
public leaderboard payloads, not secrets.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_CACHE_DIR = Path.home() / ".cache" / "delphi-benchmarks"
DEFAULT_TTL = timedelta(hours=24)


class Cache:
    """Filesystem-backed TTL cache. Thread-unsafe by design — CLI use only."""

    def __init__(
        self,
        cache_dir: Path | None = None,
        ttl: timedelta = DEFAULT_TTL,
    ) -> None:
        self.dir = cache_dir or DEFAULT_CACHE_DIR
        self.dir.mkdir(parents=True, exist_ok=True)
        self.ttl = ttl

    def get(self, key: str) -> str | None:
        """Return cached payload or ``None`` if missing or expired."""
        path = self._path(key)
        if not path.exists():
            return None
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if datetime.now(timezone.utc) - mtime > self.ttl:
            return None
        return path.read_text(encoding="utf-8")

    def put(self, key: str, value: str) -> None:
        """Atomically write ``value`` under ``key``."""
        path = self._path(key)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(value, encoding="utf-8")
        tmp.replace(path)

    def invalidate(self, key: str) -> None:
        """Drop the entry for ``key`` if present."""
        self._path(key).unlink(missing_ok=True)

    def invalidate_prefix(self, prefix: str) -> int:
        """Drop every entry whose sanitized key starts with ``prefix``.

        Returns the number of entries removed. Used by ``cmd_fetch`` to
        bust a source's dated cache keys without enumerating them.
        """
        safe_prefix = "".join(
            c if c.isalnum() or c in "-_." else "_" for c in prefix
        )
        removed = 0
        for path in self.dir.glob(f"{safe_prefix}*"):
            if path.is_file():
                path.unlink()
                removed += 1
        return removed

    def _path(self, key: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in key)
        return self.dir / safe
