"""Test plugin — echoes parameters back for verifying the plugin pipeline."""


def echo_test(params):
    message = params["message"]
    repeat = params.get("repeat", 1)
    return {
        "echoed": message,
        "repeated": message * repeat,
        "count": repeat,
    }


def echo_write_test(params):
    return {"wrote": params["value"]}


def echo_unsafe_test(params):
    return {"status": "unsafe_executed"}
