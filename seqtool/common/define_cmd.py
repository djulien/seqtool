# seqtool-command: define | main | refine | named terms at levels - show, kind of prop, song, section: define set "left arm wave" --for spinners TEXT | define get NAME | define dump
"""seqtool define [list] | define set NAME [WHERE] [--for X] [--data JSON] TEXT ... |
       define get NAME [--for PROP] [@TIME] [--json] | define dump [--for PROP] [@TIME] [--json] |
       define remove NAME [WHERE] [--for X]

Named terms you use in your directions (0.24.46) - 'left arm wave', 'the slow phrase', 'the call
pattern' - kept at levels and read back in one query, so the seqtool-direction skill (and you)
don't have to repeat them in every direction. Each is a few lines of text (what it means, for a
reader) and, if it has one, a machine form (--data JSON: what a choreography effect plays).

WHERE (the level; the most specific one that applies wins):
    --show          the whole show (every song)            seqtool-prefs/definitions.json
    --song          this song (the default)
    @#3 | @1:05     a section of this song and its repeats (--only: that one) - kept by its time,
                    so editing the sections doesn't lose it
    --for X         with any of them: a kind of prop (spinner, matrix, line, tree ...), a group or
                    one prop

    define set "left arm wave" --show --for spinners one spoke dips from 10 o'clock to 7 and back
    define set "left arm wave" --show --for Matrix one loop of pumpkin-left-ani.gif
    define set "slow phrase" the last "Sing it all night long." of each chorus: 5 slow words
    define set "flap time" @#3 0.3 s per flap here --data '{"length": 0.3}'
    define get "left arm wave" --for Spinner1 @#3      everything that applies, merged
    define dump @#3 --json                               every term that applies there (for a skill)
    define                                                the names
    define remove "flap time" @#3
"""
from __future__ import annotations

import argparse
import json
import sys

from . import definitions as DF


def _context():
    try:
        from ..matchup.reroll import _context as ctx
        _, _, profile, sha = ctx()
        return profile, sha
    except SystemExit:
        return None, None


def _where(a, profile) -> tuple[str, float | None, bool]:
    times = [w for w in a.words if str(w).startswith("@")]
    if a.show:
        return "show", None, True
    if times:
        if not profile:
            raise SystemExit("define: a section needs the current song's analysis - 'run' first")
        from ..matchup.explain import parse_time
        from ..matchup.pins import _section_at
        t = parse_time(times[0], profile)
        s = _section_at(profile, t)
        at = (s["start"] + s["end"]) / 2 if times[0].startswith("@#") else t
        return "section", round(at, 3), not a.only
    return "song", None, True


def show_one(d: dict) -> list[str]:
    L = [f"{{head}}{d['name']}{{/}}" + (f"  {{note}}(for {d['for']}){{/}}" if d.get("for") else "")]
    for lv in d["levels"]:
        L.append(f"  {{note}}{lv['where']}:{{/}} {lv['text']}" + (f"  {{note}}data {json.dumps(lv['data'])}{{/}}"
                                                                  if lv.get("data") else ""))
    if d.get("data"):
        L.append(f"  {{note}}together:{{/}} {json.dumps(d['data'])}")
    return L


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool define", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", nargs="?", default="list", choices=("list", "set", "get", "dump", "remove"))
    ap.add_argument("words", nargs="*", help="NAME [@#N|@TIME] TEXT ...")
    ap.add_argument("--for", dest="for_", default=None, metavar="X", help="a kind of prop, a group or a prop")
    ap.add_argument("--show", action="store_true", help="for the whole show (every song)")
    ap.add_argument("--song", action="store_true", help="for this song (the default)")
    ap.add_argument("--only", action="store_true", help="with @#N: that section only, not its repeats")
    ap.add_argument("--data", default=None, help="the machine form, JSON (e.g. '{\"length\": 0.3}')")
    ap.add_argument("--json", action="store_true", help="get / dump: as JSON")
    a = ap.parse_args(argv)
    profile, sha = _context()
    if a.for_ and DF.Props().kind_of(a.for_) is None:
        from .suggest import suggest
        P = DF.Props()
        raise SystemExit(f"define: '{a.for_}' is no prop, group or kind of prop ({', '.join(sorted(set(DF.CLASS_WORDS.values())))})"
                         + suggest(a.for_, list(P.by)))
    if a.action == "list":
        ns = DF.names(sha)
        if not ns:
            print("no definitions yet - e.g. 'define set \"left arm wave\" --show --for spinners one spoke dips from "
                  "10 to 7 o'clock and back'")
            return 0
        print(f"{{head}}definitions{{/}} ({len(ns)}): " + ", ".join(f"'{n}'" for n in ns))
        print("{note}('define get NAME' shows one, 'define dump' all that apply somewhere){/}")
        return 0
    words = [w for w in a.words if not str(w).startswith("@")]
    times = [w for w in a.words if str(w).startswith("@")]
    at = None
    if times and a.action in ("get", "dump"):
        if not profile:
            raise SystemExit("define: a time needs the current song's analysis - 'run' first")
        from ..matchup.explain import parse_time
        at = parse_time(times[0], profile)
    if a.action == "set":
        if len(words) < 2 and not a.data:
            raise SystemExit('define set NAME TEXT ... - e.g. define set "slow phrase" the last line of each chorus')
        level, at_, rep = _where(a, profile)
        data = None
        if a.data:
            try:
                data = json.loads(a.data)
            except ValueError as e:
                raise SystemExit(f"define --data: not JSON ({e}) - e.g. --data '{{\"length\": 0.3}}'") from None
        e = {"name": words[0], "level": level, "text": " ".join(words[1:])}
        if a.for_:
            e["for"] = a.for_
        if data is not None:
            e["data"] = data
        if level == "section":
            e["at"], e["repeats"] = at_, rep
        how = DF.put(e, sha)
        from .log import good
        where = DF.applying(sha, profile, None, None, words[0])
        w = next((x["where"] for x in where if DF._key(x) == DF._key(e)), level)
        good(f"'{words[0]}' {how} ({w}) - 'define get \"{words[0]}\"' shows everything that applies")
        return 0
    if a.action == "remove":
        if not words:
            raise SystemExit('define remove NAME [@#N | --song | --show] [--for X]')
        level, at_, _ = _where(a, profile) if (a.show or times or a.song) else (None, None, True)
        n = DF.remove(words[0], level, a.for_, at_, sha, profile)
        if not n:
            raise SystemExit(f"define remove: no '{words[0]}' there - 'define get \"{words[0]}\"' shows where it is")
        from .log import good
        good(f"removed {n} definition(s) of '{words[0]}'")
        return 0
    if a.action == "get":
        if not words:
            raise SystemExit('define get NAME [--for PROP] [@TIME]')
        d = DF.get(words[0], sha, profile, a.for_, at)
        if d is None:
            from .suggest import suggest
            raise SystemExit(f"define: no '{words[0]}'" + (f" for {a.for_}" if a.for_ else "")
                             + (" there" if at is not None else "") + suggest(words[0], DF.names(sha)))
        print(json.dumps(d, indent=2, ensure_ascii=False) if a.json else "\n".join(show_one(d)))
        return 0
    out = [d for n in DF.names(sha) for d in [DF.get(n, sha, profile, a.for_, at)] if d]
    if a.json:
        print(json.dumps({"for": a.for_, "at": at, "definitions": out}, indent=2, ensure_ascii=False))
    elif not out:
        print("no definitions apply" + (f" to {a.for_}" if a.for_ else "") + (" there" if at is not None else ""))
    else:
        for d in out:
            print("\n".join(show_one(d)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
