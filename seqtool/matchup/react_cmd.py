# seqtool-command: react | main | refine | make props follow the music: react TARGET PRESET[,PRESET..] [@#N | --song] [--over] | off
"""seqtool react [TARGET PRESET[,PRESET...] [@#N|@TIME [--only] | --song]] [--over]

    react                           list the props and groups that follow the music
    react MegaTree beat             a flash on every beat (brighter on the first beat of each bar)
    react Roofline downbeat         a flash on the first beat of every bar
    react Arches onset-sparkle      sparkles on each note onset
    react Floods energy-color       accent colours when the music is loud
    react Matrix energy-speed       spirals that speed up with the loudness
    with stems ('run --stems'):
    react MegaTree melody-fill      the tree fills up and down with the tune (higher note, fuller)
    react Floods melody-color       a colour per melody note, low notes the palette's first colour
    react Arches snare,kick,hat-sparkle
                                    the drum kit: snare flashes, kick flashes, hi-hat sparkles
    react Roofline bass-pulse       a glow on each bass note
    react Arches chorus-beat-chase,beat
                                    beat chases in choruses, plain beat flashes elsewhere
                                    (a list works like conditional formatting: first match wins)
    react MegaTree beat --over      on the layer above its normal effects
    react MegaTree off              back to normal effect choice
    react MegaTree beat --song      this song only (kept with the song, like pins)
    react MegaTree beat @#3         this song, section 3 and its repeats (--only: not the repeats);
                                    the rest of the song as before
    react MegaTree off @#5          no reaction in section 5 of this song (normal effects there)
    react MegaTree off --song       remove MegaTree's reactions for this song (all its sections)
    react Spinners spoke-bounce --on word --words star,night
                                    any preset's look on any event (here the spoke bounce on those
                                    words; kept as 'spoke-bounce@word[star|night]')
    react MegaTree word-flash --words star,night,bright
                                    a flash only when one of those words is sung (any preset; it is
                                    kept as 'word-flash[star|night|bright]' - typed that way too)
    (the GUI: Ctrl+click an effect, 'react ...')

For one song, later settings win where they overlap: a section's over the song's, the
song's over the preferences'.

'presets' lists every preset (built-in and your own) and how to make one.
'react' and 'rules ... react=' set the same thing at two scales: 'react' one
prop or group by its name, a rule every name a pattern matches (e.g. 'rules add
'(?i)arch' react=beat-chase' for all the arches, new ones included). When both
apply, 'react' wins; 'react' alone lists both kinds. TARGET is a name from the
stored layout, or from the layout the current song was planned with (the demo's).

Without --over the reactive effects replace the prop's normal effects. With
--over they go on the layer above: with xLights' default layer mixing the
upper layer wins where it is lit and the normal effects show where it is dark
(e.g. as a flash fades).
Settings are kept in your preferences (models.json); run again to update the plan.
"""
from __future__ import annotations

from ..common.suggest import suggest

import argparse
import sys
from pathlib import Path

from ..common import config
from ..common.log import good, info


def _song_layout_ids() -> list[str]:
    """Props and groups of the layout the current song's results were planned with -
    the demo's layout after 'demo', so a tutorial's 'react Matrix ...' works (0.19.9)."""
    try:
        from ..common import current
        from ..common.canonical import read_json
        s = current.song()
        if not s or not s.get("matchup"):
            return []
        m = read_json(s["matchup"])
        mf = Path(s["matchup"]).with_name(m["source"]["models"]["filename"])
        return [x["id"] for x in read_json(mf)["models"]] if mf.exists() else []
    except Exception:  # noqa: BLE001
        return []


