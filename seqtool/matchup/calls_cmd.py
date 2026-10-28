# seqtool-command: calls | main | refine | call and response pairs found from the cues you tagged 'call' (cue tag call @#3)
"""seqtool calls [@#N] [--json]

The call and response pairs of the current song (0.24.49): the ones you marked with cues
tagged 'call' / 'response' ('cue tag call @#3'), and the ones seqtool finds from them in the
rest of the section and its repeats (calls.py has how). A choreography plays on them with
"per": "call" | "response" | "call_phrase" | "response_phrase" | "pair".

    calls                      every pair
    calls @#5                  the pairs in section 5
    pref music.calls.gap_beats = 2       a pause this long (beats) ends a phrase
    pref music.calls.response = onsets   find each response's hits in what is heard (default
                                         'copy': the call's timing, one offset later)
    pref music.calls.onset = 0.5         how strong a note must be to count, in found calls
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool calls", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("where", nargs="?", help="@#N - one section")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    from ..common import songs
    from ..common.canonical import read_json
    from .calls import derive
    from .reroll import _context
    path, m, profile, sha = _context()
    music = read_json(Path(path).parent / m["source"]["music"]["filename"])
    cues = list(songs.get(sha).get("cues") or [])
    ev = derive(music, profile, cues)
    if a.where:
        from .explain import parse_time
        from .pins import _section_at
        sec = _section_at(profile, parse_time(a.where, profile))
        ev = [e for e in ev if sec["start"] <= e["time"] < sec["end"]]
    if a.json:
        print(json.dumps(ev, indent=1))
        return 0
    if not ev:
        n = sum(1 for c in cues if c.get("tag"))
        print("no call and response pairs" + (f" - {n} tagged cue(s), but not a call followed by a response"
                                               if n else " - tag the cues of the first pair or two: 'cue tag call @#3'"))
        return 0
    pairs = sorted({e["pair"] for e in ev})
    print(f"{{head}}call and response{{/}}: {len(pairs)} pair(s), "
          f"{sum(1 for p in pairs if not any(e['derived'] for e in ev if e['pair'] == p))} marked by you")
    secs = profile["sections"]
    for p in pairs:
        es = [e for e in ev if e["pair"] == p]
        c = [e["time"] for e in es if e["kind"] == "call"]
        r = [e["time"] for e in es if e["kind"] == "response"]
        pr = next(e for e in es if e["kind"] == "pair")
        s = next((x for x in secs if x["start"] <= pr["time"] < x["end"]), secs[-1])
        print(f"  {p:>2}. #{s['index']} {pr['time']:7.2f}-{pr['end']:6.2f} s  call {len(c)} note(s) at "
              + " ".join(f"{t:.2f}" for t in c[:6]) + (" ..." if len(c) > 6 else "")
              + f"  | response {len(r)} at " + " ".join(f"{t:.2f}" for t in r[:6]) + (" ..." if len(r) > 6 else "")
              + ("  {note}(found){/}" if es[0]["derived"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
