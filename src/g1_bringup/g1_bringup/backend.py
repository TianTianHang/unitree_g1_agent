SUPPORTED_BACKENDS = ("official_loco", "textop")


def backend_plan(backend: str) -> dict[str, object]:
    if backend not in SUPPORTED_BACKENDS:
        allowed = ", ".join(SUPPORTED_BACKENDS)
        raise ValueError(f"invalid motion_backend={backend!r}; expected one of: {allowed}")
    return {
        "g1_interface_backend": backend,
        "start_textop": backend == "textop",
        "start_low_level_guard": backend == "textop",
    }
