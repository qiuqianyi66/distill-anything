def snapshot(root):
    """夹具代码：只出骨架。"""
    return {"root": root, "nodes": 3}


def act(ref, action):
    if not ref.startswith("ref="):
        raise ValueError("INVALID_ARGS")
    return f"{action}@{ref}"
