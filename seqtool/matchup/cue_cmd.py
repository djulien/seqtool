# seqtool-command: cue | main | refine | your own trigger marks, extra hits for reacting props: cue add @1:05.2 [--for PROP]
"""seqtool cue [add @TIME... | remove @TIME... | --all | from-xsq TRACK] [--for PROP[,PROP]] [--len S]

Cues are your own trigger marks for the current song (0.24.18): a moment where a prop
that reacts to the music reacts once more, whatever its preset says - an extra flash on a
cymbal crash, a hit the beat tracker missed, a word you want to land on.

    cue                              list this song's cues
    cue add @1:05.2 @1:07            two cues for every reacting prop
    cue add @65.2 --for MegaTree,Arches
                                     only for those (a prop or a group, as the timeline names it)
    cue add @1:05.2 --len 0.5        a cue half a second long (default: one beat)
    cue remove @1:05.2               the cue(s) within 0.1 s of that time
    cue move @1:05.2 @1:05.4         move it (the magnifier: drag its flag)
    cue remove --all                 every cue of this song (--for: only that prop's)
    cue tag call @#3                 tag the cues of section 3 (or @TIME ...) as call and response
                                     marks (0.24.49): they take turns, call - response - ...;
                                     tag a phrase 'response' to say which it is; 'calls' shows the
                                     pairs seqtool finds from them; 'cue tag none @#3' clears it.
                                     A tagged cue is no extra hit for the reacting props
    cue add @43.2 @43.7 --tag call   added with a tag
    cue from-xsq Cues                the marks of a timing track 'Cues' - tap them in xLights
                                     (in the exported sequence or the .xsq the song came from)
                                     with --xsq FILE for another sequence

A cue makes a reacting prop show its first preset's effect there, cutting what was there;
outside the sections where it reacts, a cue does nothing. A prop that shouldn't react
otherwise can react to cues only: 'react PROP cue-flash --over' (a flash on each cue, on
top of its normal effects); any preset with "on": "cue" does the same. In the GUI: the
cues row under the stems - click it to add a cue there, click a cue to remove it;
while the song plays, the C key taps a cue at the playhead; in the magnifier: right-click >
add a cue here, drag a cue's flag to move it.
After a change the last 'run' is repeated (the analysis is reused).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..common import songs
from ..common.log import info, warn

NEAR = 0.1


def _ctx():
    from .reroll import _context
    path, m, profile, sha = _context()
    if not sha:
        raise SystemExit("cue: no current song - 'run --audio SONG' first")
    return m, profile, sha


def _fmt(c: dict) -> str:
    t = float(c["t"])
    return (f"  @{int(t // 60)}:{t % 60:04.1f}  ({t:.2f} s)" + (f"  {c['len']:.2f} s long" if c.get("len") else "")
            + (f"  [{c['tag']}]" if c.get("tag") else
               (f"  for {', '.join(c['for'])}" if c.get("for") else "  for every reacting prop")))


def _xsq_marks(track: str, xsq_file: str | None) -> tuple[list[float], Path]:
    from ..adapters.xlights import xsq as xsq_mod
    from ..common import config
    if xsq_file:
        f = Path(xsq_file).expanduser()
    else:
        cands = []
        lm = config.answer("last_matchup")
        if lm:
            cands = sorted(Path(lm).parent.glob("*.xsq"), key=lambda p: p.stat().st_mtime)
        f = cands[-1] if cands else None
        if f is None:
            raise SystemExit("cue from-xsq: no exported .xsq for this song yet - 'xlights-export', or "
                             "'cue from-xsq TRACK --xsq Song.xsq'")
    if not f.is_file():
        raise SystemExit(f"cue from-xsq: no file {f} - e.g. 'cue from-xsq Cues --xsq Song.xsq'")
    seq = xsq_mod.read(f)
    tracks = sorted({e.element for e in seq.effects if e.element_type == "timing"})
    tr = next((t for t in tracks if t.lower() == track.lower()), None)
    if tr is None:
        raise SystemExit(f"cue from-xsq: no timing track '{track}' in {f.name} - it has: {', '.join(tracks) or 'none'} "
                         f"(e.g. 'cue from-xsq \"{tracks[0] if tracks else 'Cues'}\"')")
    return sorted({round(e.start, 3) for e in seq.effects if e.element_type == "timing" and e.element == tr
                   and e.layer == 0}), f


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool cue", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("words", nargs="*", help="add @TIME... | remove @TIME... | from-xsq TRACK")
    ap.add_argument("--for", dest="for_", default=None, help="only these props or groups (comma list)")
    ap.add_argument("--len", type=float, default=None, help="add: how long each cue is, in seconds (default: a beat)")
    ap.add_argument("--all", action="store_true", help="remove: every cue (with --for: only theirs)")
    ap.add_argument("--xsq", default=None, help="from-xsq: the sequence holding the timing track")
    ap.add_argument("--tag", default=None, help="add / from-xsq: tag them (call, response)")
    a = ap.parse_args(argv)
    m, profile, sha = _ctx()
    cues = list(songs.get(sha).get("cues") or [])
    who = [x.strip() for x in (a.for_ or "").split(",") if x.strip()] or None
    if not a.words and not a.all:
        if not cues:
            print("no cues for this song - e.g. '{do}cue add @1:05.2{/}' (an extra hit for every reacting prop)")
            return 0
        print(f"{{head}}cues{{/}} ({len(cues)}):")
        for c in sorted(cues, key=lambda c: c["t"]):
            print(_fmt(c))
        print("{note}('cue remove @TIME' or 'cue remove --all' removes them){/}")
        return 0
    act = a.words[0] if a.words else "remove"
    rest = a.words[1:]
    from .explain import parse_time
    if act == "add":
        times = [w for w in rest if w.startswith("@")]
        if not times:
            raise SystemExit("cue add @TIME [@TIME ...] - e.g. 'cue add @1:05.2'")
        new = []
        for w in times:
            t = round(parse_time(w, profile), 3)
            c = {"t": t, **({"len": round(a.len, 3)} if a.len else {}), **({"for": who} if who else {}),
                 **({"tag": _tag(a.tag)} if a.tag else {})}
            cues = [x for x in cues if not (abs(float(x["t"]) - t) < 0.01 and x.get("for") == c.get("for"))]
            cues.append(c)
            new.append(c)
        label = f"{len(new)} cue(s) added: " + "; ".join(_fmt(c).strip() for c in new)
    elif act == "remove":
        if a.all:
            keep = [c for c in cues if who and not set(c.get("for") or []) & set(who)] if who else []
        else:
            times = [parse_time(w, profile) for w in rest if w.startswith("@")]
            if not times:
                raise SystemExit("cue remove @TIME | --all - e.g. 'cue remove @1:05.2'")
            keep = [c for c in cues if not any(abs(float(c["t"]) - t) <= NEAR for t in times)
                    or (who and not set(c.get("for") or []) & set(who))]
        if len(keep) == len(cues):
            raise SystemExit("cue remove: no cue there - 'cue' lists them")
        label = f"{len(cues) - len(keep)} cue(s) removed"
        cues = keep
    elif act == "move":                              # 0.24.21: a cue dragged in the magnifier
        times = [w for w in rest if w.startswith("@")]
        if len(times) != 2:
            raise SystemExit("cue move @FROM @TO - e.g. 'cue move @1:05.2 @1:05.4'")
        t0, t1 = (round(parse_time(w, profile), 3) for w in times)
        hit = [c for c in cues if abs(float(c["t"]) - t0) <= NEAR and (not who or set(c.get("for") or []) & set(who))]
        if not hit:
            raise SystemExit(f"cue move: no cue at {t0:.2f} s - 'cue' lists them")
        for c in hit:
            c["t"] = t1
        label = f"{len(hit)} cue(s) moved from {t0:.2f} s to {t1:.2f} s"
    elif act == "tag":                               # 0.24.49: call / response marks
        if not rest:
            raise SystemExit("cue tag call @#3 | cue tag response @45.2 @45.9 | cue tag none @#3")
        tag = _tag(rest[0])
        hit = []
        for w in [x for x in rest[1:] if x.startswith("@")]:
            if w.startswith("@#"):
                from .pins import _section_at
                sec = _section_at(profile, parse_time(w, profile))
                hit += [c for c in cues if sec["start"] <= float(c["t"]) < sec["end"]]
            else:
                t = parse_time(w, profile)
                hit += [c for c in cues if abs(float(c["t"]) - t) <= NEAR]
        if not hit:
            raise SystemExit("cue tag: no cue there - 'cue' lists them (e.g. 'cue tag call @#3')")
        for c in hit:
            if tag:
                c["tag"] = tag
            else:
                c.pop("tag", None)
        label = f"{len({id(c) for c in hit})} cue(s) " + (f"tagged '{tag}'" if tag else "untagged")
    elif act == "from-xsq":
        if not rest:
            raise SystemExit("cue from-xsq TRACK - e.g. 'cue from-xsq Cues' (a timing track you tapped in xLights)")
        marks, f = _xsq_marks(" ".join(rest), a.xsq)
        if not marks:
            raise SystemExit(f"the timing track '{' '.join(rest)}' in {f.name} has no marks")
        have = {round(float(c["t"]), 2) for c in cues if c.get("for") == who}
        add = [{"t": t, **({"len": round(a.len, 3)} if a.len else {}), **({"for": who} if who else {}),
                **({"tag": _tag(a.tag)} if a.tag else {})}
               for t in marks if round(t, 2) not in have]
        cues += add
        label = f"{len(add)} cue(s) from the timing track '{' '.join(rest)}' of {f.name}"
    else:
        raise SystemExit(f"cue: '{act}'? - 'cue add @TIME', 'cue remove @TIME', 'cue move @FROM @TO', 'cue from-xsq TRACK' or 'cue'")
    songs.update(sha, cues=sorted(cues, key=lambda c: c["t"]))
    if act != "tag" and not a.tag:
        _not_reacting(m, who)
    else:
        info("  {note}'calls' shows the call and response pairs found from them{/}")
    from .pins import _apply_and_show
    _apply_and_show(label, m, profile)
    return 0


def _tag(text: str) -> str | None:
    t = str(text).strip().lower()
    if t in ("none", "off", "-", ""):
        return None
    from .calls import ROLES
    if t not in ROLES:
        raise SystemExit(f"cue: tag '{text}'? - one of {', '.join(ROLES)} (or none), e.g. 'cue tag call @#3'")
    return t


def _not_reacting(m: dict, who: list[str] | None) -> None:
    """Cues act only on props that react: say so when the ones named don't (or nothing does)."""
    reacting = {p["target"] for p in m.get("plans", []) if p.get("react")}
    if who:
        for w in who:
            if w not in reacting:
                warn(f"{w} doesn't react to the music, so a cue does nothing to it - 'react {w} cue-flash --over' "
                     "makes it flash on its cues (on top of its normal effects)")
    elif not reacting:
        warn("no prop reacts to the music yet, so cues do nothing - e.g. 'react MegaTree cue-flash --over' "
             "(a flash on each cue) or 'react MegaTree beat'")
    else:
        info(f"  cues act on the reacting props: {', '.join(sorted(reacting)[:8])}"
             + (" ..." if len(reacting) > 8 else ""))


if __name__ == "__main__":
    sys.exit(main())
