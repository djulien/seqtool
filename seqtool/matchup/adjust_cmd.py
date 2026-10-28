# seqtool-command: adjust | main | refine | settings over whatever plays there (faces too): adjust Matrix @#1 rotation=180deg..360deg --on face
"""seqtool adjust TARGET [@#N | @TIME] NAME=VALUE ... [from=@T] [until=@T] [--only] [--on LAYER]
       adjust                          list this song's adjustments
       adjust TARGET --remove [@#N]    take them off

An adjustment (0.24.57) changes settings of whatever plays on TARGET there - its own effects, a
reaction, a singing face, a choreography's parts - without choosing the effect. The settings any
effect takes (xLights' Layer Settings): rotation (Roto-Zoom Z: 180deg, 6oclock, a share of a
turn), area (x,y,w,h), render (default | per-model); 'a..b' or 'a..b..c' glide over the time it
covers (an xLights value curve once the kit has learned them).

    adjust Matrix @#1 rotation=180deg until=@ready --on face
                                 the face upside down until the word 'ready'
    adjust Matrix @#1 rotation=180deg..360deg until=@ready --on face
                                 ... turning upright (clockwise) by then
    adjust Matrix @0:12 rotation=90deg --only           section at 0:12 only, every layer
    adjust Matrix --remove @#1   take the adjustments in section 1 off

@#N: that section and its repeats (--only: that one); none: the whole song. from= / until=
(onset= / offset=, as pins take them): part of the section - then that section only.
--on: only that layer - face (or a face's name), react, choreo, pin, main, top, detail,
enhance, base. Kept per song (songs.json 'adjust'); the song's score lists them.
"""
from __future__ import annotations

import argparse
import sys

from ..common import songs
from ..common.log import good, info

LAYERS = ("face", "react", "choreo", "pin", "main", "top", "detail", "enhance", "base", "place", "borrowed")


def _ctx():
    from .reroll import _context
    path, m, profile, sha = _context()
    if not sha:
        raise SystemExit("adjust: no current song - 'run --audio SONG' first")
    return m, profile, sha


