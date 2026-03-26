"""Global instance counter + limits."""

from __future__ import annotations


class Limiter:
    """Tracks live worker instances by project_id against soft/hard limits.

    soft_limit : advisory threshold reported to AI.  0 = off.
    hard_limit : spawn refused at this count.  0 = unlimited.
    """

    def __init__(
        self,
        soft_limit: int = 4,
        hard_limit: int = 8,
    ) -> None:
        self._soft_limit = soft_limit
        self._hard_limit = hard_limit
        self._active: set[str] = set()

    @property
    def instance_count(self) -> int:
        return len(self._active)

    @property
    def active_projects(self) -> frozenset[str]:
        return frozenset(self._active)

    @property
    def can_spawn(self) -> bool:
        return self._hard_limit == 0 or len(self._active) < self._hard_limit

    @property
    def over_soft_limit(self) -> bool:
        return self._soft_limit > 0 and len(self._active) > self._soft_limit

    def on_spawned(self, project_id: str) -> None:
        self._active.add(project_id)

    def on_destroyed(self, project_id: str) -> None:
        self._active.discard(project_id)
