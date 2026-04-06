"""Hatch build hook: build frontend if Node.js is available."""

from __future__ import annotations

import os
import subprocess
import logging

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

log = logging.getLogger(__name__)

FRONTEND_DIR = os.path.join("src", "ramune_ida", "web", "frontend")
WEBUI_DIR = "web-ui"
MIN_NODE = 18
MIN_NPM = 9


def _get_version(cmd: str) -> tuple[int, ...] | None:
    try:
        out = subprocess.check_output([cmd, "--version"], text=True).strip()
        # "v18.17.0" or "9.6.7"
        return tuple(int(x) for x in out.lstrip("v").split("."))
    except Exception:
        return None


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict) -> None:
        # Only build frontend when explicitly requested
        if not os.environ.get("RAMUNE_BUILD_WEB"):
            return

        node_ver = _get_version("node")
        npm_ver = _get_version("npm")

        has_existing = os.path.isfile(os.path.join(FRONTEND_DIR, "index.html"))

        if node_ver is None or npm_ver is None:
            if has_existing:
                log.warning(
                    "Node.js/npm not found — using existing frontend build"
                )
                return
            raise RuntimeError(
                "Node.js and npm are required to build the frontend. "
                "Install Node.js >= %d and npm >= %d" % (MIN_NODE, MIN_NPM)
            )

        if node_ver[0] < MIN_NODE:
            raise RuntimeError(
                "Node.js >= %d required, found %s" % (MIN_NODE, ".".join(map(str, node_ver)))
            )
        if npm_ver[0] < MIN_NPM:
            raise RuntimeError(
                "npm >= %d required, found %s" % (MIN_NPM, ".".join(map(str, npm_ver)))
            )

        if not os.path.isdir(WEBUI_DIR):
            if has_existing:
                log.warning("web-ui/ directory not found — using existing frontend build")
                return
            raise RuntimeError("web-ui/ directory not found and no existing build")

        log.info("Building frontend (node %s, npm %s)...",
                 ".".join(map(str, node_ver)), ".".join(map(str, npm_ver)))

        subprocess.check_call(["npm", "ci"], cwd=WEBUI_DIR)
        subprocess.check_call(["npx", "vite", "build"], cwd=WEBUI_DIR)

        if not os.path.isfile(os.path.join(FRONTEND_DIR, "index.html")):
            raise RuntimeError("Frontend build did not produce output")

        log.info("Frontend build complete")
