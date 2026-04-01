"""Server configuration."""

from __future__ import annotations

import os

from pydantic import BaseModel

ENV_DATA_DIR = "RAMUNE_DATA_DIR"
DEFAULT_DATA_DIR = "~/.ramune-ida"


class ServerConfig(BaseModel):
    worker_python: str = "python"
    soft_limit: int = 4
    hard_limit: int = 8
    auto_save_interval: float = 300.0
    data_dir: str = DEFAULT_DATA_DIR
    output_max_length: int = 20_000
    output_preview_length: int = 3_000
    output_max_per_project: int = 100
    plugins_enabled: bool = True

    @property
    def resolved_data_dir(self) -> str:
        return os.path.expanduser(self.data_dir)

    @property
    def resolved_work_base_dir(self) -> str:
        return os.path.join(self.resolved_data_dir, "projects")

    @property
    def resolved_plugin_dir(self) -> str | None:
        path = os.path.join(self.resolved_data_dir, "plugins")
        return path if os.path.isdir(path) else None
