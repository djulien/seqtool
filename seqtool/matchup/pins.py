# seqtool-command: pin | main | refine | keep or force an effect: pin MegaTree @#3 [EFFECT]; pin lists them
# seqtool-command: unpin | main_unpin | refine | let seqtool choose again: unpin MegaTree @#3 | unpin MegaTree | unpin --all
"""seqtool pin TARGET [@#N | @TIME] [EFFECT] [--only]  |  pin  |  unpin ...

Keeps a choice you like, or forces one, whatever the scores say. Pins survive
rerolls, new seeds, re-analysis and section edits (a pin remembers a moment of
the song, not a section number).

    pin MegaTree @#3              keep MegaTree's current effect in section 3 -
                                  and in the sections that repeat it
    pin MegaTree @#3 spirals      force spirals there instead
    pin MegaTree @1:05 dark       black out MegaTree in the section playing at 1:05
    pin MegaTree @#3 --only       section 3 only, not its repeats
    pin MegaTree twinkle          the whole song
    pin Matrix @#1 meteors direction=explode speed=medium-fast
    pin Matrix meteors until=@vocals       only part of a section: onset= / offset= (or from= / until=)
                                  as 2s, 1b (bars), 3beats, 25% of the section, or @TIME; the rest of
                                  the section: nothing from this pin (what is underneath shows). With
                                  @TIME the section can be left out (the time says it; a word sung
                                  more than once: which one is asked, or @#N takes the one there)
    pin Spinners @#3 meteors render=per-model    a group's effect on each of its props (render=default:
                                  the group's own layout in xLights)
                                  with settings of yours ('effects meteors' lists them; a level
                                  0-1, 0-100% or low / medium / medium-fast / fast / dense ...)
    pin MegaTree @#3 bars speed=0.2..0.9  a setting that glides over the pin (a..b, or a..b..c: evenly
                                  spaced) - an xLights value curve once the kit has learned them
    pin Spinner1 @#3 pinwheel rotation=10oclock..7oclock..10oclock
                                  turned (Layer Settings > Roto-Zoom > Z rotation): 90deg, 3oclock (12 = 0) or a share
                                  of a turn; a..b glides
    pin MegaTree --all            keep MegaTree's current effect in every section (the GUI's row pin)
    pin "MegaTree (enhance)" @#3 transparent
                                  a later pass's layer: name it as the timeline does
    pin                           list this song's pins
    unpin MegaTree @#3            remove pins on MegaTree in section 3
    unpin MegaTree                remove all of MegaTree's pins
    unpin --all                   remove every pin for this song

After a change the last 'run' is repeated (the analysis is reused) and what
changed is shown. EFFECT is any effect type ('effects' lists them), including
'dark' (explicitly black) and 'transparent' (nothing from this layer, so what is
underneath shows). A pinned effect still gets its own parameters and colours.
Pins are kept per song (songs.json, keyed by the audio).
"""
from __future__ import annotations

import argparse
import re
import sys

from ..common import config, songs
from ..common.log import good, info, warn
from ..common.vocab import canon

PASS_SUFFIX = {" (enhance)": "enhance", " (main)": "main", " (top)": "top", " (pin)": "pin", " (detail)": "detail",
               " (placed)": "place", " (place)": "place"}


TRIM_ALIASES = {"from": "onset", "until": "offset", "delay": "onset", "start": "onset", "end": "offset"}
_TRIM = re.compile(r"^(\d+(?:\.\d+)?)\s*(s|sec|secs|seconds?|b|bars?|beats?|%)?$")


def trim_text(text: str, profile: dict | None = None) -> str:
    """onset / offset of a pinned effect (0.24.37): '2s', '1.5b' (bars), '3beats', '25%' (of the
    section) - or '@TIME' (any time form: '@0:05', '@vocals', '@star'): it starts / ends there."""
    t = str(text).strip().lower()
    if t.startswith("@"):
        from .explain import parse_time
        parse_time(t, profile)                         # a time that works now (it is worked out again each plan)
        return t
    m = _TRIM.match(t)
    if not m:
        raise ValueError("a time in s, bars (b), beats or % of the section, or @TIME")
    unit = (m.group(2) or "s")
    unit = "%" if unit == "%" else "beat" if unit.startswith("beat") else "b" if unit.startswith("b") else "s"
    return f"{float(m.group(1)):g}{'' if unit == 's' else unit}" + ("s" if unit == "s" else "")


