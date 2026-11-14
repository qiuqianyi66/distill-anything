def snapshot(root):
    """夹具代码：raw 里有可读代码，产物却一条都没引用它。"""
    return {"root": root, "nodes": 3}


def act(ref, action):
    if not ref.startswith("ref="):
        raise ValueError("INVALID_ARGS")
    return f"{action}@{ref}"
