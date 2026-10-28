# seqtool-command: reroll | main | refine | new random choices: reroll [TARGET] [@#N|@TIME] [--seed N] [--undo]
"""seqtool reroll [TARGET] [@#N | @TIME] [--seed N] [--undo]

Gives part of the plan a new seed, re-runs the last 'run' or 'demo' (the
analysis is reused, so it is quick) and shows what changed.

    reroll                    new master seed for the whole song
    reroll MegaTree           new seed for one target (prop or group)
    reroll @#3                new seed for section 3 - and its repeats, so
                              repeated material still matches
    reroll MegaTree @#3       one target in one section (and its repeats)
    reroll ... --seed 42      use a specific seed instead of a random one
    reroll --undo             go back one reroll

Seeds are remembered per song (see 'inspect audio').
"""
from __future__ import annotations

import argparse
import importlib
import os
import random
import sys
from pathlib import Path

from ..common import config, songs
from ..common.canonical import read_json
from ..common.log import good, info, set_level, warn


def deferred_note() -> str:
    """What a deferred change says (a batch, or --later)."""
    why = _DEFER.get("why")
    if why == "gui":
        return "the plan follows a few seconds after your last change"
    return "planned later - 'replan' makes it now" if why == "later" else "planned at the end of the batch"


def _context():
    lm = config.answer("last_matchup")
    if not lm or not Path(lm).exists():
        raise SystemExit("nothing to reroll yet - run 'seqtool run' (or 'demo') first")
    m = read_json(lm)
    folder = Path(lm).parent
    profile = read_json(folder / m["source"]["music_profile"]["filename"])
    sha = m.get("lineage", {}).get("audio")
    return Path(lm), m, profile, sha


def _repeat_root(profile: dict, sec: dict) -> str:
    ids = {s["id"]: s for s in profile["sections"]}
    root = sec
    while root.get("repeat_of") in ids:
        root = ids[root["repeat_of"]]
    return root["id"]


def plan_columns(m: dict, profile: dict) -> dict:
    """(target, section index) -> (effect sequence, parameters, palette)"""
    from ..baseline import label
    out = {}
    for p in m["plans"]:
        for s in profile["sections"]:
            segs = [g for g in p["segments"] if g["start"] < s["end"] - 1e-6 and g["end"] > s["start"] + 1e-6]
            out[(label(p), s["index"])] = ("/".join(dict.fromkeys(g["selected"]["effect"] for g in segs)),
                                              [g.get("parameters", {}) for g in segs],
                                              [g.get("palette") for g in segs])
    return out


def diff(old: dict, new: dict, profile: dict) -> list[str]:
    types = {s["index"]: s.get("type", "?") for s in profile["sections"]}
    lines, params = [], 0
    rests: dict[int, list[str]] = {}
    for key in sorted(set(old) | set(new), key=lambda k: (k[0], k[1])):
        a, b = old.get(key), new.get(key)
        if a is None or b is None:            # a layer appeared or went away
            a, b = a or ("", [], []), b or ("", [], [])
        if a[0] != b[0]:
            if a[0] and not b[0]:             # now resting (e.g. a top group took over): one line per section
                rests.setdefault(key[1], []).append(key[0])
                continue
            lines.append(f"  {key[0]:<22} #{key[1]} {types[key[1]]:<10} {a[0] or '-'}  ->  {b[0] or '-'}")
        elif a[1] != b[1]:
            params += 1
    for sec, names in sorted(rests.items()):
        shown = ", ".join(names[:4]) + (f" and {len(names) - 4} more" if len(names) > 4 else "")
        lines.append(f"  #{sec} {types[sec]:<10} {len(names)} target(s) now rest there (no effect): {shown}")
    if params:
        lines.append(f"  (+ {params} target/section(s) with the same effect but new settings, e.g. direction)")
    return lines


_DEFER = {"n": 0, "pending": False}          # 0.24.29: inside 'batch' the plan is made once, at the end


def deferring() -> bool:
    return _DEFER["n"] > 0


def rerun() -> None:
    """Run the plan again after an explicit change (pin, react, reroll, promote ...). Stale
    intermediate files are rebuilt without asking (0.24.11: the question could hide under the
    GUI's magnifier, so the change seemed to do nothing) - unless --stale=warn was chosen."""
    if _DEFER["n"]:
        _DEFER["pending"] = True
        return
    from ..common import freshness
    old = freshness._mode
    if old == "ask":
        freshness.set_mode("rebuild")
    import time
    from ..common import log as _log
    _log.STAGES.clear()
    t0 = time.monotonic()
    _log.PROGRESS = True
    try:
        _rerun()
        config.remember("replan_pending", False)       # 0.24.40: nothing waits for a plan any more
    finally:
        _log.PROGRESS = False
        _log.progress_end()                       # 0.24.32: the progress line goes; the results stay
        freshness.set_mode(old)
    took = time.monotonic() - t0                  # 0.24.27: where a slow re-plan spends its time
    from ..demo import run as _run
    if _run.EXPORT_SKIPPED:
        info("  (the .xsq for xLights is out of date now: 'xlights-export' or 4. Export writes it - "
             "'pref xlights.export_on_replan = true' writes it after every change)")
    if took >= 4.0 and _log.STAGES:
        st = _log.STAGES
        ends = [b for _, b in st[1:]] + [time.monotonic()]
        parts = [(st[0][1] - t0, "starting (reading and checking files)")] + \
            [(e - b, name) for (name, b), e in zip(st, ends)]
        parts.sort(reverse=True)
        info(f"  (re-planned in {_log.seconds(took)}: "
             + ", ".join(f"{n} {_log.seconds(d)}" for d, n in parts[:4] if d >= 0.3) + ")")


