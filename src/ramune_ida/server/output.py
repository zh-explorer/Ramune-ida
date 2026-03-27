"""Output truncation — disk-backed, per-project.

Every MCP tool decorated with ``@register_tool`` (from ``server.app``)
has its return value automatically passed through
:meth:`OutputStore.process` **only when the result contains a
project_id**.  Oversized strings are truncated and the full text is
written to the project's ``outputs/`` directory for later retrieval
via ``GET /files/{project_id}/outputs/{output_id}.txt``.
"""

from __future__ import annotations

import itertools
import os
from typing import Any

_counter = itertools.count(1)


class OutputStore:
    """Disk-backed store for truncated output originals.

    Index structure: ``{project_id: {output_id: filepath}}``.
    Actual content lives on disk under each project's ``outputs/`` dir.
    """

    def __init__(self, max_length: int, max_outputs_per_project: int = 100) -> None:
        self._max_length = max_length
        self._max_outputs = max_outputs_per_project
        self._index: dict[str, dict[str, str]] = {}

    # -- public API ----------------------------------------------------------

    def process(self, data: Any, project_id: str, output_dir: str) -> Any:
        """Recursively walk *data* and truncate any oversized strings.

        *project_id* is used for index bookkeeping and URL generation.
        *output_dir* is the directory where full-text files are written.
        """
        if isinstance(data, str):
            truncated, _ = self.truncate_if_needed(data, project_id, output_dir)
            return truncated
        if isinstance(data, dict):
            return {
                k: self.process(v, project_id, output_dir)
                for k, v in data.items()
            }
        if isinstance(data, list):
            return [self.process(item, project_id, output_dir) for item in data]
        return data

    def truncate_if_needed(
        self,
        content: str,
        project_id: str,
        output_dir: str,
    ) -> tuple[str, str | None]:
        """Return *(possibly truncated content, full_output_url or None)*."""
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

        url = f"/files/{project_id}/outputs/{output_id}.txt"
        truncated = (
            content[: self._max_length]
            + f"\n\n... [truncated, full output: {url}]"
        )
        return truncated, url

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
