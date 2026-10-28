"""Per-song settings, kept in seqtool-prefs/songs.json and keyed by the audio
file's sha256 (so renaming or moving the file doesn't lose them):

    seed            the song's master seed (default: derived from the audio, so
                    every song starts different but reproducible)
    seed_overrides  {"MegaTree": n, "@S03": n, "MegaTree@S03": n} - seeds for one
                    target, one section (and its repeats), or one target in one section
    seed_history    undo stack for reroll
    sections        user edits: {"boundaries": [t, ...], "types": {"t": "chorus"}}
"""
from __future__ import annotations

import json
from pathlib import Path

from . import config


def _file() -> Path:
    return config.user_dir() / "songs.json"


def _all() -> dict:
    f = _file()
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            return {}
    return {}


def get(sha: str) -> dict:
    return _all().get(sha, {})


def update(sha: str, name: str | None = None, **changes) -> dict:
    data = _all()
    rec = data.setdefault(sha, {})
    if name:
        rec["name"] = name
    elif "name" not in rec:                          # 0.21.3: 'songs' lists them by name
        try:
            from .canonical import read_json
            lm, la = config.answer("last_music"), config.answer("last_audio")
            if lm and la and Path(lm).exists() and read_json(Path(lm)).get("lineage", {}).get("audio") == sha:
                rec["name"] = Path(la).name
        except Exception:  # noqa: BLE001
            pass
    if changes.get("lyrics"):                        # 0.24.0: {VOICE} codes -> each word's voice
        from ..music.voices import normalize
        normalize(changes["lyrics"])
    for k, v in changes.items():
        if v is None:
            rec.pop(k, None)
        else:
            rec[k] = v
    config.user_dir().mkdir(parents=True, exist_ok=True)
    _file().write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return rec


def derived_seed(sha: str) -> int:
    return int(sha[:8], 16) % 100000 + 1


def seed(sha: str) -> int:
    return int(get(sha).get("seed") or derived_seed(sha))


def seed_overrides(sha: str) -> dict:
    return dict(get(sha).get("seed_overrides", {}))


def section_edits(sha: str) -> dict:
    return dict(get(sha).get("sections", {}))


def effective_seed(master: int, overrides: dict, target: str, repeat_key: str) -> int:
    """Most specific override wins: target@section, then target, then @section."""
    for k in (f"{target}@{repeat_key}", target, f"@{repeat_key}"):
        if k in overrides:
            return int(overrides[k])
    return master
