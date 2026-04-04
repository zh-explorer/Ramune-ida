"""Framework-reserved tag constants.

Tags are plain strings in each tool's ``metadata.py`` ``tags`` list.
Prefixed tags (``prefix:value``) carry structured semantics; the
framework only acts on tags defined here.  Plugins may use any
custom tags freely — unrecognised tags are passed through untouched.

Grep ``TAG_KIND`` to find all framework tag checks.
"""

from __future__ import annotations

TAG_KIND_READ: str = "kind:read"
TAG_KIND_WRITE: str = "kind:write"
TAG_KIND_UNSAFE: str = "kind:unsafe"
TAG_MCP_FALSE: str = "mcp:false"
