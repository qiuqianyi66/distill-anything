def act(ref, action):
    if not ref.startswith("ref="):
        raise ValueError("INVALID_ARGS")
    return f"{action}@{ref}"