def trim_seconds(text: str, sec: dict, profile: dict | None, end: bool) -> float:
    """onset / offset as a time in the song for this section (start + onset, end - offset)."""
    t = str(text)
    if t.startswith("@"):
        from .explain import parse_time
        return parse_time(t, profile)
    from .parts import duration
    length = sec["end"] - sec["start"]
    br = sec.get("beat_range") or []
    beat = length / (br[1] - br[0]) if len(br) == 2 and br[1] > br[0] else 0.5
    d = duration(t, length, beat)
    return sec["end"] - d if end else sec["start"] + d


def _trim_times(given: list[str], times: list[str], profile: dict):
    """A pin's from= / until= (onset= / offset=) given as @TIME (0.24.37): (its section, the
    settings with a sung word's time made exact) - or None. Without @#N the time says the
    section; a word sung more than once is asked about (which time?), or with @#N the one sung in
    that section is taken."""
    from .explain import WORD_TIME, parse_time, word_times
    out, sec = [], None
    want = _section_at(profile, parse_time(times[0], profile)) if times else None
    for g in given:
        k, v = g.split("=", 1)
        kk = TRIM_ALIASES.get(k.lower(), k.lower())
        if kk not in ("onset", "offset") or not v.startswith("@"):
            out.append(g)
            continue
        m = WORD_TIME.match(v)
        if m and not m.group(2) and m.group(1).lower() != "vocals" and not re.match(r"@?\d", v):
            word, hits = word_times(m.group(1))
            if want is not None:
                hits_in = [i for i, t in enumerate(hits, 1) if want["start"] <= t < want["end"]]
            else:
                hits_in = list(range(1, len(hits) + 1))
            if not hits_in:
                raise SystemExit(f"pin: '{word}' isn't sung in #{want['index']} - 'lyrics' shows where it is")
            n = hits_in[0]
            if len(hits_in) > 1:
                n = _ask_which(word, [(i, hits[i - 1]) for i in hits_in], profile, k)
            v = f"@{word}#{n}{m.group(3) or ''}"
        t = parse_time(v, profile)
        s_ = _section_at(profile, t - (1e-3 if kk == "offset" else 0.0))   # 'until' the start of a section: the one before
        if want is not None and s_ is not want:
            raise SystemExit(f"pin: {k}={v} is at {int(t // 60)}:{t % 60:04.1f}, in #{s_['index']} - not in "
                             f"#{want['index']}; leave out the section (the time says it) or give another time")
        sec = sec or s_
        out.append(f"{k}={v}")
    return None if sec is None else (want or sec, out)


def _ask_which(word: str, hits: list[tuple[int, float]], profile: dict, key: str) -> int:
    from ..common.prompt import ask, interactive
    rows = [f"  {n}) {int(t // 60)}:{t % 60:04.1f}  #{_section_at(profile, t)['index']} "
            f"{_section_at(profile, t).get('type', '')}" for n, t in hits]
    if not interactive():
        raise SystemExit(f"pin: '{word}' is sung {len(hits)} times - say which: {key}=@{word}#N\n" + "\n".join(rows))
    print(f"'{word}' is sung {len(hits)} times:\n" + "\n".join(rows))
    ans = ask(f"which one? [{hits[0][0]}]", str(hits[0][0]), show_default=False).strip()
    if ans.isdigit() and int(ans) in {n for n, _ in hits}:
        return int(ans)
    raise SystemExit(f"pin: not one of them - e.g. {key}=@{word}#{hits[0][0]}")


def _section_at(profile: dict, t: float) -> dict:
    secs = profile["sections"]
    return next((s for s in secs if s["start"] <= t < s["end"]), secs[-1])


