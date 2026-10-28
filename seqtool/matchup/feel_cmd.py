# seqtool-command: feel | main | refine | creative controls for the song: feel busy 0.7 | feel intensity high @#3 | feel warmth 0.3 | feel unison 0.8
"""seqtool feel [NAME VALUE [@#N|@TIME [--only]]] | feel NAME reset [@#N] | feel reset

Four broad creative controls for the current song (0.24.30). Each goes from 0 to 1; 0.5 is
neutral - seqtool's own choice. They turn planning settings, the same way every time:

    busy       how often effects change        0 = long, steady effects ... 1 = they change often
    intensity  which effects win               0 = calm (washes, twinkles) ... 1 = intense (chases,
                                               strobes, fire); per section too
    warmth     the colours                     0 = cool (blues) ... 1 = warm (reds, ambers)
    unison     together or apart               0 = every prop its own (no whole-yard moments) ...
                                               1 = more moments where the whole yard moves together

    feel                         the song's controls now
    feel busy 0.7                (values: 0 to 1, 0-100%, or low / neutral / high)
    feel intensity high @#3      section 3 and its repeats (--only: that one); the rest of the song
                                 keeps the song's value
    feel warmth 0.3
    feel busy reset              back to neutral (with @#3: that section's own value goes)
    feel reset                   every control back to neutral

They work on what seqtool chooses: your pins, reactions and cues stay as they are. Several at
once: 'batch "feel busy 0.3; feel intensity low"' (one re-plan). In the GUI: 2. Song > feel.
After a change the last 'run' is repeated (the analysis is reused).
"""
from __future__ import annotations

import argparse
import sys

from ..common import songs
from . import feel as F


def _bar(v: float) -> str:
    k = round(v * 10)
    return "[" + "#" * k + "." * (10 - k) + "]"


def show(feel: dict | None, profile: dict | None) -> list[str]:
    from .pins import _section_at
    L = []
    for n in F.NAMES:
        v = F.song_value(feel, n)
        L.append(f"  {n:<10} {v:4.2f} {_bar(v)}  {'{note}' if v == 0.5 else '{head}'}"
                 f"{'neutral' if v == 0.5 else ('higher' if v > 0.5 else 'lower')}{{/}} - {F.ABOUT[n]}")
    for e in (feel or {}).get("sections") or []:
        sec = _section_at(profile, float(e["at"])) if profile else None
        where = f"#{sec['index']} {sec.get('type', '')}" if sec else f"@{e['at']}"
        L.append(f"    {e['name']} {float(e['value']):.2f} in {where}"
                 + (" and its repeats" if e.get("repeats", True) else " (that one only)"))
    return L


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool feel", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("words", nargs="*", help="NAME VALUE [@#N] | NAME reset | reset")
    ap.add_argument("--only", action="store_true", help="with @#N: that section only, not its repeats")
    a = ap.parse_args(argv)
    from .reroll import _context
    path, m, profile, sha = _context()
    if not sha:
        raise SystemExit("feel: no current song - 'run --audio SONG' first")
    cur = dict(songs.get(sha).get("feel") or {})
    times = [w for w in a.words if w.startswith("@")]
    words = [w for w in a.words if not w.startswith("@")]
    if not words:
        print("{head}feel{/} of this song (0.5 = neutral, seqtool's own choice):")
        print("\n".join(show(cur, profile)))
        print("{note}e.g. 'feel busy 0.7', 'feel intensity high @#3', 'feel reset'{/}")
        return 0
    if words == ["reset"]:
        new = {}
        label = "feel: every control back to neutral"
    else:
        name = words[0].lower()
        if name not in F.NAMES:
            from ..common.suggest import suggest
            raise SystemExit(f"feel: no control '{words[0]}' - they are {', '.join(F.NAMES)}" + suggest(name, list(F.NAMES)))
        if len(words) < 2:
            raise SystemExit(f"feel {name} VALUE - e.g. 'feel {name} 0.7' (0 to 1, 0.5 = neutral)")
        new = dict(cur)
        secs = list(new.get("sections") or [])
        at = None
        if times:
            if name not in F.PER_SECTION:
                raise SystemExit(f"feel {name}: for the whole song only (per section: {', '.join(F.PER_SECTION)}) - "
                                 f"e.g. 'feel {name} 0.7'")
            from .explain import parse_time
            from .pins import _section_at
            t = parse_time(times[0], profile)
            sec = _section_at(profile, t)
            at = round((sec["start"] + sec["end"]) / 2, 3)
            secs = [e for e in secs if not (e.get("name") == name and _section_at(profile, float(e["at"])) is sec)]
        if words[1].lower() == "reset":
            if at is None:
                new.pop(name, None)
                secs = [e for e in secs if e.get("name") != name]
            label = f"feel {name}: neutral" + (" in that section" if at is not None else "")
        else:
            try:
                v = F.value(words[1])
            except ValueError:
                raise SystemExit(f"feel {name} {words[1]}: a value from 0 to 1 (or 0-100%, low / neutral / high) - "
                                 f"e.g. 'feel {name} 0.7'") from None
            if at is None:
                new[name] = v
                if v == 0.5:
                    new.pop(name)
            else:
                secs.append({"name": name, "at": at, "value": v, "repeats": not a.only})
            label = f"feel {name} {v:.2f}" + (f" {times[0]}" if at is not None else "") + f" - {F.ABOUT[name]}"
        if secs:
            new["sections"] = secs
        else:
            new.pop("sections", None)
    songs.update(sha, feel=new or None)
    from .pins import _apply_and_show
    _apply_and_show(label, m, profile)
    return 0


if __name__ == "__main__":
    sys.exit(main())
