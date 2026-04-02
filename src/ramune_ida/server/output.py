"""Output truncation — disk-backed, per-project.

Every MCP tool decorated with ``@register_tool`` (from ``server.app``)
has its return value automatically passed through
:meth:`OutputStore.process` **only when the result contains a
project_id**.  When the serialised result exceeds *max_length* the full
JSON is written to disk and the return value is progressively truncated:

1. Large strings   → preview + "truncated" note
2. Long lists (>30) → first 30 items + ``_truncated`` key
3. Fallback        → scalars only + download URL
"""

from __future__ import annotations

import itertools
import os
from typing import Any

import orjson

_counter = itertools.count(1)

_LIST_CAP = 30
_LIST_MIN = 5


def _make_url(project_id: str, output_id: str, ext: str) -> str:
    """Build a download URL, absolute if request_base_url is available."""
    from ramune_ida.server.app import request_base_url

    base = request_base_url.get("")
    relative = f"/files/{project_id}/outputs/{output_id}{ext}"
    return f"{base}{relative}" if base else relative


class OutputStore:
    """Disk-backed store for truncated output originals.

    Index structure: ``{project_id: {output_id: filepath}}``.
    Actual content lives on disk under each project's ``outputs/`` dir.
    """

    def __init__(
        self,
        max_length: int,
        preview_length: int = 3000,
        max_outputs_per_project: int = 100,
    ) -> None:
        self._max_length = max_length
        self._preview_length = min(preview_length, max_length)
        self._max_outputs = max_outputs_per_project
        self._index: dict[str, dict[str, str]] = {}

    # -- public API ----------------------------------------------------------

    def process(self, data: Any, project_id: str, output_dir: str) -> Any:
        """Truncate *data* if its serialised size exceeds *max_length*.

        Three phases run in order; each phase re-checks the total size
        and returns immediately when within budget.
        """
        if self._measure(data) <= self._max_length:
            return data

        url = self._save_full_json(data, project_id, output_dir)

        data = self._truncate_strings(data, url)
        if self._measure(data) <= self._max_length:
            return data

        data = self._truncate_lists(data, url)
        if self._measure(data) <= self._max_length:
            return data

        return self._fallback(data, url)

    def truncate_if_needed(
        self,
        content: str,
        project_id: str,
        output_dir: str,
    ) -> tuple[str, str | None]:
        """Return *(possibly truncated content, full_output_url or None)*.

        Kept for backward compatibility; saves oversized strings to disk
        individually.
        """
        if len(content) <= self._max_length:
            return content, None

        output_id = f"out-{next(_counter):06d}"
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, f"{output_id}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

        bucket = self._index.setdefault(project_id, {})
        bucket[output_id] = path
        self._evict(bucket)

        url = _make_url(project_id, output_id, ".txt")
        truncated = (
            content[: self._preview_length]
            + f"\n\n... [truncated {len(content)} chars, full output: {url}]"
        )
        return truncated, url

    # -- internals -----------------------------------------------------------

    @staticmethod
    def _measure(data: Any) -> int:
        return len(orjson.dumps(data))

    def _save_full_json(
        self, data: Any, project_id: str, output_dir: str
    ) -> str:
        """Write the complete result as JSON and return its download URL."""
        output_id = f"out-{next(_counter):06d}"
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, f"{output_id}.json")
        with open(path, "wb") as f:
            f.write(orjson.dumps(data, option=orjson.OPT_INDENT_2))

        bucket = self._index.setdefault(project_id, {})
        bucket[output_id] = path
        self._evict(bucket)

        return _make_url(project_id, output_id, ".json")

    def _truncate_strings(self, data: Any, url: str) -> Any:
        """Phase 1: recursively shorten strings longer than preview_length."""
        if isinstance(data, str):
            if len(data) > self._preview_length:
                return (
                    data[: self._preview_length]
                    + f"\n\n... [truncated {len(data)} chars, full output: {url}]"
                )
            return data
        if isinstance(data, dict):
            return {k: self._truncate_strings(v, url) for k, v in data.items()}
        if isinstance(data, list):
            return [self._truncate_strings(item, url) for item in data]
        return data

    def _truncate_lists(self, data: Any, url: str) -> Any:
        """Phase 2: cap lists longer than _LIST_CAP items."""
        if isinstance(data, dict):
            result: dict[str, Any] = {}
            for k, v in data.items():
                if isinstance(v, list) and len(v) > _LIST_CAP:
                    keep = max(_LIST_MIN, _LIST_CAP)
                    result[k] = v[:keep]
                    result["_truncated"] = (
                        f"Showing {keep} of {len(v)} items. "
                        f"Full JSON: {url}"
                    )
                else:
                    result[k] = self._truncate_lists(v, url)
            return result
        if isinstance(data, list):
            if len(data) > _LIST_CAP:
                return data[: max(_LIST_MIN, _LIST_CAP)]
            return [self._truncate_lists(item, url) for item in data]
        return data

    @staticmethod
    def _fallback(data: Any, url: str) -> dict[str, Any]:
        """Phase 3: keep only scalar fields + download URL."""
        result: dict[str, Any] = {"_truncated": f"Output too large. Full JSON: {url}"}
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, (str, int, float, bool)) or v is None:
                    result[k] = v
        return result

    # -- housekeeping --------------------------------------------------------

    def _evict(self, bucket: dict[str, str]) -> None:
        """Remove oldest entries until the bucket is within the limit."""
        while len(bucket) > self._max_outputs:
            oldest_id = next(iter(bucket))
            path = bucket.pop(oldest_id)
            try:
                os.remove(path)
            except FileNotFoundError:
                pass

    def discard_project(self, project_id: str) -> None:
        """Remove all outputs for a project."""
        project_outputs = self._index.pop(project_id, None)
        if project_outputs is None:
            return
        for path in project_outputs.values():
            try:
                os.remove(path)
            except FileNotFoundError:
                pass

    def list_outputs(self, project_id: str) -> dict[str, str]:
        """Return ``{output_id: filepath}`` for a project."""
        return dict(self._index.get(project_id, {}))
