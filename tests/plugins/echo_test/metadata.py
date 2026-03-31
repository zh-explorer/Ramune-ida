"""Test plugin metadata — verifies the external plugin discovery pipeline."""

TOOLS = [
    {
        "name": "echo_test",
        "description": "Test plugin that echoes back all parameters.",
        "tags": ["test", "kind:read"],
        "params": {
            "message": {
                "type": "string",
                "required": True,
                "description": "Message to echo back",
            },
            "repeat": {
                "type": "integer",
                "required": False,
                "default": 1,
                "description": "Number of times to repeat",
            },
        },
    },
    {
        "name": "echo_write_test",
        "description": "Test plugin tagged as write operation.",
        "tags": ["test", "kind:write"],
        "params": {
            "value": {
                "type": "string",
                "required": True,
            },
        },
    },
    {
        "name": "echo_unsafe_test",
        "description": "Test plugin tagged as unsafe operation.",
        "tags": ["test", "kind:unsafe"],
        "params": {},
    },
]
