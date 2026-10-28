"""Definitions - named terms, kept at levels and read back in one query (0.24.46).

A definition is a text container: a few lines for a reader (the user, Claude with the
seqtool-direction skill) and, if it has one, a machine form ("data": JSON - what a choreography
effect will play). Levels, from the most general:

    show      the whole show                      seqtool-prefs/definitions.json
    show/for  a kind of prop (spinner, matrix, ...), a group, or one prop
    song      this song                            songs.json (the song's entry)
    section   a section of this song (and its repeats, or --only that one) - anchored to a time
              in the song, as pins are, so section edits don't lose it
    (each of song and section can be 'for' props too)

get(name, for, at) merges every entry that applies, most general first: the text lines are
listed with where they come from; the data is merged, a more specific level winning per key.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from . import config, songs

LEVELS = ("show", "song", "section")
CLASS_WORDS = {"LINEAR": "line", "ARC": "arch", "RADIAL": "spinner", "RING": "ring", "SURFACE_2D": "matrix",
               "CONE": "tree", "FIGURE": "figure", "FLOOD": "flood", "POINT": "point", "VOLUME": "3-D",
               "IRREGULAR": "irregular", "STAR": "star", "ORNAMENT": "ornament"}


def _show_file() -> Path:
    return config.user_dir() / "definitions.json"


def show_entries() -> list[dict]:
    f = _show_file()
    try:
        return list(json.loads(f.read_text(encoding="utf-8")).get("definitions", []))
    except (OSError, ValueError):
        return []


def _save_show(entries: list[dict]) -> None:
    f = _show_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"_doc": "seqtool definitions for the whole show ('define' changes them)",
                             "definitions": entries}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def song_entries(sha: str | None) -> list[dict]:
    return list(songs.get(sha).get("definitions") or []) if sha else []


def all_entries(sha: str | None) -> list[dict]:
    return [{**e, "level": "show"} for e in show_entries()] + \
        [{**e, "level": e.get("level", "song")} for e in song_entries(sha)]


def put(entry: dict, sha: str | None) -> str:
    """Add or replace (same name, level, for, place). Returns 'added' or 'changed'."""
    key = _key(entry)
    if entry["level"] == "show":
        es = show_entries()
        how = "changed" if any(_key({**e, "level": "show"}) == key for e in es) else "added"
        es = [e for e in es if _key({**e, "level": "show"}) != key] + [{k: v for k, v in entry.items() if k != "level"}]
        _save_show(es)
        return how
    if not sha:
        raise SystemExit("define: no current song - 'run --audio SONG' first (or --show for the whole show)")
    es = song_entries(sha)
    how = "changed" if any(_key(e) == key for e in es) else "added"
    es = [e for e in es if _key(e) != key] + [entry]
    songs.update(sha, definitions=es)
    return how


def remove(name: str, level: str | None, for_: str | None, at: float | None, sha: str | None, profile) -> int:
    n = 0
    hit = lambda e: _same(e["name"], name) and (level is None or e.get("level", "song") == level) and \
        (for_ is None or (e.get("for") or "").lower() == for_.lower()) and \
        (at is None or (e.get("at") is not None and _sec(profile, e["at"]) is _sec(profile, at)))   # noqa: E731
    es = show_entries()
    keep = [e for e in es if not hit({**e, "level": "show"})]
    if len(keep) != len(es):
        n += len(es) - len(keep)
        _save_show(keep)
    if sha:
        es = song_entries(sha)
        keep = [e for e in es if not hit(e)]
        if len(keep) != len(es):
            n += len(es) - len(keep)
            songs.update(sha, definitions=keep)
    return n


def _same(a: str, b: str) -> bool:
    return " ".join(str(a).lower().split()) == " ".join(str(b).lower().split())


def _key(e: dict) -> tuple:
    return (" ".join(e["name"].lower().split()), e.get("level", "song"), (e.get("for") or "").lower(),
            None if e.get("at") is None else round(float(e["at"]), 1), bool(e.get("repeats", True)))


def _sec(profile, t: float):
    if not profile:
        return None
    from ..matchup.pins import _section_at
    return _section_at(profile, float(t))


class Props:
    """What a 'for' word means: a prop, a group (and everything in it) or a kind of prop."""

    def __init__(self):
        from ..layout import store
        try:
            from .canonical import read_json
            ms = read_json(store.folder() / "layout.models.json")["models"]
        except Exception:  # noqa: BLE001
            ms = []
        self.by = {m["id"].lower(): m for m in ms}
        self.groups = {m["id"].lower(): [x.lower() for x in m.get("members", [])] for m in ms if m["kind"] == "group"}

    def kind_of(self, word: str) -> str | None:
        w = word.lower().rstrip("s")
        if w in self.by:
            return "group" if w in self.groups else "prop"
        if word.lower() in self.by:
            return "group" if word.lower() in self.groups else "prop"
        if w in CLASS_WORDS.values() or w in (c.lower() for c in CLASS_WORDS):
            return "class"
        return None

    def members(self, g: str, seen=()) -> set[str]:
        out = set()
        for x in self.groups.get(g, []):
            if x in self.groups and x not in seen:
                out |= self.members(x, seen + (g,)) | {x}
            else:
                out.add(x)
        return out

    def rank(self, word: str | None, target: str | None) -> int | None:
        """How specifically `word` applies to `target`: 0 = to everything, 1 a kind, 2 a group,
        3 the prop itself; None = not to it."""
        if not word:
            return 0
        if not target:
            return 1                                    # no target asked about: every entry, as listed
        w, t = word.lower(), target.lower()
        if w == t:
            return 3
        if w in self.groups and t in self.members(w):
            return 2
        m = self.by.get(t)
        cls = (m or {}).get("geometry_class", "")
        if m and (w.rstrip("s") == CLASS_WORDS.get(cls, "~") or w == cls.lower()):
            return 1
        if t in self.groups:                            # asked about a group: what is for its members' kind
            kinds = {CLASS_WORDS.get(self.by[x].get("geometry_class", ""), "") for x in self.members(t) if x in self.by}
            if w.rstrip("s") in kinds:
                return 1
        return None


def applying(sha: str | None, profile, for_: str | None, at: float | None, name: str | None = None) -> list[dict]:
    """The entries that apply (to `for_`, at time `at`), most general first, each with 'rank' and
    'where' (its level and place, in words)."""
    P = Props()
    sec_at = _sec(profile, at) if at is not None else None
    out = []
    for e in all_entries(sha):
        if name is not None and not _same(e["name"], name):
            continue
        r = P.rank(e.get("for"), for_)
        if r is None:
            continue
        lvl = e.get("level", "song")
        where = lvl
        if lvl == "section":
            s = _sec(profile, e["at"]) if profile else None
            if sec_at is not None and s is not None:
                from ..matchup.pins import _root
                if not (s is sec_at or (e.get("repeats", True) and _root(profile, s) == _root(profile, sec_at))):
                    continue
            where = (f"#{s['index']} {s.get('type', '')}".strip() if s else f"@{e['at']}") + \
                ("" if e.get("repeats", True) else " only")
        if e.get("for"):
            where += f", for {e['for']}"
        out.append({**e, "rank": r, "where": where})
    out.sort(key=lambda e: (LEVELS.index(e.get("level", "song")), e["rank"]))
    return out


def merge(entries: list[dict]) -> dict:
    """The data of entries (most general first) merged: a later one wins per key, deeply."""
    def deep(a, b):
        if isinstance(a, dict) and isinstance(b, dict):
            out = dict(a)
            for k, v in b.items():
                out[k] = deep(a.get(k), v)
            return out
        return copy.deepcopy(b)
    data: dict = {}
    for e in entries:
        if isinstance(e.get("data"), dict):
            data = deep(data, e["data"])
    return data


def get(name: str, sha, profile, for_=None, at=None) -> dict | None:
    es = applying(sha, profile, for_, at, name)
    if not es:
        return None
    return {"name": es[-1]["name"], "for": for_, "at": at,
            "levels": [{"level": e.get("level", "song"), "where": e["where"], "for": e.get("for"),
                        "text": e.get("text", ""), "data": e.get("data")} for e in es],
            "data": merge(es)}


def names(sha) -> list[str]:
    seen = {}
    for e in all_entries(sha):
        seen.setdefault(" ".join(e["name"].lower().split()), e["name"])
    return sorted(seen.values(), key=str.lower)
