"""Server configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class ServerConfig:
    worker_python: str = "python"
    soft_limit: int = 4
    hard_limit: int = 8
    auto_save_interval: float = 300.0
    work_base_dir: str = "~/.ramune-ida/projects"
    output_max_length: int = 50_000
    output_max_per_project: int = 100

    @property
    def resolved_work_base_dir(self) -> str:
        return os.path.expanduser(self.work_base_dir)