def apply_pins(mprefs: dict, pins: list, windows, profile: dict, notes: list) -> dict:
    """Return models prefs with targets.<id>._pins = {pass: {window index: effect}}."""
    targets = {k: dict(v) for k, v in mprefs.get("targets", {}).items()}
    for pin in pins:
        if pin.get("at") is None:
            idx = [w.index for w in windows]
        else:
            sec = _section_at(profile, float(pin["at"]))
            root = next((w.section_repeat_key for w in windows if w.section_id == sec["id"]), sec["id"])
            idx = [w.index for w in windows
                   if w.section_id == sec["id"] or (pin.get("repeats", True) and w.section_repeat_key == root)]
        if not idx:
            notes.append(f"pin {pin['target']} @{pin.get('at')}: no part of the song matches")
            continue
        t = targets.setdefault(pin["target"], {})
        per = {k: dict(v) for k, v in t.get("_pins", {}).items()}
        slot = per.setdefault(pin.get("pass", "main"), {})
        pr = dict(pin.get("params") or {})
        on, off = pr.pop("onset", None), pr.pop("offset", None)
        if on or off:                                  # 0.24.37: later start / earlier end in each section
            trims = {k: list(v) for k, v in t.get("_pin_trim", {}).items()}
            tl = trims.setdefault(pin.get("pass", "main"), [])
            secs = {w.section_id for w in windows if w.index in idx}
            for sc in profile["sections"]:
                if sc["id"] not in secs:
                    continue
                try:
                    a = trim_seconds(on, sc, profile, False) if on else sc["start"]
                    b = trim_seconds(off, sc, profile, True) if off else sc["end"]
                except SystemExit as e:
                    notes.append(f"pin {pin['target']}: {e}")
                    continue
                tl.append([sc["start"], sc["end"], round(max(sc["start"], a), 3), round(min(sc["end"], b), 3),
                           f"{'onset=' + on if on else ''}{' ' if on and off else ''}{'offset=' + off if off else ''}"])
            t["_pin_trim"] = trims
        pp = {k: dict(v) for k, v in t.get("_pin_params", {}).items()}
        pslot = pp.setdefault(pin.get("pass", "main"), {})
        for i in idx:
            slot[i] = canon(pin["effect"])         # later pins win where they overlap
            if pr:                                 # 0.24.36: settings you gave the pinned effect
                pslot[i] = dict(pr)
            else:
                pslot.pop(i, None)
        t["_pins"] = per
        t["_pin_params"] = pp
    return {**mprefs, "targets": targets}


def _root(profile: dict, s: dict) -> str:
    ids = {x["id"]: x for x in profile["sections"]}
    while s.get("repeat_of") in ids:
        s = ids[s["repeat_of"]]
    return s["id"]


def covers(pin: dict, sec: dict, profile: dict) -> bool:
    """Does the pin apply in section sec - its own section, a repeat of it (unless --only), or
    the whole song (0.21.1: unpinning in a repeat said 'no pin matches')."""
    if pin.get("at") is None:
        return True
    own = _section_at(profile, float(pin["at"]))
    return own is sec or (pin.get("repeats", True) and _root(profile, own) == _root(profile, sec))


def describe(pin: dict, profile: dict) -> str:
    ps = pin.get("pass", "main")
    who = pin["target"] + (f" ({'placed' if ps == 'place' else ps})" if ps != "main" else "")
    if pin.get("at") is None:
        where = "whole song"
    else:
        sec = _section_at(profile, float(pin["at"]))
        ids = {s["id"]: s for s in profile["sections"]}

        def root(s):
            while s.get("repeat_of") in ids:
                s = ids[s["repeat_of"]]
            return s["id"]
        reps = [s for s in profile["sections"] if s is not sec and pin.get("repeats", True) and root(s) == root(sec)]
        where = f"#{sec['index']} {sec.get('type', '?')}" + (
            f" (+ repeats {', '.join('#' + str(s['index']) for s in reps)})" if reps else "")
        where += f"  [@{float(pin['at']):.1f}]"
    def fmt(v):
        if isinstance(v, dict) and "ramp" in v:
            return "..".join(f"{x:g}" for x in v["ramp"])
        if isinstance(v, dict) and "curve" in v:
            return "..".join(f"{y:g}" for _, y in v["curve"])
        return ",".join(f"{x:g}" for x in v) if isinstance(v, list) else v
    sets = " " + " ".join(f"{k}={fmt(v)}" for k, v in pin["params"].items()) if pin.get("params") else ""
    return f"  {who:<26} {where:<44} {{b}}{pin['effect']}{{/}}{sets}" + (f"  {{note}}({pin['how']}){{/}}" if pin.get("how") else "")


