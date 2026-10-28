# seqtool-command: sections | main | refine | list or fix the song's sections: merge, split, move, type, import
"""seqtool sections [ACTION ...]

    sections                      list the current song's sections
    sections --audio SONG ...     any of these for another song (it becomes the current song)
    sections merge 3 4            join section 3 and 4 (or just: merge 3)
    sections split 3 @41.5        split section 3 at 41.5 s (exactly; --snap beat|bar to align)
    sections move 3 @30.2         move the start of section 3 (exactly; --snap beat|bar)
    sections type 3 chorus        set a section's type: intro, verse, pre_chorus, chorus, bridge,
                                  breakdown, build, drop, solo, outro - or your own name
                                  (interlude, setup, instrumental, ...: see 'pref section_types')
    sections set @8.94 @36.7=breakdown ...   every boundary at once, exactly (=TYPE: its type) - a
                                  song's score writes them so
    sections import labels.txt    use section labels edited in Audacity
    sections from-timing "Beats" @0:30-1:10
                                  the marks of a timing track of the .xsq you opened or borrow from
                                  start sections there (between those times; no span: the whole
                                  song) - the other boundaries stay (--layer 2: its words row ...)
    sections from-xsq Song.xsq    the sections an existing xLights sequence shows (where its effects change
                                  together, which passages look alike); --apply uses them as your fixes,
                                  --layout SHOWFOLDER for its groups (default: next to the .xsq, else yours)
                                  ('gui audacity', edit, File > Export > Labels)
    sections reset                forget your edits for this song
    sections snap [bar|beat]      move your boundaries to the nearest bar line (or beat); asks first
                                  (to always align new splits/moves: 'pref music.sections.snap = bar')
    sections score [SONGS]        how well detection matches every song you fixed (--detail: per boundary)
    sections tune                 find the detection settings that match your fixes best

Edits are kept per song (seqtool-prefs/songs.json) and override detection.
After editing, 'run' again updates the plan (the audio analysis is reused).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from ..common import config, songs
from ..common.canonical import read_json, write_json
from ..common.log import good, info
from ..common.paths import arg as paths_arg, show

HINT = ("Sections wrong? Fix them for this song: 'sections merge 3 4', 'sections split 3 @41.5', "
        "'sections move 3 @30.2', 'sections type 3 chorus', or edit the labels in Audacity "
        "('gui audacity', then File > Export > Labels) and 'sections import FILE'. "
        "For fewer, longer sections in every song, raise sections.min_bars (now {min_bars}) "
        "in seqtool-prefs/music.json.")


def table(profile: dict) -> list[str]:
    ids = {x["id"]: x["index"] for x in profile["sections"]}
    rows = ["  #    start -    end  (length)  bars  type        energy  repeats"]
    bpm = profile["profile"].get("tempo_bpm") or 120
    for s in profile["sections"]:
        rep = f"#{ids.get(s['repeat_of'], '?')}" if s.get("repeat_of") else ""
        bars = (s["end"] - s["start"]) * bpm / 240
        mark = "*" if s.get("edited") else " "
        rows.append(f"  {s['index']:<2} {span(s['start'], s['end'])}  {bars:4.0f}  {s.get('type', '?'):<10}{mark}"
                    f" {s.get('energy', 0):5.2f}   {rep}")
    return rows


def clock(t: float) -> str:
    t = round(t, 1)
    return f"{int(t // 60)}:{t % 60:04.1f}"


def span(start: float, end: float) -> str:
    """'0:15.0 - 0:30.0  (15.0 s)'"""
    return f"{clock(start):>6} - {clock(end):>6}  ({end - start:5.1f} s)"


def profile_path(music_path: Path) -> Path:
    n = music_path.name
    return music_path.with_name(n[: -len(".music.json")] + ".music-profile.json")


def _context():
    from ..common import current
    s = current.song()
    if not s or not s["music"]:
        raise SystemExit("no song analysed yet - run 'seqtool run --audio SONG' (or 'analyze-music SONG') first")
    mpath = s["music"]
    music = read_json(mpath)
    ppath = profile_path(mpath)
    return mpath, music, ppath, read_json(ppath) if ppath.exists() else None


def _snap(music: dict, t: float, mode: str = "none") -> float:
    """Exact time by default; --snap beat / --snap bar moves it to the nearest beat or bar."""
    ev = music["analysis"]["events"]
    pool = {"beat": [b["time"] for b in ev.get("beats", [])],
            "bar": [d["time"] for d in ev.get("downbeats", [])]}.get(mode, [])
    if pool:
        return round(min(pool, key=lambda d: abs(d - t)), 3)
    return round(t, 3)


def _nearby(music: dict, t: float) -> str:
    ev = music["analysis"]["events"]
    out = []
    for name, pts in (("beat", [b["time"] for b in ev.get("beats", [])]),
                      ("bar", [d["time"] for d in ev.get("downbeats", [])])):
        if pts:
            near = min(pts, key=lambda d: abs(d - t))
            if abs(near - t) > 0.005:
                out.append(f"nearest {name} {near:.2f}")
    return f" ({', '.join(out)}; --snap beat|bar to align)" if out else ""


def section_rules_snap() -> str:
    from ..common.config import music_prefs
    v = music_prefs().get("sections", {}).get("snap", "none")
    return v if v in ("none", "beat", "bar") else "none"


def known_types() -> set[str]:
    from ..common.config import load
    return {t for e in load("effects")["effects"].values() for t in e.get("section_affinity", {})}


def section_rules_types() -> dict:
    from ..common.config import music_prefs
    return music_prefs().get("section_types", {})


def parse_labels(path: Path) -> tuple[list[float], dict]:
    """Audacity label file: start<TAB>end<TAB>label. Section starts become boundaries;
    a type word in the label (e.g. '#3 chorus') sets the type."""
    starts, types = [], {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) < 2 or not re.match(r"^-?\d", parts[0].strip()):
            continue
        t = float(parts[0])
        starts.append(t)
        label = parts[2] if len(parts) > 2 else ""
        words = [w for w in re.split(r"[\s=]+", label) if w and not w.startswith("#") and not re.match(r"S\d+$", w)]
        if words:
            types[f"{t:.2f}"] = words[0].lower()
    starts = sorted(set(starts))
    return [t for t in starts if t > 0], types


def _confirm(question: str) -> bool:
    from ..common.prompt import ask, interactive
    if not interactive():
        return True                      # scripted use: the command was explicit
    return ask(question, "n", show_default=False).lower() in ("y", "yes")


SECTION_PREFS = ("music.sections.method", "music.sections.min_bars", "music.sections.min_strength",
                 "music.sections.vocal_entry", "music.sections.lyrics", "music.sections.snap", "music.section_types")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool sections", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", nargs="?", choices=("merge", "split", "move", "type", "import", "reset", "score", "tune", "snap",
                                                  "from-xsq", "from-timing", "set"))
    ap.add_argument("args", nargs="*")
    ap.add_argument("--snap", choices=("none", "beat", "bar"), default=None,
                    help="split/move: align to the nearest beat or bar (default: music.sections.snap, 'none' = "
                         "the exact time you give)")
    ap.add_argument("--save", action="store_true", help="tune: save the best settings without asking")
    ap.add_argument("--layout", type=paths_arg, default=None, help="from-xsq: the xLights show folder or "
                    "xlights_rgbeffects.xml the sequence was made for (its groups)")
    ap.add_argument("--layer", type=int, default=1, help="from-timing: which row of the timing track (1 = its first)")
    ap.add_argument("--apply", action="store_true", help="from-xsq: use the sections found as your section fixes")
    ap.add_argument("--detail", "-v", action="store_true", help="score: what detection did at each of your boundaries")
    ap.add_argument("--audio", default=None, help="work on this song (it becomes the current song); default: the current song")
    ap.add_argument("--debug", action="store_true", help="write a log of every candidate boundary, its evidence and "
                    "why it was kept or dropped (<song>-seqtool/<song>.debug-sections.txt)")
    ap.add_argument("--baseline", nargs="?", metavar="N", help="song N of your baseline instead (no N: each song in turn; 'baseline' lists them)")
    a = ap.parse_args(argv)
    if a.audio:
        from ..common import current
        from ..common.paths import expand
        song = expand(a.audio, "file")
        if not song.is_file():
            raise SystemExit(f"no such song: {a.audio} - e.g. 'sections --audio ../Songs/song.mp3'")
        current.remember(audio=song)
    if a.action in ("score", "tune"):                 # all songs you fixed, not just the current one
        from . import sections_tune
        from glob import glob
        import os
        extra = [Path(h) for pat in a.args for h in (sorted(glob(os.path.expanduser(pat))) or [pat])]
        return sections_tune.score_cmd(extra, a.detail) if a.action == "score" \
            else sections_tune.tune_cmd(True if a.save else None, extra)
    snap = a.snap or section_rules_snap()
    mpath, music, ppath, profile = _context()
    sha = music["lineage"]["audio"]
    name = music["source"].get("filename")
    from .classify import classify, section_rules
    if profile is None:
        profile = classify(music, mpath.name)
        write_json(ppath, profile)
    if a.debug:
        from ..common.debuglog import DebugLog
        from .classify import boundary_trace
        audio = Path(music.get("run", {}).get("audio") or name or mpath.name)
        dbg = DebugLog.for_song(audio if audio.exists() else mpath.with_name(name or "song"), "sections")
        dbg.kv(analysis=str(mpath), your_edits="yes (they replace detected boundaries)" if songs.section_edits(sha).get("boundaries") else "none")
        for ln in boundary_trace(music, section_rules()):
            dbg.line(ln)
        dbg.save()
    if a.action is None:
        info(f"{name}: {len(profile['sections'])} sections   (* = your edit)")
        for line in table(profile):
            print(line)
        print(HINT.format(min_bars=section_rules().get("min_bars", 8)))
        snap = section_rules_snap()
        print(f"Boundaries you split, move or import snap to the nearest {snap} line" if snap != "none" else
              "Boundaries you split, move or import keep the exact time you give", end="")
        print(" ('pref music.sections.snap = bar | beat | none' to change; 'sections snap bar' aligns your "
              "earlier fixes).")
        from ..common.prefcmd import uses
        for ln in uses(*SECTION_PREFS):
            print(ln)
        return 0
    secs = profile["sections"]
    starts = [s["start"] for s in secs[1:]]
    edits = songs.section_edits(sha)
    types = dict(edits.get("types", {}))

    def sec(n):
        n = int(str(n).lstrip("#"))
        if not 1 <= n <= len(secs):
            raise SystemExit(f"no section #{n} (1-{len(secs)}; 'sections' lists them)")
        return n

    def at(text):
        from ..matchup.explain import parse_time
        return parse_time(text, profile)
    act, args = a.action, a.args
    if act in ("reset", "import") and edits and not _confirm(
            f"this replaces your {len(edits.get('boundaries', []))} edited boundaries and "
            f"{len(edits.get('types', {}))} section types for {name}. Continue? [y/N]"):
        info("nothing changed")
        return 0
    if act == "snap":                                # tidy your boundaries: to the nearest bar (or beat)
        to = (args[0] if args else "bar").lower()
        if to not in ("bar", "beat"):
            raise SystemExit("sections snap [bar|beat]  (e.g. 'sections snap bar')")
        if not edits.get("boundaries"):
            print("no boundaries of yours to snap in this song - detection's are already on the beat grid")
            return 0
        moves = [(t, _snap(music, t, to)) for t in sorted(edits["boundaries"])]
        moved = [(t, u) for t, u in moves if abs(t - u) > 0.005]
        if not moved:
            print(f"all your boundaries are on a {to} line already")
            return 0
        for t, u in moved:
            print(f"  {t:8.2f} -> {u:8.2f}  ({u - t:+.2f} s)")
        if not _confirm(f"move these {len(moved)} boundaries of yours to the nearest {to}? [y/N]"):
            info("nothing changed")
            return 0
        starts = sorted({u for _, u in moves})
        for t, u in moved:
            if f"{t:.2f}" in types:
                types[f"{u:.2f}"] = types.pop(f"{t:.2f}")
        msg = f"moved {len(moved)} boundaries to the nearest {to}"
    elif act == "reset":
        songs.update(sha, name, sections=None)
        msg = "your section edits for this song were removed"
    elif act == "merge":
        n = sec(args[0])
        m = sec(args[1]) if len(args) > 1 else n + 1
        lo, hi = sorted((n, m))
        if hi != lo + 1 or hi > len(secs):
            raise SystemExit("merge needs two neighbouring sections, e.g. 'merge 3 4'")
        starts.remove(secs[hi - 1]["start"])
        msg = f"merged #{lo} and #{hi}"
    elif act == "split":
        n = sec(args[0])
        t = _snap(music, at(args[1]), snap)
        s = secs[n - 1]
        if not s["start"] < t < s["end"]:
            raise SystemExit(f"@{t:.1f} is not inside section #{n} ({s['start']:.1f}-{s['end']:.1f})")
        starts.append(t)
        msg = f"split #{n} at {t:.2f} s" + (f" (the nearest {snap})" if snap != "none" else _nearby(music, t))
    elif act == "move":
        n = sec(args[0])
        if n == 1:
            raise SystemExit("section #1 always starts at 0")
        t = _snap(music, at(args[1]), snap)
        lo, hi = secs[n - 2]["start"], secs[n - 1]["end"]
        if not lo < t < hi:
            raise SystemExit(f"@{t:.1f} must be between {lo:.1f} and {hi:.1f}")
        old = secs[n - 1]["start"]
        starts[starts.index(old)] = t
        if f"{old:.2f}" in types:
            types[f"{t:.2f}"] = types.pop(f"{old:.2f}")
        msg = f"moved the start of #{n} to {t:.2f} s" + (f" (the nearest {snap})" if snap != "none" else _nearby(music, t))
    elif act == "type":
        n, typ = sec(args[0]), args[1].lower()
        types[f"{secs[n - 1]['start']:.2f}"] = typ
        known, aliases = known_types(), section_rules_types()
        if typ in known:
            msg = f"#{n} is now '{typ}'"
        elif typ in aliases:
            msg = f"#{n} is now '{typ}' (chosen like a '{aliases[typ]}')"
        else:
            msg = (f"#{n} is now '{typ}' - a new type name: until you say what it is like, effects treat it "
                   f"neutrally. e.g.  pref music/section_types/{typ} = bridge   (known: {', '.join(sorted(known))})")
    elif act == "from-xsq":
        if not args:
            raise SystemExit("sections from-xsq Song.xsq [--layout SHOWFOLDER] [--apply]")
        from ..common.paths import expand
        from .xsq_sections import analyse
        f = expand(args[0], "file")
        if not f.is_file():
            raise SystemExit(f"not found: {f} - e.g. 'sections from-xsq ~/xLights/show/MySong.xsq'")
        lay = a.layout
        if lay is not None and Path(lay).is_dir():
            lay = Path(lay) / "xlights_rgbeffects.xml"
        if lay is None:
            for d in (f.parent, f.parent.parent):
                if (d / "xlights_rgbeffects.xml").exists():
                    lay = d / "xlights_rgbeffects.xml"
                    break
        if lay is None:
            from ..layout import store
            src = store.source_info()
            lay = Path(src["path"]) if src and str(src.get("path", "")).endswith(".xml") and Path(src["path"]).exists() else None
        res = analyse(f, lay, music)
        info(f"{f.name}: {res['effects']} effects on {res['props']} props" + (f" (groups from {show(lay)})" if lay
             else " {warn}(no layout: group effects count for the group only - --layout SHOWFOLDER){/}"))
        print(f"{{head}}{'#':>3} {'start':>7} {'bars':>5}  {'look':<5}{'type':<10}{'like':<10} props/bar{{/}}")
        for x in res["sections"]:
            like = f"#{x['like']} ({x['similarity']:.0%})" if x["like"] else ""
            print(f"{x['index']:>3} {clock(x['start']):>7} {x['bars']:>5}  {x['letter']:<5}{x['type']:<10}{like:<10} {x['density']}")
        cur = [round(s_["start"], 1) for s_ in secs]
        found = [x["start"] for x in res["sections"]]
        near = sum(1 for t in found[1:] if any(abs(t - c) <= 2.0 for c in cur[1:]))
        info(f"  {near} of its {len(found) - 1} boundaries are within 2 s of the current sections' "
             f"({len(cur) - 1}); the letters show which passages look alike")
        if not a.apply:
            print("{note}to use them as your section fixes:{/} {do}sections from-xsq " + args[0] + " --apply{/}  "
                  "{note}(then 'sections' to adjust; 'sections reset' goes back to detection){/}")
            return 0
        if edits and not _confirm(f"this replaces your {len(edits.get('boundaries', []))} edited boundaries for "
                                  f"{name}. Continue? [y/N]"):
            info("nothing changed")
            return 0
        starts = [x["start"] for x in res["sections"][1:]]
        types = {f"{x['start']:.2f}": x["type"] for x in res["sections"]}
        msg = f"{len(res['sections'])} sections from {f.name}, used as your fixes"
    elif act == "from-timing":                       # 0.21.8: part of an .xsq's timing track as boundaries
        rec = songs.get(sha).get("borrowed") or {}
        f = Path(rec.get("xsq", ""))
        if not rec.get("xsq") or not f.is_file():
            raise SystemExit("no .xsq for this song - 'open-xsq Song.xsq' (or 'xsq-borrow Song.xsq') first")
        names = [x for x in args if not x.startswith("@")]
        spans = [x for x in args if x.startswith("@")]
        from ..adapters.xlights import xsq as xsq_mod
        seq = xsq_mod.read(f)
        tracks = sorted({e.element for e in seq.effects if e.element_type == "timing"})
        if not names:
            raise SystemExit(f"which timing track? {f.name} has: {', '.join(tracks) or 'none'} - e.g. "
                             f"'sections from-timing \"{tracks[0] if tracks else 'Beats'}\" @0:30-1:10'")
        tr = next((t for t in tracks if t.lower() == " ".join(names).lower()), None)
        if tr is None:
            raise SystemExit(f"no timing track '{' '.join(names)}' in {f.name} - it has: {', '.join(tracks) or 'none'}")
        marks = sorted(e.start for e in seq.effects if e.element_type == "timing" and e.element == tr
                       and e.layer == a.layer - 1)
        lo, hi = 0.0, music["audio"]["duration"]
        if spans:
            m_ = re.fullmatch(r"@([\d:.#]+)-([\d:.]+)", spans[0])
            if m_:
                lo, hi = at(m_.group(1)), at(m_.group(2))
            else:
                n = sec(spans[0].lstrip("@#")) if spans[0].startswith("@#") else None
                s_ = secs[n - 1] if n else next(x for x in secs if x["start"] <= at(spans[0]) < x["end"])
                lo, hi = s_["start"], s_["end"]
        new = [_snap(music, t, snap) for t in marks if lo < t < hi and 0.5 < t < music["audio"]["duration"] - 0.5]
        if not new:
            raise SystemExit(f"no marks of '{tr}' between {clock(lo)} and {clock(hi)}")
        starts = sorted({t for t in starts if not lo < t < hi} | set(new))
        msg = (f"{len(new)} section boundaries from the timing track '{tr}' of {f.name}, "
               f"{clock(lo)}-{clock(hi)}" + (f" (aligned to the nearest {snap})" if snap != "none" else ""))
    elif act == "set":                                # 0.24.50: every boundary at once, as given (a score)
        starts, types = [], {}
        for w in args:
            t_, _, typ = w.lstrip("@").partition("=")
            try:
                t = round(float(t_), 3)
            except ValueError:
                raise SystemExit(f"sections set: '{w}' - times in seconds, e.g. 'sections set @8.94 @36.7=breakdown'") from None
            starts.append(t)
            if typ:
                types[f"{t:.2f}"] = typ.lower()
        if not starts:
            raise SystemExit("sections set @T1 @T2=TYPE ... - e.g. 'sections set @8.94 @36.7=breakdown'")
        msg = f"{len(starts) + 1} sections, as given"
    elif act == "import":
        from ..common.paths import expand
        f = expand(args[0], "file")
        starts, types = parse_labels(f)
        if snap != "none":                           # label times are approximate too
            moved = {t: _snap(music, t, snap) for t in starts}
            types = {f"{moved.get(float(k), float(k)):.2f}": v for k, v in types.items()}
            starts = sorted(set(moved.values()))
        msg = f"imported {len(starts) + 1} sections from {show(f)}" + (f" (aligned to the nearest {snap})" if snap != "none" else "")
    if act != "reset":
        songs.update(sha, name, sections={"boundaries": sorted(starts), "types": types},
                     music=str(mpath.resolve()))           # so 'sections score' can find the analysis
    profile = classify(music, mpath.name)
    write_json(ppath, profile)
    good(msg)
    for line in table(profile):
        print(line)
    print("update the plan: run again ('run' reuses the analysis), or 'reroll' to also try new choices")
    from ..common.prefcmd import uses
    for ln in uses(*SECTION_PREFS):
        print(ln)
    return 0


if __name__ == "__main__":
    sys.exit(main())
