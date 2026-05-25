"""LiveBench — contamination-resistant multi-category benchmark.

LiveBench rotates its question set monthly to keep scores resistant to
training-set contamination, and publishes a fresh ``table_<date>.csv``
plus matching ``categories_<date>.json`` on each rotation in the
website repo at ``livebench/livebench.github.io/tree/main/public``.

This module auto-discovers the latest pair via the GitHub contents
API rather than hardcoding a date that would go stale within a month.
The CSV ships *per-task* columns; we aggregate per-category using the
mapping the official site uses.

Category mapping (lowercased snake_case to match ``map.py`` keys):

    Reasoning      → reasoning
    Coding         → coding
    Agentic Coding → agentic_coding
    Mathematics    → mathematics
    Data Analysis  → data_analysis
    Language       → language
    IF             → instruction_following

If the discovery API rate-limits (60 req/h unauthenticated), the
24-hour cache normally hides it. If it fails on a cold cache, the
error surfaces — there's no point silently falling back to a stale
hardcoded date.
"""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime, timezone

import httpx

from benchmarks.cache import Cache
from benchmarks.models import BenchmarkScore
from benchmarks.normalize import canonicalize

_REPO = "livebench/livebench.github.io"
_CONTENTS_API = f"https://api.github.com/repos/{_REPO}/contents/public"
_RAW_BASE = f"https://raw.githubusercontent.com/{_REPO}/main/public"

_TABLE_RE = re.compile(r"^table_(\d{4}_\d{2}_\d{2})\.csv$")

_CATEGORY_NORMALIZATION: dict[str, str] = {
    "Reasoning": "reasoning",
    "Coding": "coding",
    "Agentic Coding": "agentic_coding",
    "Mathematics": "mathematics",
    "Data Analysis": "data_analysis",
    "Language": "language",
    "IF": "instruction_following",
}


class LiveBenchSource:
    """Adapter for the LiveBench dated table CSVs."""

    name = "livebench"

    def __init__(
        self,
        cache: Cache | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._cache = cache or Cache()
        self._client = client or httpx.Client(timeout=30.0)

    def fetch(self) -> list[BenchmarkScore]:
        release = self._discover_latest_release()
        table_csv = self._fetch_text(
            f"livebench_table_{release}.csv",
            f"{_RAW_BASE}/table_{release}.csv",
        )
        categories_raw = self._fetch_text(
            f"livebench_categories_{release}.json",
            f"{_RAW_BASE}/categories_{release}.json",
        )
        return list(self._aggregate(table_csv, json.loads(categories_raw), release))

    # --- internals -------------------------------------------------------

    def _discover_latest_release(self) -> str:
        """Return the date string of the most recent ``table_*.csv``.

        Date format ``YYYY_MM_DD`` — string max is also chronological max.
        """
        cached = self._cache.get("livebench_discovery")
        if cached is None:
            response = self._client.get(_CONTENTS_API)
            response.raise_for_status()
            cached = response.text
            self._cache.put("livebench_discovery", cached)
        listing = json.loads(cached)
        dates: list[str] = []
        for entry in listing:
            if not isinstance(entry, dict):
                continue
            match = _TABLE_RE.match(str(entry.get("name", "")))
            if match:
                dates.append(match.group(1))
        if not dates:
            raise RuntimeError(
                "LiveBench: no table_*.csv found at "
                f"{_CONTENTS_API} — repo layout may have changed"
            )
        return max(dates)

    def _fetch_text(self, cache_key: str, url: str) -> str:
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        response = self._client.get(url)
        response.raise_for_status()
        text = response.text
        self._cache.put(cache_key, text)
        return text

    @staticmethod
    def _aggregate(
        table_csv: str,
        categories_json: dict[str, list[str]],
        release: str,
    ) -> list[BenchmarkScore]:
        """Mean each model's per-task scores into per-category composites.

        Drops a (model, category) cell if *every* task in that category
        was missing or non-numeric — emitting a 0 would silently advantage
        models with patchy coverage.
        """
        category_to_tasks: dict[str, list[str]] = {}
        for display_name, tasks in categories_json.items():
            normalized = _CATEGORY_NORMALIZATION.get(display_name)
            if normalized is None:
                continue
            if isinstance(tasks, list):
                category_to_tasks[normalized] = [str(t) for t in tasks]

        now = datetime.now(timezone.utc)
        reader = csv.DictReader(io.StringIO(table_csv))
        out: list[BenchmarkScore] = []
        for row in reader:
            model = row.get("model") or row.get("Model")
            if not model:
                continue
            canonical = canonicalize(model)
            for category, tasks in category_to_tasks.items():
                values: list[float] = []
                for task in tasks:
                    raw = row.get(task)
                    if raw in (None, "", "N/A"):
                        continue
                    try:
                        values.append(float(raw))
                    except (TypeError, ValueError):
                        continue
                if not values:
                    continue
                out.append(
                    BenchmarkScore(
                        canonical_model=canonical,
                        raw_model=model,
                        source="livebench",
                        category=category,
                        score=sum(values) / len(values),
                        fetched_at=now,
                        metadata={
                            "release": release,
                            "tasks_scored": len(values),
                            "tasks_in_category": len(tasks),
                        },
                    )
                )
        return out