def main(argv=None) -> int:
    from . import reactive
    ap = argparse.ArgumentParser(prog="seqtool react", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("words", nargs="*", metavar="TARGET PRESET [@#N]")
    ap.add_argument("--over", action="store_true", help="add on the layer above the normal effects")
    ap.add_argument("--song", action="store_true", help="this song only (the current song)")
    ap.add_argument("--only", action="store_true", help="with @#N: that section only, not its repeats")
    ap.add_argument("--on", dest="on_event", default=None, metavar="EVENT",
                    help="the preset's look on another event: beat, downbeat, onset, word, lyric, kick, snare ... "
                         "(e.g. react Spinners spoke-bounce --on word --words star)")
    ap.add_argument("--words", dest="only_words", default=None, metavar="W1,W2", help="only on these sung words (e.g. --words star,night): "
                    "the preset (word-flash, or any other) reacts where one of them is sung")
    a = ap.parse_args(argv)
    times = [w for w in a.words if w.startswith("@")]
    rest = [w for w in a.words if not w.startswith("@")]
    a.target = rest[0] if rest else None
    a.mode = rest[1] if len(rest) > 1 else None
    if len(rest) > 2:
        raise SystemExit("react TARGET PRESET[,PRESET...] [@#N] - one target (quote a name with spaces)")
    mp = config.load("models")
    targets = mp.get("targets", {})
    if not a.target:
        had = _list_song()
        rows = [(k, v["react"], v.get("react_over")) for k, v in sorted(targets.items())
                if v.get("react") and v.get("react") != "off"]
        rules = [r for r in mp.get("rules", []) or [] if r.get("react")]
        if not rows and not rules and not had:
            print("no props follow the music yet - e.g.  react MegaTree beat   ('presets' lists the choices)")
        for k, mode, over in rows:
            print(f"  {k:<24} {mode}" + ("   (on top of its normal effects)" if over else ""))
        for r in rules:
            print(f"  /{r['match']}/{'':<{max(0, 22 - len(r['match']))}} {r['react']}"
                  + ("   (on top of its normal effects)" if r.get("react_over") else "") + "   (name rule)")
        return 0
    if not a.mode:
        raise SystemExit("react TARGET PRESET[,PRESET...] [--over]  ('presets' lists them)")
    name = a.target
    try:                                                # accept the name as typed in the layout, any case
        from ..layout import store
        cur = store.current()
        ids = [m["id"] for m in cur[1]["models"]] if cur else []
        ids += _song_layout_ids()                       # the layout the current song was planned with (the demo's)
        if ids:
            exact = [i for i in dict.fromkeys(ids) if i.lower() == name.lower()]
            if not exact:
                raise SystemExit(f"no prop or group named '{name}' in the stored layout or the current song's plan"
                                 + suggest(name))
            name = exact[0]
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        pass
    if (a.only_words or a.on_event) and a.mode != "off":   # 0.24.24/25: PRESET@EVENT[w1|w2]
        ws = None
        if a.only_words:
            ws = [w for w in a.only_words.replace("|", ",").split(",") if w.strip()]
            if not ws:
                raise SystemExit("react ... --words W1,W2 - e.g. 'react MegaTree word-flash --words star,night'")
        if a.on_event and a.on_event not in reactive.TRIGGERS:
            raise SystemExit(f"react ... --on {a.on_event}: the events are {', '.join(reactive.TRIGGERS)} - "
                             "e.g. 'react Spinners spoke-bounce --on word'")
        a.mode = ",".join(reactive.with_words(n, ws, a.on_event) for n in reactive.names_of(a.mode))
    if a.mode != "off":
        bad = reactive.check(a.mode, reactive.load_presets(), config.load("effects")["effects"])
        if bad:
            raise SystemExit("; ".join(bad))
    if times or a.song:                               # this song / this section (0.21.4)
        return _song_react(name, a.mode, times[0] if times else None, a.over, a.only)
    if a.mode != "off":
        mode = ",".join(reactive.names_of(a.mode))
        change = {"react": mode, "react_over": bool(a.over)}
    else:
        change = {"react": "off", "react_over": False}
    config.update("models", {"targets": {name: change}})
    label = f"{name}: " + ("normal effect choice" if a.mode == "off" else
                           f"follows the music ({change['react']})" + (" on top of its normal effects" if a.over else ""))
    replan_every_song(name, label)
    return 0


def take_song_overrides(name: str) -> list[str]:
    """0.24.17: a setting for every song, made now, wins in the current song too (the later command
    wins): this song's own reaction settings for the prop are taken away, and its pins on a row of
    its own under a group (they would cover the reaction). Returns what was taken, described."""
    try:
        path, m, profile, sha = _song_context()
    except SystemExit:
        return []
    if not sha:
        return []
    from ..common import songs
    from .pins import describe
    rec = songs.get(sha)
    ents, pins = list(rec.get("react") or []), list(rec.get("pins") or [])
    gone_r = [e for e in ents if e["target"] == name]
    gone_p = [x for x in pins if x.get("target") == name and x.get("pass") == "pin"]
    if gone_r:
        songs.update(sha, react=[e for e in ents if e not in gone_r])
    if gone_p:
        songs.update(sha, pins=[x for x in pins if x not in gone_p])
    return ([f"this song's reaction setting {describe({**e, 'effect': e['preset'], 'pass': 'main'}, profile).strip()}"
             for e in gone_r]
            + [f"this song's pin {describe(x, profile).strip()}" for x in gone_p])


def replan_every_song(name: str, label: str) -> None:
    """After a setting for every song (react PROP PRESET, face use PROP FACE): this song follows it
    (its own settings for the prop go - said), and the plan is made again at once, when there is one."""
    from ..common.log import good as _good
    gone = take_song_overrides(name)
    try:
        path, m, profile, sha = _song_context()
    except SystemExit:
        _good(label + " - 'run' makes a plan with it")
        return
    for g in gone:
        info(f"  {g} is taken away, so this setting shows in this song too ('undo' brings it back)")
    from .pins import _apply_and_show
    _apply_and_show(label, m, profile)


def _song_context():
    from .reroll import _context
    return _context()


def _list_song() -> bool:
    try:
        path, m, profile, sha = _song_context()
    except SystemExit:
        return False
    from ..common import songs
    from .pins import describe
    ents = songs.get(sha).get("react") or []
    if ents:
        print("{head}this song{/}:")
        for e in ents:
            d = describe({**e, "effect": e["preset"], "pass": "main"}, profile).rstrip()
            print(d + ("   (on top of its normal effects)" if e.get("over") else ""))
        print("{head}all songs{/} (preferences):")
    return bool(ents)


def _song_react(name: str, mode: str, when: str | None, over: bool, only: bool) -> int:
    from ..common import songs
    from .pins import _apply_and_show, _section_at, describe
    path, m, profile, sha = _song_context()
    if not sha:
        raise SystemExit("react ... --song: no current song - 'run --audio SONG' first")
    ents = list(songs.get(sha).get("react") or [])
    at, repeats = None, not only
    if when:
        from .explain import parse_time
        t = parse_time(when, profile)
        sec = _section_at(profile, t)
        at = round((sec["start"] + sec["end"]) / 2, 3) if when.startswith("@#") else round(t, 3)
    from . import reactive
    preset = "off" if mode == "off" else ",".join(reactive.names_of(mode))
    if at is None:
        if preset == "off":                            # off for the song: every setting for it goes
            ents = [e for e in ents if e["target"] != name]
            new = {"target": name, "at": None, "preset": "off", "over": False}
        else:
            ents = [e for e in ents if not (e["target"] == name and e.get("at") is None)]
            new = {"target": name, "at": None, "preset": preset, "over": over}
    else:
        sec = _section_at(profile, at)
        ents = [e for e in ents if not (e["target"] == name and e.get("at") is not None
                                        and _section_at(profile, float(e["at"])) is sec)]
        new = {"target": name, "at": at, "preset": preset, "over": over, "repeats": repeats}
    ents.append(new)
    dropped = []
    if at is not None and preset != "off":           # 0.24.11: what you ask for here wins over a pin there
        from .pins import covers
        sec = _section_at(profile, at)
        pins = list(songs.get(sha).get("pins") or [])
        keep = [x for x in pins if not (x.get("target") == name and x.get("at") is not None
                                          and x.get("pass", "main") != "place" and covers(x, sec, profile))]
        dropped = [x for x in pins if x not in keep]
        if dropped:
            songs.update(sha, pins=keep)
    songs.update(sha, react=ents)
    for x in dropped:
        info(f"  its pin there ({x.get('effect', '?')}) is taken away, so the reaction shows ('undo' brings it back)")
    what = describe({**new, "effect": preset, "pass": "main"}, profile).strip()
    _apply_and_show(f"{name}: " + ("no reaction" if preset == "off" else f"follows the music ({preset})")
                    + (" on top of its normal effects" if over else "") + f" - {what}", m, profile)
    info(f"('react {name} off {when or '--song'}' undoes it; 'react' lists the reactions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