def _resolve(m: dict, text: str) -> tuple[str, str]:
    """(target, pass). Without a '(pass)' suffix the pass is the one the target is
    sequenced in: 'top' for a top group, 'pin' (a row of its own) for a prop that a
    group sequences, else 'main'."""
    from .explain import resolve_target
    for suf, ps in PASS_SUFFIX.items():
        if text.endswith(suf):
            return resolve_target(m, text[: -len(suf)])[0], ps
    low = text.lower()
    for sk in m.get("diagnostics", {}).get("skipped_targets", []):
        if sk["id"].lower() != low or any(p["target"] == sk["id"] and p.get("pass") != "base" for p in m["plans"]):
            continue
        g = re.match(r"driven via group (.+)", sk["reason"])
        if g:
            info(f"{sk['id']} is sequenced as part of group {g.group(1)}: this pin gives {sk['id']} a row of its "
                 f"own there, above the group's (for the whole group: 'pin {g.group(1)} ...')")
            return sk["id"], "pin"
        if sk["reason"].startswith("top pass") or "role 'top'" in sk["reason"]:
            return sk["id"], "top"
    target, note = resolve_target(m, text)
    passes = {p.get("pass", "main") for p in m["plans"] if p["target"] == target and not p.get("react")
              and p.get("pass") != "base"}                 # moments aren't pinned (0.20)
    if note:
        g = re.match(r"(.+) is sequenced as part of group", note)
        if g:
            return _resolve(m, g.group(1))
        info(note)
    if "main" in passes or not passes:
        return target, "main"
    return target, next((ps for ps in ("pin", "top", "detail", "enhance", "place") if ps in passes), "main")


def _current_effect(m: dict, target: str, pass_: str, t0: float, t1: float) -> str | None:
    """The effect that plays longest for target/pass between t0 and t1."""
    best: dict[str, float] = {}
    for p in m["plans"]:
        if p["target"] != target or p.get("pass", "main") != pass_ or p.get("react"):
            continue
        for g in p["segments"]:
            ov = min(g["end"], t1) - max(g["start"], t0)
            if ov > 0:
                best[g["selected"]["effect"]] = best.get(g["selected"]["effect"], 0) + ov
    return max(best, key=best.get) if best else None


