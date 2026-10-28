"""'did you mean ...' for mistyped prop, group and target names."""
from __future__ import annotations

import difflib


def layout_names() -> list[str]:
    try:
        from ..layout import store
        from .canonical import read_json
        f = store.folder() / "layout.models.json"
        return [m["id"] for m in read_json(f)["models"]] if f.exists() else []
    except Exception:  # noqa: BLE001
        return []


def suggest(name: str, choices: list[str] | None = None) -> str:
    """' - did you mean 'MegaTree'?' (or a pointer to where names are listed)."""
    choices = layout_names() if choices is None else choices
    low = {c.lower(): c for c in choices}
    hits = difflib.get_close_matches(name.lower(), list(low), n=3, cutoff=0.5)
    if hits:
        return " - did you mean " + " or ".join(f"'{low[h]}'" for h in hits) + "?"
    return " - 'groups --list' and 'inspect layout' show the names"
