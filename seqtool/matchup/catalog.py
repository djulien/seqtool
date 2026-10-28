# seqtool-command: effects | effects_main | look | the effect types seqtool can choose, with help: effects [NAME]
# seqtool-command: presets | presets_main | refine | reaction presets for 'react' (beat, onset, energy, ...): presets [NAME]
"""Help for effect types and reaction presets.

    effects             every effect type: what it looks like, what it suits
    effects chase       one effect in detail: its ideal music, props, sections, parameters
    presets             the reaction presets 'react' can use (built-in and yours)
    presets beat-chase  one preset in detail, and how to make your own
"""
from __future__ import annotations

import argparse
import json
import sys

from ..common import config


def _xlights_names() -> dict:
    try:
        from pathlib import Path
        p = Path(__file__).resolve().parents[1] / "adapters" / "xlights" / "effect_map.json"
        return json.loads(p.read_text(encoding="utf-8"))["effects"]
    except Exception:  # noqa: BLE001
        return {}


def _top(d: dict, n: int = 3, skip=("default",)) -> str:
    items = sorted(((k, v) for k, v in d.items() if k not in skip), key=lambda kv: -kv[1])
    return ", ".join(f"{k} {v:.1f}" for k, v in items[:n] if v >= 0.5) or "-"


def effects_text(name: str | None = None) -> str:
    effs = config.load("effects")["effects"]
    xl = _xlights_names()
    if name is None:
        L = ["{head}Effect types{/} (generic names; the xLights effect each becomes is in brackets):", ""]
        for k, e in effs.items():
            L.append(f"  {{do}}{k:<11}{{/}} {e.get('help', '')}" + (f"  {{note}}[{xl[k]}]{{/}}" if xl.get(k) else ""))
        L += ["", "  effects NAME   details: ideal music, best props and sections, parameters",
              "  pref effects   change ratings; name rules (rules) and per-prop preferences bias the choice"]
        return "\n".join(L)
    k = next((x for x in effs if x == name or x.startswith(name)), None)
    if k is None:
        raise SystemExit(f"no effect type '{name}' - one of: {', '.join(effs)} (e.g. 'effects chase')")
    e = effs[k]
    L = [f"{{head}}{k}{{/}}" + (f"  [xLights: {xl[k]}]" if xl.get(k) else "") + f"  family {e.get('family', '-')}",
         f"  {e.get('help', '')}", "",
         "  ideal music:   " + (", ".join(f"{f} {v:.2f}" for f, v in e.get("music_fit", {}).items()) or "-"),
         "  best props:    " + _top(e.get("model_fit", {})) + f"  (others {e.get('model_fit', {}).get('default', 0.5):.1f})",
         "  sections:      " + (", ".join(f"{s} {v:.2f}" for s, v in e.get("section_affinity", {}).items()) or "-"),
         "  styles:        " + (", ".join(f"{s} {v:.2f}" for s, v in e.get("style_affinity", {}).items()) or "-"),
         f"  inertia:       {e.get('inertia', 0.5):.2f}  (how much it prefers to keep running once chosen)"]
    if e.get("geometry_requirements"):
        L.append("  needs:         " + ", ".join(f"{g} {v:.2f}" for g, v in e["geometry_requirements"].items()))
    ps = e.get("parameters", {})
    if ps:
        L.append("  parameters:")
        for p, spec in ps.items():
            L.append(f"    {p:<16} " + (f"one of {', '.join(spec['choices'])} (chosen by the seed)" if "choices" in spec
                                       else f"{spec['range'][0]}-{spec['range'][1]}, follows {spec['driver']}"))
    L.append("  (ratings are 0-1; 'music fit' compares what is heard with these ideals)")
    return "\n".join(L)


def presets_text(name: str | None = None) -> str:
    from .reactive import fmt_when, load_presets
    pr = load_presets()
    defaults = config.load("presets", config.DEFAULT_DIR).get("presets", {})
    if name is None:
        L = ["{head}Reaction presets{/} ('react TARGET PRESET'; a comma list = first match wins):", ""]
        for k, p in pr.items():
            mark = "" if k in defaults and defaults[k] == p else ("  (yours)" if k not in defaults else "  (changed)")
            L.append(f"  {{do}}{k:<18}{{/}} on {p.get('on', '?'):<9} {p.get('effect', '?'):<11} {p.get('help', '')}{mark}")
            if p.get("when"):
                L.append(f"  {'':<18} only when {fmt_when(p['when'])}")
        L += ["", "  presets NAME     one preset in full, and how to make your own"]
        return "\n".join(L)
    if name not in pr:
        raise SystemExit(f"no preset '{name}' - one of: {', '.join(pr)} (e.g. 'presets beat')")
    body = json.dumps(pr[name], indent=2)
    return "\n".join([f"{name}:", body, "", HOWTO])


HOWTO = """{head}Make your own:{/} copy one into seqtool-prefs/presets.json under "presets" with a new
name ('pref edit presets'), then 'react TARGET NAME'. Keys:
  on          beat | downbeat | onset | section | lyric | word (lyrics: 'lyrics import')
  when        conditions, all must hold: {"section": ["chorus","drop"], "energy": ">=0.6",
              "downbeat": true, "beat": [1,3], "bar": ">8"}
  every       use every Nth matching event (2 = every other beat)
  keyframes   CSS-style steps anywhere in the event (syncopation): {"0%": {...}, "37.5%": {...},
              "62.5%, 87.5%": {...}} - in a 4/4 bar each beat is 25%; values carry over;
              "animation-timing-function": linear | ease | ease-in | ease-out | ease-in-out |
              cubic-bezier(...) | steps(N) glides to the next keyframe (default: hold)
  split       divide each event into N equal steps (on downbeat + split 8 = eighth notes in 4/4)
  effect      an effect type ('effects' lists them)
  params      constant, {"from": "energy", "range": [lo, hi]}, {"if": {...}, "then": a, "else": b},
              {"cycle": [a, b]} (next value each event), or {"step": [a, b, ...]} (by position
              in the bar - a step sequencer)  ('effects NAME' lists an effect's parameters, values 0-1)
  palette     base | accent (or an "if")      colors  "cycle" = one palette colour per event
  max_length  cap in seconds (otherwise an event lasts until the next one)
Values for when/from: energy, energy_end, onset, brightness (any analysed level), downbeat,
beat (number in the bar), bar, step, section, section_index, time, lyric and word (the
text sung then; "~regex" tests it, e.g. {"lyric": "~(?i)merry"})."""


def effects_main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool effects", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", nargs="?")
    a = ap.parse_args(argv)
    print(effects_text(a.name))
    return 0


def presets_main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool presets", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", nargs="?")
    a = ap.parse_args(argv)
    print(presets_text(a.name))
    return 0


if __name__ == "__main__":
    sys.exit(effects_main())
