# seqtool-command: baseline | main | tools | keep plans for a few songs, then see what a settings change did: baseline add [SONG] | baseline diff
"""seqtool baseline : what did my change do?  Keep the plans for a few songs, change
settings, then compare.

    baseline add                      add the current song (its plan as it is now)
    baseline add SONG [SONG ...]      add these songs (globs ok: baseline add '../Songs/*.mp3')
    baseline remove SONG | N          take a song out ('baseline' numbers them)
    baseline diff                     run the songs again; list every changed choice
    baseline update [SONG | N ...]    accept the current results as the new baseline
                                      (all songs, or the ones named)
    baseline                          list baselines and their songs

    --name NAME                       keep several baselines (default: 'default')

A plan is kept as a table of the chosen effects per target and section (like the
summary file), plus the sections, palette and validation counts. 'diff' prints only
what changed, e.g.  MegaTree  #3 chorus  spirals -> meteors.

Each song is run as 'run --audio SONG' with your current settings and stored layout;
analysis files are reused when fresh. Nothing is asked while it runs. The current
song and the last run (for 'reroll') are restored afterwards.

Typical use while tuning:  baseline add 'songs/*.mp3', then  pref ... = ..., then
baseline diff. Keep the change ('baseline update'), or 'pref reset ...' and diff again.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from contextlib import redirect_stderr, redirect_stdout
from glob import glob
from pathlib import Path

from . import __version__
from .common import config
from .common.canonical import read_json
from .common.log import good, info
from .common.paths import show

RESTORE = ("last_run", "last_audio", "last_music", "last_matchup", "last_out")


def songs_of(name: str = "default") -> list[Path]:
    """The songs of a baseline, in the order 'baseline' lists them (1, 2, ...); songs
    that have moved are followed."""
    from .common.current import relocate
    f = store() / f"{name}.json"
    if not f.exists():
        return []
    return [relocate(Path(s)) or Path(s) for s in read_json(f)["songs"]]


def store() -> Path:
    return config.user_dir() / "baselines"


def label(p: dict) -> str:
    if p.get("react"):
        return p["target"] + " (react)"
    ps = p.get("pass", "main")
    return p["target"] + (f" ({'placed' if ps == 'place' else ps})" if ps != "main" else "")


def snapshot(music: dict, profile: dict, matchup: dict, validation: dict | None) -> dict:
    """The parts of a run worth comparing: sections, effect per target and section, palette."""
    from .demo.run import section_columns
    secs = profile["sections"]
    cols = section_columns(profile, matchup)
    cells = {label(p): [c[k] for c in cols] for k, p in enumerate(matchup["plans"])}
    return {
        "tempo": round(music["analysis"]["summary"]["tempo"]["bpm"], 1),
        "sections": [{"index": s["index"], "type": s.get("type", "?"), "start": round(s["start"], 1),
                      "end": round(s["end"], 1)} for s in secs],
        "cells": cells,
        "palette": matchup.get("palettes", {}).get("base", {}).get("colors", []),
        "seed": matchup.get("settings", {}).get("seed"),
        "validation": {k: validation["summary"].get(k, 0) for k in ("errors", "warnings", "info")} if validation else {},
    }


def run_song(song: Path, extra: list[str]) -> dict:
    """Run the pipeline quietly for one song and return its snapshot."""
    from .demo.run import main_run
    old = os.environ.get("SEQTOOL_NONINTERACTIVE")
    os.environ["SEQTOOL_NONINTERACTIVE"] = "1"               # never stop to ask in the middle of a batch
    buf = io.StringIO()
    try:
        with redirect_stdout(buf), redirect_stderr(buf):
            rc = main_run(["--audio", str(song), "--view", "none", "--quiet", *extra])
    except SystemExit as e:
        raise SystemExit(f"baseline: {song.name} failed: {e}")
    finally:
        if old is None:
            os.environ.pop("SEQTOOL_NONINTERACTIVE", None)
        else:
            os.environ["SEQTOOL_NONINTERACTIVE"] = old
    if rc:
        raise SystemExit(f"baseline: {song.name} failed:\n{buf.getvalue()[-2000:]}")
    mu = Path(config.answer("last_matchup"))
    stem = mu.name.split(".matchup")[0]
    music = read_json(mu.with_name(f"{stem}.music.json"))
    profile = read_json(mu.with_name(f"{stem}.music-profile.json"))
    vf = mu.with_name(mu.name.replace(".matchup", ".validation"))
    return snapshot(music, profile, read_json(mu), read_json(vf) if vf.exists() else None)


def run_all(songs: list[Path], extra: list[str]) -> dict[str, dict]:
    keep = {k: config.answer(k) for k in RESTORE}
    out = {}
    try:
        for n, s in enumerate(songs, 1):
            print(f"  [{n}/{len(songs)}] {show(s)}", flush=True)
            out[str(s.resolve())] = run_song(s, extra)
    finally:
        for k, v in keep.items():
            if v is not None:
                config.remember(k, v)
    return out


def _old_at(old_secs: list, new_secs: list, i: int) -> int | None:
    """Position of the old section playing at the middle of new section i."""
    if i >= len(new_secs):
        return None
    ns = new_secs[i]
    end = ns.get("end", new_secs[i + 1]["start"] if i + 1 < len(new_secs) else ns["start"] + 1)
    mid = (ns["start"] + end) / 2
    for j, os_ in enumerate(old_secs):
        o_end = os_.get("end", old_secs[j + 1]["start"] if j + 1 < len(old_secs) else float("inf"))
        if os_["start"] <= mid < o_end:
            return j
    return len(old_secs) - 1 if old_secs else None


def compare(old: dict, new: dict) -> list[str]:
    """Lines describing what changed between two snapshots of one song ([] = nothing)."""
    lines = []
    if old["tempo"] != new["tempo"]:
        lines.append(f"tempo {old['tempo']} -> {new['tempo']} BPM")
    os_, ns = old["sections"], new["sections"]
    same_secs = [(a["type"], a["start"]) for a in os_] == [(b["type"], b["start"]) for b in ns]
    if not same_secs:
        lines.append("sections: " + " ".join(f"#{s['index']}{s['type'][:3]}" for s in os_) + "  ->  "
                     + " ".join(f"#{s['index']}{s['type'][:3]}" for s in ns)
                     + "  (effects compared at the same moments)")
    if old["palette"] != new["palette"]:
        lines.append(f"palette {' '.join(old['palette'])} -> {' '.join(new['palette'])}")
    if old.get("seed") != new.get("seed"):
        lines.append(f"seed {old.get('seed')} -> {new.get('seed')}")
    names = {s["index"]: f"#{s['index']} {s['type']}" for s in ns}
    w = max([len(t) for t in set(old["cells"]) | set(new["cells"])] + [8])
    changed = total = 0
    for t in sorted(set(old["cells"]) | set(new["cells"])):
        a, b = old["cells"].get(t), new["cells"].get(t)
        if a is None:
            lines.append(f"{{ok}}+ {t}{{/}}  new: " + "  ".join(b))
            continue
        if b is None:
            lines.append(f"{{warn}}- {t}{{/}}  no longer planned")
            continue
        for i, y in enumerate(b):
            j = i if same_secs else _old_at(os_, ns, i)
            x = a[j] if j is not None and j < len(a) else ""
            total += 1
            if x != y:
                changed += 1
                idx = ns[i]["index"] if i < len(ns) else i + 1
                lines.append(f"  {t:<{w}}  {names.get(idx, '#' + str(idx)):<14}  {x or '-'} -> {{b}}{y or '-'}{{/}}")
    ov, nv = old.get("validation", {}), new.get("validation", {})
    if ov != nv and nv:
        lines.append("validation: " + ", ".join(f"{k} {ov.get(k, 0)} -> {nv.get(k, 0)}" for k in nv
                                                if ov.get(k, 0) != nv.get(k, 0)))
    if changed:
        lines.insert(0, f"{changed} of {total} choices changed")
    return lines


def _songs(patterns: list[str]) -> list[Path]:
    out = []
    for p in patterns:
        raw = os.path.expanduser(p.strip("'\""))
        hits = sorted(glob(raw)) if any(c in raw for c in "*?[") else [raw]
        if not hits:
            raise SystemExit(f"baseline: no files match {p}")
        out += [Path(h) for h in hits]
    for s in out:
        if not s.is_file():
            raise SystemExit(f"baseline: no such file: {s}")
    return out


def _pick(old: dict, args: list[str], name: str) -> list[str]:
    """Baseline song keys for names, paths or numbers ('baseline' numbers them)."""
    keys = list(old["songs"])
    out = []
    for pat in args:
        if pat.isdigit():
            n = int(pat)
            if not 1 <= n <= len(keys):
                raise SystemExit(f"no song {n} in baseline '{name}' (it has {len(keys)}) - 'baseline' lists them")
            out.append(keys[n - 1])
            continue
        hit = [k for k in keys if Path(k).name == Path(pat).name or Path(k) == Path(pat).expanduser().resolve()]
        if not hit:
            raise SystemExit(f"{pat} isn't in baseline '{name}' - 'baseline' lists its songs")
        out += hit
    return list(dict.fromkeys(out))


def _write(f: Path, songs: dict) -> None:
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"saved": time.strftime("%Y-%m-%d %H:%M"), "version": __version__,
                             "songs": songs}, indent=1) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool baseline", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", nargs="?", choices=("add", "remove", "diff", "update", "list", "save"), default="list")
    ap.add_argument("songs", nargs="*", help="audio files (globs ok), or song numbers for remove / update")
    ap.add_argument("--name", default="default")
    ap.add_argument("--layout", default=None, help=argparse.SUPPRESS)      # passed to run (tests, prop-wizard layouts)
    a = ap.parse_args(argv)
    if a.action == "save":                          # the old name: songs given = add, none = update
        a.action = "add" if a.songs else "update"
    extra = ["--layout", a.layout] if a.layout else []
    nm = f" --name {a.name}" if a.name != "default" else ""
    f = store() / f"{a.name}.json"
    if a.action == "list":
        files = sorted(store().glob("*.json")) if store().is_dir() else []
        if not files:
            print("no baselines yet - '{do}baseline add{/}' keeps the current song's plan to compare against "
                  "('baseline add SONG ...' for others)")
            return 0
        for bf in files:
            b = read_json(bf)
            print(f"{{head}}{bf.stem}{{/}}  saved {b['saved']} (seqtool {b['version']}):")
            for i, s_ in enumerate(songs_of(bf.stem), 1):        # moved songs are followed
                print(f"  {i}. {show(Path(s_), typed=True)}" + ("" if Path(s_).exists() else "  (not found)"))
        print("{note}'baseline add' adds the current song; 'run --baseline N' runs song N again{/}")
        return 0
    old = read_json(f) if f.exists() else None
    if a.action == "remove":
        if old is None or not a.songs:
            raise SystemExit("baseline remove SONG | N  (e.g. 'baseline remove 2'; 'baseline' lists the songs)")
        gone = _pick(old, a.songs, a.name)
        for k in gone:
            del old["songs"][k]
        _write(f, old["songs"])
        good(f"removed {', '.join(Path(k).name for k in gone)}; baseline '{a.name}' has {len(old['songs'])} song(s)")
        info("  (only from the baseline: the songs' pins and other settings, and the current song, are kept - "
             "'songs' lists them, 'songs forget N' forgets one)")
        return 0
    if a.action == "add":
        if a.songs:
            songs = _songs(a.songs)
        else:
            la = config.answer("last_audio")
            if not la or not Path(la).is_file():
                raise SystemExit("baseline add: no current song - 'baseline add SONG ...' (e.g. 'baseline add songs/*.mp3')")
            songs = [Path(la)]
            print(f"adding the current song {show(songs[0])}")
        have = {str(Path(k).resolve()) for k in (old or {}).get("songs", {})}
        again = [s_ for s_ in songs if str(s_.resolve()) in have]
        if again:
            print(f"{{note}}already in the baseline, its plan is replaced: {', '.join(s_.name for s_ in again)} "
                  f"(to compare with it instead: 'baseline diff'{nm}){{/}}")
        print(f"{{head}}baseline '{a.name}'{{/}}: running {len(songs)} song(s) with your current settings")
        kept = dict((old or {}).get("songs", {}))
        kept.update(run_all(songs, extra))
        _write(f, kept)
        print(f"{{ok}}added{{/}} {', '.join(s_.name for s_ in songs)}; baseline '{a.name}' has {len(kept)} song(s) - "
              f"change settings, then '{{do}}baseline diff{{/}}'{nm}")
        return 0
    if a.action == "update":
        if old is None or not old.get("songs"):
            raise SystemExit(f"no baseline '{a.name}' yet - 'baseline add' adds the current song")
        keys = _pick(old, a.songs, a.name) if a.songs else list(old["songs"])
        songs = [Path(k) for k in keys if Path(k).exists()]
        for k in keys:
            if not Path(k).exists():
                print(f"{{warn}}skipped{{/}} {show(Path(k))} (file not found)")
        print(f"{{head}}baseline '{a.name}'{{/}}: accepting the current results for {len(songs)} song(s)")
        kept = dict(old["songs"])
        kept.update(run_all(songs, extra))
        _write(f, kept)
        print(f"{{ok}}updated{{/}} {len(songs)} of {len(kept)} song(s) in baseline '{a.name}'")
        cur = config.answer("last_audio")
        if not a.songs and cur and Path(cur).is_file() and str(Path(cur).resolve()) not in kept:
            print(f"{{note}}the current song {Path(cur).name} isn't in it - 'baseline add' adds it{{/}}")
        return 0
    if old is None:
        raise SystemExit(f"baseline diff: no baseline '{a.name}' yet - 'baseline add' keeps the current song's plan (or 'baseline add SONG ...')")
    from .common.current import relocate
    for s_ in [Path(k) for k in old["songs"]]:            # songs that moved: follow them
        if not s_.exists():
            new = relocate(s_)
            if new:
                old["songs"][str(new)] = old["songs"].pop(str(s_))
    songs = [Path(s) for s in old["songs"]]
    missing = [s for s in songs if not s.exists()]
    for s in missing:
        print(f"{{warn}}skipped{{/}} {show(s)} (file not found)")
    songs = [s for s in songs if s.exists()]
    print(f"{{head}}baseline '{a.name}'{{/}} saved {old['saved']} (seqtool {old['version']}): "
          f"running {len(songs)} song(s) again")
    new = run_all(songs, extra)
    n_changed = 0
    for s in songs:
        key = str(s.resolve())
        lines = compare(old["songs"][key], new[key])
        n_changed += bool(lines)
        print(f"{{head}}{s.name}{{/}}: " + ("no change" if not lines else ""))
        for ln in lines:
            print("  " + ln)
    print(f"{n_changed} of {len(songs)} song(s) changed" + (
        f" - keep them as the new baseline with '{{do}}baseline update{{/}}'{nm}" if n_changed else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