def _rerun() -> None:
    lr = config.answer("last_run")
    if not lr:
        raise SystemExit("no previous run recorded - 'run' first")
    from ..__main__ import discover
    mod, func, _, _ = discover()[lr["cmd"]]
    here = Path.cwd()
    os.chdir(lr.get("cwd", here))
    set_level(45)
    try:
        argv, skip = [], 0
        for x in lr["argv"]:               # a rerun keeps the seed it was given: no viewer, no seed search
            if skip:
                skip -= 1
            elif x in ("--view", "--candidates"):
                skip = 1
            elif not x.startswith(("--view=", "--candidates=")):
                argv.append(x)
        argv += ["--view", "none"]
        if lr["cmd"] == "run":
            argv.append("--replan")                   # 0.24.28: no timeline page, no export (said)
        import io
        out = sys.stdout
        if hasattr(out, "local"):                     # GUI router: silence just this thread
            prev = getattr(out.local, "target", None)
            out.local.target = io.StringIO()
            try:
                getattr(importlib.import_module(mod), func)(argv)
            finally:
                out.local.target = prev
        else:
            from contextlib import redirect_stdout
            with redirect_stdout(io.StringIO()):
                getattr(importlib.import_module(mod), func)(argv)
    finally:
        set_level(int(os.environ.get("SEQTOOL_DEBUG", "10")))
        os.chdir(here)
    config.remember("last_run", lr)                 # the rerun re-recorded itself; keep the original


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool reroll", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("where", nargs="*", help="TARGET and/or @#N / @TIME")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--undo", action="store_true")
    a = ap.parse_args(argv)
    path, old_m, profile, sha = _context()
    rec = songs.get(sha)
    hist = list(rec.get("seed_history", []))
    overrides = songs.seed_overrides(sha)

    if a.undo:
        if not hist:
            raise SystemExit("nothing to undo")
        h = hist.pop()
        key, prev = h["key"], h["previous"]
        if key == "":
            songs.update(sha, seed=prev, seed_history=hist)
        else:
            if prev is None:
                overrides.pop(key, None)
            else:
                overrides[key] = prev
            songs.update(sha, seed_overrides=overrides, seed_history=hist)
        label = f"undid reroll of {key or 'the whole song'}"
    else:
        target, sec_key, sec_label = None, None, ""
        times = [w for w in a.where if w.startswith("@")]
        names = [w for w in a.where if not w.startswith("@")]
        if times:
            from .explain import parse_time
            t = parse_time(times[0], profile)
            sec = next((s for s in profile["sections"] if s["start"] <= t < s["end"]), profile["sections"][-1])
            sec_key = _repeat_root(profile, sec)
            reps = [f"#{s['index']}" for s in profile["sections"] if _repeat_root(profile, s) == sec_key]
            sec_label = f"section {', '.join(reps)}"
        if names:
            from .explain import resolve_target
            target, note = resolve_target(old_m, " ".join(names))
            if note:
                info(note)
        key = (target or "") + (f"@{sec_key}" if sec_key else "")
        new = a.seed if a.seed is not None else random.SystemRandom().randrange(1, 1_000_000)
        prev = (rec.get("seed") if key == "" else overrides.get(key))
        hist.append({"key": key, "previous": prev})
        if key == "":
            songs.update(sha, seed=new, seed_history=hist[-50:])
        else:
            overrides[key] = new
            songs.update(sha, seed_overrides=overrides, seed_history=hist[-50:])
        label = f"rerolled {' in '.join(x for x in (target, sec_label) if x) or 'the whole song'} (seed {new})"

    old_cols = plan_columns(old_m, profile)
    old_pal = old_m.get("palettes")
    if deferring():
        rerun()
        good(label + "  {note}(" + deferred_note() + "){/}")
        return 0
    info("re-running the plan (analysis is reused) ...")
    rerun()
    new_path = Path(config.answer("last_matchup"))
    new_m = read_json(new_path)
    lines = diff(old_cols, plan_columns(new_m, profile), profile)
    if new_m.get("palettes") != old_pal:
        lines.append("  palette changed")
    good(label)
    if not a.undo:                     # pinned effects keep their effect: only their settings are new
        scope_t = target
        scope_s = None if not sec_key else {s["index"] for s in profile["sections"] if _repeat_root(profile, s) == sec_key}
        pinned = sorted({(p["target"], g.get("section_index")) for p in new_m["plans"] for g in p["segments"]
                         if g.get("pinned") and (scope_t is None or p["target"] == scope_t)
                         and (scope_s is None or g.get("section_index") in scope_s)})
        if pinned:
            info("  pinned, so the effect stays and only its settings (direction, speed ...) are new: "
                 + ", ".join(f"{t} #{i}" for t, i in pinned[:6]) + (" ..." if len(pinned) > 6 else ""))
    if lines:
        print("\n".join(lines))
    else:
        warn("no visible change: the new seed didn't flip any choice here - reroll again, or --undo")
    return 0


if __name__ == "__main__":
    sys.exit(main())
