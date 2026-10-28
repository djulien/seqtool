"""Preferences: built-in defaults overlaid by the user's own folder.

Built-in defaults live in <repo>/preferences and are never written to.
User choices live in a user preference folder - by default ~/seqtool-prefs, in
your home folder (0.22.3; before, ./seqtool-prefs wherever seqtool started, which
put one beside songs). Override with --preferences DIR or SEQTOOL_PREFS (a
relative SEQTOOL_PREFS is taken from the folder seqtool started in).
load(name) deep-merges the user's <name>.json over the default, so a user
file only needs the keys it changes. save(name, data) writes the user file.

answers.json in the same folder remembers interactive answers (last kit
folder, viewer choice, accepted channel overlaps, ...) so the next run
offers them as defaults.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .canonical import read_json

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "preferences"
_user_dir: Path | None = None
_default_dir: Path | None = None
_anchor: Path | None = None          # the folder seqtool started in (a relative SEQTOOL_PREFS is from there)


def user_dir() -> Path:
    """Absolute, fixed for the session, so 'cd' at the prompt (or the working folder
    following the current song) doesn't move it."""
    global _default_dir, _anchor
    if _user_dir is not None:
        return _user_dir
    if _default_dir is None:
        if _anchor is None:
            _anchor = Path.cwd()
        env = os.environ.get("SEQTOOL_PREFS")
        _default_dir = (_anchor / env).resolve() if env else (Path.home() / "seqtool-prefs").resolve()
    return _default_dir


def set_user_dir(path: Path | None) -> None:
    """None: back to the default folder (~/seqtool-prefs, or SEQTOOL_PREFS) - never one in the
    working folder now (0.22.1: 'run' after the working folder had moved to the song's looked
    for the layout in <song folder>/seqtool-prefs and said 'no layout')."""
    global _user_dir, _default_dir
    _default_dir = None
    _user_dir = None if path is None or Path(path).resolve() == DEFAULT_DIR else Path(path).resolve()


def reanchor() -> None:
    """Seqtool moved to another folder before doing anything (an unwritable start folder):
    the default preference folder is there."""
    global _anchor, _default_dir
    _anchor, _default_dir = None, None


def _merge(base, over):
    if isinstance(base, dict) and isinstance(over, dict):
        out = dict(base)
        for k, v in over.items():
            out[k] = _merge(base.get(k), v) if k in base else v
        return out
    return over


def load(name: str, pref_dir: Path | None = None) -> dict:
    base = read_json(DEFAULT_DIR / f"{name}.json")
    udir = pref_dir if pref_dir is not None and Path(pref_dir).resolve() != DEFAULT_DIR else user_dir()
    f = Path(udir) / f"{name}.json"
    if f.exists():
        base = _merge(base, read_json(f))
    from .vocab import fold
    return fold(name, base)


def save(name: str, data: dict, pref_dir: Path | None = None) -> Path:
    udir = Path(pref_dir) if pref_dir is not None and Path(pref_dir).resolve() != DEFAULT_DIR else user_dir()
    udir.mkdir(parents=True, exist_ok=True)
    f = udir / f"{name}.json"
    f.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return f


def unset(name: str, keys: list[str], pref_dir: Path | None = None) -> Path:
    """Remove one setting (a path of keys) from the user's file for `name` - the default
    (or guess) applies again (0.21.8). Empty parents are removed too."""
    udir = Path(pref_dir) if pref_dir is not None and Path(pref_dir).resolve() != DEFAULT_DIR else user_dir()
    f = udir / f"{name}.json"
    cur = read_json(f) if f.exists() else {}
    chain, node = [], cur
    for k in keys[:-1]:
        if not isinstance(node.get(k), dict):
            return f
        chain.append((node, k))
        node = node[k]
    node.pop(keys[-1], None)
    for parent, k in reversed(chain):
        if parent[k] == {}:
            parent.pop(k)
    return save(name, cur, pref_dir)


def update(name: str, changes: dict, pref_dir: Path | None = None) -> Path:
    """Merge `changes` into the user's file for `name` (not the defaults)."""
    udir = Path(pref_dir) if pref_dir is not None and Path(pref_dir).resolve() != DEFAULT_DIR else user_dir()
    f = udir / f"{name}.json"
    cur = read_json(f) if f.exists() else {}
    return save(name, _merge(cur, changes), pref_dir)


def music_prefs(pref_dir: Path | None = None) -> dict:
    return load("music", pref_dir)


# ---- remembered answers ----------------------------------------------------
def answer(key: str, default=None):
    f = user_dir() / "answers.json"
    if f.exists():
        try:
            return read_json(f).get(key, default)
        except Exception:
            return default
    return default


def remember(key: str, value) -> None:
    f = user_dir() / "answers.json"
    cur = {}
    if f.exists():
        try:
            cur = read_json(f)
        except Exception:
            cur = {}
    cur[key] = value
    user_dir().mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(cur, indent=2) + "\n", encoding="utf-8")


def old_folder_note() -> str | None:
    """0.22.3: a ./seqtool-prefs in the start folder that isn't the one used any more - say
    where settings are kept now (the user moves it; seqtool doesn't move files)."""
    old = (_anchor or Path.cwd()) / "seqtool-prefs"
    try:
        if old.is_dir() and old.resolve() != user_dir() and not os.environ.get("SEQTOOL_PREFS"):
            return (f"settings are kept in {user_dir()} now (since 0.22.3), not in {old} - move that folder's "
                    f"contents there to keep them (or start with SEQTOOL_PREFS={old})")
    except OSError:
        pass
    return None