def describe(e: dict, profile) -> str:
    from .pins import _section_at
    from .score_cmd import _val
    where = "whole song"
    if e.get("at") is not None:
        s = _section_at(profile, float(e["at"]))
        where = f"#{s['index']} {s.get('type', '')}".strip() + ("" if e.get("repeats", True) else " only")
    part = "".join(f" {k}={v}" for k, v in (("from", e.get("from")), ("until", e.get("until"))) if v)
    sets = " ".join(f"{k}={_val(v)}" for k, v in (e.get("params") or {}).items())
    return f"  {e['target']:<24} {where:<22} {sets}{part}" + (f"  (on {e['on']})" if e.get("on") else "")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool adjust", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("words", nargs="*", help="TARGET [@#N|@TIME] NAME=VALUE ...")
    ap.add_argument("--only", action="store_true", help="that section only, not its repeats")
    ap.add_argument("--on", default=None, metavar="LAYER", help="only this layer: " + ", ".join(LAYERS) + ", or a face's name")
    ap.add_argument("--remove", action="store_true", help="take this target's adjustments off (there)")
    a = ap.parse_args(argv)
    m, profile, sha = _ctx()
    ents = list(songs.get(sha).get("adjust") or [])
    if not a.words:
        if not ents:
            print("no adjustments for this song - e.g. 'adjust Matrix @#1 rotation=180deg --on face'")
            return 0
        print(f"{{head}}adjustments{{/}} ({len(ents)}):")
        for e in ents:
            print(describe(e, profile))
        return 0
    from .explain import parse_time, resolve_target
    from .parts import EXTRA_SPECS
    from .pins import TRIM_ALIASES, _section_at, trim_text
    times = [w for w in a.words if w.startswith("@")]
    given = [w for w in a.words if "=" in w and not w.startswith("@")]
    names = [w for w in a.words if w not in times and w not in given]
    if not names:
        raise SystemExit("adjust TARGET [@#N] NAME=VALUE - e.g. 'adjust Matrix @#1 rotation=180deg --on face'")
    target, note = resolve_target(m, " ".join(names))
    if note:
        info(note)
    at = None
    if times:
        t = parse_time(times[0], profile)
        sec = _section_at(profile, t)
        at = round((sec["start"] + sec["end"]) / 2, 3) if times[0].startswith("@#") else round(t, 3)
    if a.remove:
        keep = [e for e in ents if not (e["target"] == target and (at is None or (
            e.get("at") is not None and _section_at(profile, float(e["at"])) is _section_at(profile, at))))]
        if len(keep) == len(ents):
            raise SystemExit(f"adjust --remove: no adjustment of {target} there - 'adjust' lists them")
        songs.update(sha, adjust=keep)
        label = f"{len(ents) - len(keep)} adjustment(s) of {target} taken off"
    else:
        if not given:
            raise SystemExit(f"adjust {target}: which settings? - e.g. 'adjust {target} @#1 rotation=180deg' "
                             f"({', '.join(EXTRA_SPECS)})")
        from .parameters import glide_value
        params, part = {}, {}
        for g in given:
            k, v = g.split("=", 1)
            k = TRIM_ALIASES.get(k.lower(), k.lower())
            if k in ("onset", "offset"):
                try:
                    part["from" if k == "onset" else "until"] = trim_text(v, profile)
                except ValueError as e:
                    raise SystemExit(f"adjust: {k}={v}: {e} - e.g. 'until=@ready', 'from=2b'") from None
                continue
            if k not in EXTRA_SPECS:
                raise SystemExit(f"adjust: '{k}' isn't a setting every effect takes ({', '.join(EXTRA_SPECS)}) - "
                                 f"an effect's own settings go with a pin: 'pin {target} @#N EFFECT {k}=...'")
            try:
                params[k] = glide_value(k, EXTRA_SPECS[k], v)
            except ValueError as e:
                raise SystemExit(f"adjust: {e} - e.g. 'rotation=180deg..360deg'") from None
            if k == "render":
                params[k] = str(params[k]).replace("-", "_")
        if part and at is None:
            raise SystemExit("adjust: from= / until= need the section - e.g. 'adjust Matrix @#1 rotation=180deg until=@ready'")
        new = {"target": target, "at": at, "repeats": not a.only and not part, "params": params, **part}
        if a.on:
            new["on"] = a.on
        same = lambda e: (e["target"], e.get("at"), e.get("on")) == (target, at, a.on)   # noqa: E731
        ents = [e for e in ents if not same(e)] + [new]
        songs.update(sha, adjust=ents)
        label = "adjusted:" + describe(new, profile)
    from .pins import _apply_and_show
    _apply_and_show(label, m, profile)
    return 0


def _spans(e: dict, profile: dict, song_end: float) -> list[tuple[float, float]]:
    from .explain import parse_time
    from .pins import _root, _section_at, trim_seconds
    if e.get("at") is None:
        return [(0.0, song_end)]
    own = _section_at(profile, float(e["at"]))
    if e.get("from") or e.get("until"):
        a = trim_seconds(e["from"], own, profile, False) if e.get("from") else own["start"]
        b = trim_seconds(e["until"], own, profile, True) if e.get("until") else own["end"]
        if str(e.get("until", "")).startswith("@"):
            b = parse_time(e["until"], profile)
        return [(a, b)] if b > a else []
    secs = [s for s in profile["sections"] if s is own or (e.get("repeats", True) and _root(profile, s) == _root(profile, own))]
    return [(s["start"], s["end"]) for s in secs]


def _layer_of(p: dict) -> str:
    if p.get("pass") == "face":
        return "face"
    if p.get("react"):
        return "react"
    return p.get("pass", "main")


def apply(plans: list[dict], entries: list[dict], profile: dict, song_end: float, notes: list[str]) -> list[dict]:
    """Each adjustment's settings on the segments it covers (cut at its edges); glides get 'over'
    (the adjustment's span), so each part keeps its share of the glide."""
    from ..common.vocab import lit
    for e in entries or []:
        spans = _spans(e, profile, song_end)
        hits = 0
        for p in plans:
            if p["target"] != e["target"]:
                continue
            on = e.get("on")
            if on and on != _layer_of(p) and not (p.get("pass") == "face" and str(p.get("face", "")).lower() == on.lower()):
                continue
            out = []
            for g in p["segments"]:
                if not lit(g["selected"]["effect"]):
                    out.append(g)
                    continue
                cuts = sorted({x for a, b in spans for x in (a, b) if g["start"] + 1e-3 < x < g["end"] - 1e-3})
                bounds = [g["start"], *cuts, g["end"]]
                for lo, hi in zip(bounds, bounds[1:]):
                    q = {**g, "start": round(lo, 3), "end": round(hi, 3)}
                    span = next(((a, b) for a, b in spans if a - 1e-3 <= (lo + hi) / 2 < b + 1e-3), None)
                    if span:
                        pars = dict(q.get("parameters") or {})
                        for k, v in e["params"].items():
                            pars[k] = {**v, "over": [round(span[0], 3), round(span[1], 3)]} if isinstance(v, dict) else v
                        why = "adjusted: " + " ".join(f"{k}=" + (str(v) if not isinstance(v, dict) else "glide")
                                                       for k, v in e["params"].items())
                        q = {**q, "parameters": pars, "yours": sorted(set(q.get("yours") or []) | set(e["params"])),
                             "reasons": list(q.get("reasons") or []) + [why]}
                        hits += 1
                    out.append(q)
            p["segments"] = out
        if not hits:
            notes.append(f"adjust {e['target']}: nothing plays there" + (f" on its {e['on']} layer" if e.get("on") else "")
                         + " to adjust - 'adjust' lists them, 'adjust " + e["target"] + " --remove' takes one off")
    return plans


if __name__ == "__main__":
    sys.exit(main())