def _apply_and_show(label: str, old_m: dict, profile: dict) -> None:
    from .reroll import diff, plan_columns, rerun
    from ..common.canonical import read_json
    from pathlib import Path
    old_cols = plan_columns(old_m, profile)
    from .reroll import deferring
    if deferring():                                   # 0.24.29: 'batch' plans once, at the end
        rerun()
        good(label + "  {note}(" + _deferred() + "){/}")
        return
    info("re-running the plan (analysis is reused) ...")
    rerun()
    new_m = read_json(Path(config.answer("last_matchup")))
    good(label)
    unused = False
    for n in new_m.get("diagnostics", {}).get("pins", []):
        warn(n)
        unused = unused or " not used: " in n
    who = label.split(":")[0]
    for n in new_m.get("diagnostics", {}).get("faces", []):     # 0.24.17: why a face doesn't sing
        if who and who in n:
            warn(n)
    for t, ex in new_m.get("diagnostics", {}).get("excluded_effects", {}).items():
        for x in ex:
            if x["reason"].startswith("pinned, but"):
                warn(f"{t}: {x['effect']} {x['reason']}")
    lines = diff(old_cols, plan_columns(new_m, profile), profile)
    ob, nb = (old_m.get("palettes") or {}).get("base") or {}, (new_m.get("palettes") or {}).get("base") or {}
    if ob.get("colors") != nb.get("colors") and nb.get("colors"):          # 0.24.30: colours count as a change
        lines.append("  colours: " + " ".join(f"{{{c}}}\u2588\u2588{{/}}" for c in ob.get("colors") or [])
                     + "  ->  " + " ".join(f"{{{c}}}\u2588\u2588{{/}}" for c in nb["colors"]))
    if not lines and unused:                          # 0.24.15: not "already the choice there"
        print("  (nothing changed: the pin isn't used - see above)")
        return
    print("\n".join(lines) if lines else "  (no visible change: it was already the choice there"
          + (" - a face sings only where its voice's words are sung; 'explain PROP @TIME' says why there"
             if "(sing" in label or " sing" in label else "") + ")")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool pin", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("words", nargs="*", help="TARGET [@#N|@TIME] [EFFECT]")
    ap.add_argument("--only", action="store_true", help="this section only, not the sections that repeat it")
    ap.add_argument("--all", action="store_true", help="keep the target's current effect in every section (a whole row)")
    ap.add_argument("--how", default=None, help=argparse.SUPPRESS)          # a score's placed pins (promote / demote)
    a = ap.parse_args(argv)
    from .reroll import _context
    path, m, profile, sha = _context()
    pins = list(songs.get(sha).get("pins", []))
    if not a.words:
        if not pins:
            print("no pins for this song - e.g. '{do}pin MegaTree @#3{/}' keeps MegaTree's effect in section 3")
            return 0
        print(f"{{head}}pins{{/}} ({len(pins)}):")
        for p in pins:
            print(describe(p, profile))
        print("{note}('unpin TARGET [@#N]' removes them){/}")
        return 0
    if a.all:                                         # the whole row: every section keeps what it has now
        target, pass_ = _resolve(m, " ".join(a.words))
        new = []
        for sec in profile["sections"]:
            eff = _current_effect(m, target, pass_, sec["start"], sec["end"])
            if eff:
                new.append({"target": target, "pass": pass_, "at": round((sec["start"] + sec["end"]) / 2, 3),
                            "effect": eff, "repeats": False})
        if not new:
            raise SystemExit(f"pin: {target} has no plan to keep - 'run' first")
        keep = [p for p in pins if not (p["target"] == target and p.get("pass", "main") == pass_)]
        songs.update(sha, pins=keep + new)
        who = target + (f" ({pass_})" if pass_ != "main" else "")
        _apply_and_show(f"pinned {who} in all {len(new)} sections: "
                        + ", ".join(f"#{i + 1} {p['effect']}" for i, p in enumerate(new)), m, profile)
        return 0
    times = [w for w in a.words if w.startswith("@")]
    rest = [w for w in a.words if not w.startswith("@")]
    given = [w for w in rest if re.fullmatch(r"[A-Za-z_]+=.+", w)]       # 0.24.36: NAME=VALUE settings
    rest = [w for w in rest if w not in given]
    effects = config.load("effects")["effects"]
    effect = None
    if len(rest) > 1 and canon(rest[-1]) in effects:
        effect = canon(rest.pop())
    elif len(rest) == 1 and not times and canon(rest[0]) in effects:
        raise SystemExit("pin: which target? e.g. 'pin MegaTree spirals' or 'pin MegaTree @#3'")
    if not rest:
        raise SystemExit("pin: which target? e.g. 'pin MegaTree @#3'")
    target, pass_ = _resolve(m, " ".join(rest))
    trim_at = _trim_times(given, times, profile)       # 0.24.37: from=@T / until=@T can say the section
    if trim_at is not None:
        tsec, given = trim_at
        if not times:
            times = [f"@{(tsec['start'] + tsec['end']) / 2:.3f}"]
        a.only = True                                  # an @time is in one place: that section only
    if times:
        from .explain import parse_time
        t = parse_time(times[0], profile)
        sec = _section_at(profile, t)
        at = (sec["start"] + sec["end"]) / 2 if times[0].startswith("@#") else t
        span = (sec["start"], sec["end"])
    else:
        at, span = None, (0.0, profile["sections"][-1]["end"])
        if effect is None:
            raise SystemExit("pin: a whole-song pin needs an effect, e.g. 'pin MegaTree twinkle'")
    if pass_ == "pin" and effect is None:
        raise SystemExit(f"pin: {target} plays its group's effect there - name the effect it should show instead, "
                         f"e.g. 'pin {target} {' '.join(times)} dark'".replace("  ", " "))
    if pass_ == "pin" and effect == "transparent":
        raise SystemExit(f"pin: 'transparent' on {target} alone changes nothing (its group still shows) - "
                         f"'dark' blacks it out, e.g. 'pin {target} {' '.join(times)} dark'".replace("  ", " "))
    if effect is None:
        effect = _current_effect(m, target, pass_, *span)
        if effect is None:
            raise SystemExit(f"pin: {target} has no plan there to keep - name an effect, e.g. 'pin {target} {' '.join(times) or ''} twinkle'")
    elif effect not in effects:
        raise SystemExit(f"pin: unknown effect '{effect}' - 'effects' lists them")
    if effect == "face":
        raise SystemExit(f"pin: a singing face is a reaction, not a pin - 'react {target} sing {' '.join(times) or '@TIME'}' "
                         f"(here) or 'face use {target} FACE' (every song)".replace("  ", " "))
    new = {"target": target, "pass": pass_, "at": None if at is None else round(at, 3),
           "effect": effect, "repeats": not a.only}
    if a.how:
        new["how"] = a.how
    if given:
        from .parameters import glide_value as user_value                     # 0.24.48: 'a..b' glides
        from .parts import setting_specs                                       # render, area, rotation too
        specs = {**setting_specs(effects[effect]),
                 "onset": {"trim": True}, "offset": {"trim": True}}     # 0.24.37: later start / earlier end
        params = {}
        for g in given:
            k, v = g.split("=", 1)
            k = TRIM_ALIASES.get(k.lower(), k.lower())
            if k in specs and specs[k].get("text") and specs[k].get("required") is None and not v:
                raise SystemExit(f"pin: {k}= needs a value - e.g. 'pin {target} {effect} {k}=pumpkin.gif'")
            if k in ("onset", "offset"):
                try:
                    params[k] = trim_text(v, profile)
                except ValueError as e:
                    raise SystemExit(f"pin: {k}={v}: {e} - e.g. 'pin {target} {' '.join(times)} {effect} "
                                     f"onset=2b' (2 bars in), 'offset=25%', 'until=@vocals'".replace("  ", " ")) from None
                continue
            if k not in specs:
                raise SystemExit(f"pin: {effect} has no setting '{k}'" + (f" - its settings: {', '.join(specs)}"
                                 if specs else " - it has none") + f" ('effects {effect}' shows them)")
            try:
                params[k] = user_value(k, specs[k], v)
                if k == "render":
                    params[k] = str(params[k]).replace("-", "_")
            except ValueError as e:
                raise SystemExit(f"pin: {e} - e.g. 'pin {target} {' '.join(times)} {effect} {k}="
                                 f"{specs[k]['choices'][0] if 'choices' in specs[k] else '0.8'}'".replace("  ", " ")) from None
        from ..common.showfiles import bring_in, file_settings
        for k in file_settings(effect):                         # 0.24.47: kept inside the show folder
            if params.get(k):
                params[k] = bring_in(str(params[k]), f"{effect} {k}")
        new["params"] = params
    if effect == "picture" and not (new.get("params") or {}).get("file"):
        raise SystemExit(f"pin: a picture needs its file - e.g. 'pin {target} {' '.join(times)} picture "
                         "file=pumpkin-ani.gif' (in the show folder, or a path)".replace("  ", " "))
    if effect == "choreo" and not (new.get("params") or {}).get("name"):
        raise SystemExit(f"pin: a choreography needs its name - e.g. 'pin {target} {' '.join(times)} choreo "
                         "name=\"both arms wave\"' (a definition: 'define' lists them)".replace("  ", " "))
    same = lambda p: (p["target"], p.get("pass", "main"), p.get("at")) == (target, pass_, new["at"])  # noqa: E731
    pins = [p for p in pins if not same(p)] + [new]
    songs.update(sha, pins=pins)
    _apply_and_show("pinned: " + describe(new, profile).strip(), m, profile)
    return 0


def main_unpin(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool unpin", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("words", nargs="*", help="TARGET [@#N|@TIME]")
    ap.add_argument("--all", action="store_true", help="remove every pin for this song")
    a = ap.parse_args(argv)
    from .reroll import _context
    path, m, profile, sha = _context()
    pins = list(songs.get(sha).get("pins", []))
    if not pins:
        print("no pins for this song")
        return 0
    if a.all:
        keep = []
    else:
        times = [w for w in a.words if w.startswith("@")]
        rest = [w for w in a.words if not w.startswith("@")]
        if not rest:
            raise SystemExit("unpin: which target? e.g. 'unpin MegaTree @#3', or 'unpin --all'")
        target, pass_ = _resolve(m, " ".join(rest))
        sec = None
        if times:
            from .explain import parse_time
            sec = _section_at(profile, parse_time(times[0], profile))

        named_pass = any(" ".join(rest).endswith(suf) for suf in PASS_SUFFIX)

        def hit(p):                         # 'unpin MegaTree' covers all its layers; 'MegaTree (enhance)' one
            if p["target"] != target or (named_pass and p.get("pass", "main") != pass_):
                return False
            return sec is None or covers(p, sec, profile)
        keep = [p for p in pins if not hit(p)]
        if len(keep) == len(pins) and named_pass:     # the layer named may not be where the pin is (0.21.1)
            named_pass = False
            keep = [p for p in pins if not hit(p)]
        if len(keep) == len(pins):
            mine = [p for p in pins if p["target"] == target]
            raise SystemExit(f"unpin: no pin on {target}" + (f" in section #{sec['index']}" if sec else "")
                             + (" - its pins:\n" + "\n".join(describe(p, profile) for p in mine) if mine
                                else " - 'pin' lists the song's pins"))
    removed = [p for p in pins if p not in keep]
    songs.update(sha, pins=keep)
    _apply_and_show(f"removed {len(removed)} pin(s):\n" + "\n".join(describe(p, profile) for p in removed), m, profile)
    return 0


def _deferred() -> str:
    from .reroll import deferred_note
    return deferred_note()


if __name__ == "__main__":
    sys.exit(main())
