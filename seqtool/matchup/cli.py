# seqtool-command: match | main | stages | music + profile + models (+ feedback) -> matchup.json
"""seqtool-match: choose effects and abstract parameters for every target."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..common.canonical import read_json, write_json
from . import engine
from ..common.paths import arg as paths_arg

PREF_FILES = ("effects", "scoring", "models", "palettes", "presets")


def load_prefs(pref_dir: Path | None = None) -> dict:
    """Built-in defaults overlaid with the user's preference folder."""
    from ..common.config import load
    return {name: load(name, pref_dir) for name in PREF_FILES}


LABELS = {"model_fit": "prop-type fit", "capability_fit": "geometry fit", "music_fit": "music fit",
          "style_fit": "style fit", "section_fit": "section fit"}


CLASS_WORDS = {"CONE": "tree / cone", "SURFACE_2D": "flat panel / matrix", "LINEAR": "line / outline",
               "ARC": "arch", "RING": "ring / wreath", "RADIAL": "spinner / radial", "ORNAMENT": "star / ornament",
               "VOLUME": "3-D volume", "FIGURE": "3-D figure", "FLOOD": "flood / single light",
               "IRREGULAR": "irregular shape"}


def _details(ctx: dict, target: str, eff_id: str, at: float, seg: dict) -> dict:
    """Short notes saying what each factor was based on, at the moment `at`."""
    from .scoring import capability_fit  # noqa: F401  (documentation of what is reported)
    from .windows import build_windows
    notes: dict[str, str] = {}
    prefs, music, profile, models = ctx.get("prefs"), ctx.get("music"), ctx.get("profile"), ctx.get("models")
    if not (prefs and music and profile and models):
        return notes
    eff = prefs["effects"]["effects"].get(eff_id, {})
    tg = next((m for m in models["models"] if m["id"] == target), None)
    if tg:
        cls = tg.get("geometry_class", "?")
        notes["model_fit"] = f"{cls} ({CLASS_WORDS.get(cls, cls.lower())}): {eff_id} is rated " \
                             f"{eff.get('model_fit', {}).get(cls, eff.get('model_fit', {}).get('default', 0.5)):.2f} for it"
        req = eff.get("geometry_requirements", {})
        caps = tg.get("capabilities", {})
        if req:
            notes["capability_fit"] = "needs " + ", ".join(
                f"{k.replace('_', ' ')} {v:.2f}, has {caps.get(k, 0):.2f}" for k, v in list(req.items())[:2])
        else:
            notes["capability_fit"] = "no special geometry needed"
    try:
        if "windows" not in ctx:                      # built once per context (the GUI explains every segment)
            sc = prefs["scoring"]
            from ..common.config import music_prefs
            ctx["windows"] = build_windows(music, profile, sc["decision"], sc["continuity"],
                                           music_prefs().get("section_types", {}))
        w = next((w for w in ctx["windows"] if w.start <= at < w.end), None)
    except Exception:  # noqa: BLE001
        w = None
    if w is not None:
        ideal = eff.get("music_fit", {})
        parts = [f"{k} {w.features[k]:.2f}/{v:.2f}" for k, v in ideal.items() if k in w.features]
        notes["music_fit"] = "heard/ideal: " + ", ".join(parts[:4])
        aff = eff.get("section_affinity", {})
        label = next((x.get("type") for x in profile["sections"] if x["id"] == w.section_id), w.section_type)
        shown = label if label == w.section_type else f"{label} (treated as {w.section_type})"
        notes["section_fit"] = f"{shown}, label confidence {w.section_confidence:.2f}: " \
                               f"affinity {aff.get(w.section_type or '', 0.5):.2f}"
    styles = sorted(profile["profile"]["styles"].items(), key=lambda kv: -kv[1])[:2]
    saff = eff.get("style_affinity", {})
    notes["style_fit"] = ", ".join(f"{k} {v:.2f} -> {saff.get(k, 0.5):.2f}" for k, v in styles) + " (song style -> affinity)"
    return notes


def explain_context(matchup_path) -> dict:
    """The files explain needs for its detail notes, found next to the matchup."""
    from pathlib import Path as _P
    mp = _P(matchup_path)
    try:
        m = read_json(mp)
        src = m["source"]
        return {"prefs": load_prefs(), "music": read_json(mp.with_name(src["music"]["filename"])),
                "profile": read_json(mp.with_name(src["music_profile"]["filename"])),
                "models": read_json(mp.with_name(src["models"]["filename"]))}
    except Exception:  # noqa: BLE001
        return {}


def carried_note(matchup: dict, target: str, ctx: dict) -> str | None:
    """Why a prop plays on its own (its groups, closest first), from the layout's analysis -
    for plans that don't carry the note themselves."""
    from .engine import alone_why
    mods = ctx["models"]["models"]
    me = next((x for x in mods if x["id"] == target), None)
    if me is None or me["kind"] != "model":
        return None
    sk = {s["id"]: s["reason"] for s in matchup.get("diagnostics", {}).get("skipped_targets", [])}
    cov = {s["id"]: s["reason"][len("driven via group "):] for s in matchup.get("diagnostics", {}).get("skipped_targets", [])
           if s["reason"].startswith("driven via group ")}
    mp = (ctx.get("prefs") or {}).get("models", {})
    return alone_why(mods, target, mp, sk, cov) or None


def explain(matchup: dict, target: str, at: float, profile: dict | None = None, ctx: dict | None = None,
            first_pass: str | None = None) -> str:
    """Decision trace: why `target` shows this effect at time `at` (seconds). Layers are
    listed top first; first_pass puts that pass's layer first (the one clicked in the GUI)."""
    weights = matchup["settings"].get("weights", {})
    ctx = ctx if ctx is not None else {}
    if profile is not None:
        ctx.setdefault("profile", profile)
    tplans = [p for p in matchup["plans"] if p["target"] == target]
    normal = [p for p in tplans if not p.get("react")]
    extra = "".join("\n\n" + explain_reactive(matchup, p, at, ctx.get("profile"))
                    for p in tplans if p.get("react")) if normal else ""
    if not normal and tplans:
        return explain_reactive(matchup, tplans[0], at, ctx.get("profile"))
    found: list[str] = []
    for fp in [p for p in normal if p.get("pass") == "face"]:     # singing faces: no scores to show
        seg = next((g for g in fp["segments"] if g["start"] <= at < g["end"]), None)
        if seg:
            found.append(f"{{head}}[layer {fp.get('layer', 0) + 1}, singing face]{{/}}\n"
                         f"{target} sings at {at:.1f} s with its face '{fp['face']}' ({seg['start']:.1f}-{seg['end']:.1f} s, "
                         f"the lyric lines there): xLights' Faces effect follows the phoneme layer of seqtool-lyrics"
                         + (" - its other layers rest meanwhile" if fp.get("mode") == "alone" else " - on top of its other layers")
                         + f"\n  {{note}}('face use {target} off' stops it; 'face use {target} FACE' picks another face){{/}}")
    normal = [p for p in normal if p.get("pass") != "face"]
    moments = {x["id"]: x for x in matchup.get("moments", [])}
    for bp in [p for p in normal if p.get("pass") == "base"]:    # whole-yard moments (0.20)
        seg = next((g for g in bp["segments"] if g["start"] <= at < g["end"]), None)
        if seg:
            mo = moments.get(seg.get("moment"), {})
            how = {"cut": "its own effects rest for the whole moment", "over": "drawn above its own effects",
                   "under": "only where its own effects rest"}.get(bp.get("members", "cut"), "")
            found.append(f"{{head}}[base pass, moment {seg.get('moment')}]{{/}} {target} flashes "
                         f"'{seg['selected']['effect']}' at {seg['start']:.2f}-{seg['end']:.2f} s: "
                         + "; ".join(seg.get("reasons", [])).replace(f"moment {seg.get('moment')}: ", "")
                         + (f" - with {len(mo.get('targets', []))} props, {mo['start']:.1f}-{mo['end']:.1f} s" if mo else "")
                         + (f"; {how}" if how else "")
                         + "\n  {note}(scoring.passes.base: per_minute, members, types; "
                         + f"'pref models/targets/{target}/base = false' leaves {target} out){{/}}")
    normal = [p for p in normal if p.get("pass") != "base"]
    for bp in [p for p in normal if p.get("pass") == "borrowed"]:  # kept from an existing .xsq (0.20.4)
        seg = next((g for g in bp["segments"] if g["start"] <= at < g["end"]), None)
        if seg:
            found.append(f"{{head}}[borrowed, layer {bp.get('layer', 0) + 1}]{{/}} {target} plays xLights' "
                         f"'{seg['selected']['effect']}' at {seg['start']:.2f}-{seg['end']:.2f} s, exactly as in the "
                         f"sequence it came from: " + "; ".join(seg.get("reasons", []))
                         + f"\n  {{note}}(its other effects give way there; 'unborrow {target}' gives it back to seqtool){{/}}")
    normal = [p for p in normal if p.get("pass") != "borrowed"]
    PASS_WORDS = {"top": "top pass: the whole group takes over this section",
                  "detail": "detail pass: accents on its parts, above the parent's effects",
                  "enhance": "enhance pass: a second layer of accents",
                  "pin": "pinned: a row of its own, above its group's",
                  "place": "placed with promote / demote: everything inside it rests here",
                  "choreo": "a part of a choreography (pinned 'choreo' - 'define get NAME' shows its steps)"}
    for plan in sorted(normal, key=lambda p: (p.get("pass", "main") != first_pass, -p.get("layer", 0))):
        rest = plan.get("rests") or {}
        if any(a <= at < b for a, b in rest.get("spans", [])) and not any(
                s["start"] <= at < s["end"] and s["selected"]["effect"] != "transparent"
                for p_ in normal for s in p_["segments"]):  # not while another of its layers plays (a pin)
            msg = (f"{{head}}{target} rests at {at:.1f} s{{/}}: the top group {rest.get('for')} takes over this section "
                   "(top pass; scoring.passes.top)")
            if msg not in found:                       # once, whichever layers rest
                found.append(msg)
        for s in plan["segments"]:
            if not (s["start"] <= at < s["end"]):
                continue
            if plan.get("pass") == "choreo":            # a choreography's part (0.24.47): no scores
                cols = s.get("palette_colors") or matchup.get("palettes", {}).get(s.get("palette", ""), {}).get("colors", [])
                found.append("\n".join([
                    f"{{head}}[layer {plan.get('layer', 0) + 1}, {PASS_WORDS['choreo']}]{{/}}",
                    f"{{head}}Why {target} plays '{{b}}{s['selected']['effect']}{{/}}' at {at:.1f} s{{/}}",
                    f"  the part runs {s['start']:.2f}-{s['end']:.2f} s - {s.get('why', '')}",
                    f"  parameters:   {s.get('parameters')}" + (f"  (yours: {', '.join(s['yours'])})" if s.get("yours") else ""),
                    f"  colours:      {' '.join(cols)}" if cols else "  colours:      the base palette",
                    f"  {{note}}('define get \"{str(s.get('choreo', '')).split(' > ')[-1].split(' step ')[0]}\" --for {target}' "
                    "shows the steps){/}"]))
                continue
            b = s["score_breakdown"]
            sec = ""
            if profile:
                ps = next((x for x in profile["sections"] if x["id"] == s.get("section")), None)
                if ps:
                    sec = f" (section #{ps['index']} {ps.get('type', '?')})"
            notes = _details(ctx, target, s["selected"]["effect"], at, s)
            L = [f"{{head}}Why {target} uses '{{b}}{s['selected']['effect']}{{/}}' at {at:.1f} s{sec}{{/}}",
                 f"  the segment runs {s['start']:.1f}-{s['end']:.1f} s",
                 "",
                 f"  {{head}}{'factor':<16}{'value':>7} x {'weight':>6} = {'part':>6}   based on{{/}}"]
            total_w = sum(weights.get(k, 0) for k in LABELS) or 1.0
            acc = 0.0
            for k, lab in LABELS.items():
                w = weights.get(k, 0.0)
                part = b[k] * w
                acc += part
                L.append(f"  {lab:<16}{b[k]:>7.2f} x {w:>6.2f} = {part:>6.3f}" + (f"   {{note}}{notes[k]}{{/}}" if k in notes else ""))
            base = acc / total_w
            L.append(f"  {'':<16}{'':>7}   {'sum':>6}   {acc:>6.3f}")
            L.append(f"  weighted average   {acc:.3f} / {total_w:.2f} (sum of weights) = {base:.3f}")
            pref = b["user_preference"]
            rules_hit = plan.get("rules") or []
            src = ("your effect preference for this target" if not rules_hit else
                   "name rule " + ", ".join(f"/{r}/" for r in rules_hit) + " (models.json rules)")
            L.append(f"  x user preference  {pref:.2f}  -> {base * pref:.3f}"
                     + ("" if pref == 1 else f"   ({src})"))
            L.append(f"  + random variation {b['random_variation']:+.3f} -> {b['static']:.3f}  (static score; seed-based)")
            cont = s.get("continuity")
            cnote = ""
            if cont:
                cnote = (f"   previous '{cont['previous_effect']}', transition strength "
                         f"{cont['transition_strength']:.2f}" + (f" ({cont['why']})" if cont.get("why") else ""))
            L.append(f"  + continuity       {b['continuity']:+.3f} -> {{ok}}{b['final']:.3f}  (final){{/}}{{note}}{cnote}{{/}}")
            alts = s["alternatives"]
            if alts and alts[0]["score"] > b["static"]:
                gap = alts[0]["score"] - b["static"]
                prev = s.get("continuity", {}).get("previous_effect")
                why = (f"it was already running ({prev}) and switching would cost more than the "
                       f"{gap:.3f} difference" if prev == s["selected"]["effect"]
                       else f"the whole-song path (continuity across neighbouring segments) scores higher")
                L.append(f"  {{warn}}note:{{/}} {alts[0]['effect']} scored higher here ({alts[0]['score']:.3f}), but {why}")
            L.append("")
            L.append(f"  parameters:   {s.get('parameters')}")
            pal = matchup.get("palettes", {}).get(s.get("palette", ""), {})
            if pal:
                L.append(f"  colours:      {' '.join(pal['colors'])}  - {s.get('palette')} palette: {pal.get('why', '')}")
            L.append("  alternatives: " + ", ".join(f"{a['effect']} {a['score']:.2f}" for a in s["alternatives"]))
            L.append("  reasons:      " + "; ".join(s["reasons"]))
            if s.get("pinned"):
                L.append(f"  {{ok}}pinned by you{{/}} - {s['selected']['effect']} here whatever the scores say "
                         f"('unpin {plan['target']} @{at:.1f}' to let seqtool choose again)")
            if s["selected"]["effect"] == "dark":
                L.append("  {note}'dark' blanks the prop: it masks lower layers and earlier rows (xLights Off).{/}")
            elif s["selected"]["effect"] == "transparent" and not s.get("pinned"):
                best = max(s["alternatives"], key=lambda a: a["score"]) if s["alternatives"] else None
                why_off = ("'transparent' (no effect from this pass, so whatever is underneath shows) is chosen like "
                           "any other effect - there is no score threshold. It wins where quiet, sparse music suits "
                           "it better than any lit effect")
                if plan.get("pass") == "enhance":
                    why_off += "; the enhance layer also only plays where energy >= passes.enhance.min_energy"
                elif plan.get("pass") == "detail":
                    why_off += "; detail layers rest unless an accent adds something (passes.detail.rest)"
                L.append("  {note}" + why_off + (f" (best lit choice here: {best['effect']} {best['score']:.2f}"
                                                 f" vs transparent {b['static']:.2f})" if best else "") + ".{/}")
            L.append("  {note}(factor values are averages over the segment's decision windows; 'based on' notes are "
                     f"for {at:.1f} s; heard/ideal = the music's value / the effect's ideal value){{/}}")
            if plan.get("pass", "main") != "main":
                L.insert(0, f"{{head}}[layer {plan.get('layer', 0) + 1}, {PASS_WORDS.get(plan['pass'], plan['pass'])}]{{/}}")
            found.append("\n".join(L))
    why_t = next((p["why_target"] for p in normal if p.get("why_target") and p.get("pass", "main") == "main"), None)
    if why_t is None and ctx.get("models") and any(p.get("pass", "main") == "main" for p in normal):
        why_t = carried_note(matchup, target, ctx)   # a plan made before 0.20.7: worked out now
    if found and why_t:                          # why this prop (or group) carries the effect (0.20.7; first: 0.21)
        found.insert(0, f"{{head}}{target}{{/}}: {why_t}")
    if found:
        return "\n\n".join(found) + extra
    if normal:
        return f"{target}: nothing at {at:.1f} s (its layers rest here)" + extra
    return f"no segment for {target} at {at}s"


def explain_reactive(matchup: dict, plan: dict, at: float, profile: dict | None) -> str:
    from . import reactive
    seg = next((g for g in plan["segments"] if g["start"] <= at < g["end"]), None)
    react = plan["react"]
    part = next((q for q in plan.get("react_parts", []) if any(a <= at < b for a, b in q["spans"])), None)
    scope = ""
    if part:                                         # 0.21.4: the setting that applies here
        react = part["react"]
        scope = {"song": " (this song)", "section": " (this song, these sections: "
                 + ", ".join(f"{a:.1f}-{b:.1f} s" for a, b in part["spans"]) + ")"}.get(part["scope"], "")
    try:
        what = reactive.describe(react)
    except Exception:  # noqa: BLE001
        what = react
    how = (f"name rule {', '.join('/' + r + '/' for r in plan['rules'])} (models.json rules)" if plan.get("rules")
           and not scope else f"'react {plan['target']} {react}'{scope}")
    L = [f"{{head}}{plan['target']} is music-reactive{{/}}: {what}.",
         f"  {len(plan['segments'])} effects over the song" + (" on the layer above its normal effects"
                                                                if plan.get("layer", 0) else "")
         + f"; set by {how}."]
    if seg:
        p = seg.get("parameters", {})
        ps = ", ".join(f"{k} {v:.2f}" if isinstance(v, float) else f"{k} {v}" for k, v in p.items())
        L.append(f"  at {at:.1f} s: '{seg['selected']['effect']}' {seg['start']:.2f}-{seg['end']:.2f} s"
                 + (f" from preset '{seg['preset']}'" if seg.get("preset") else "")
                 + (f", {ps}" if ps else "")
                 + (f", colour {seg['palette_colors'][0]}" if seg.get("palette_colors") else "")
                 + (f" - {seg['why']}" if seg.get("why") else ""))
        why = _why_its_own(seg, react)
        if why:
            L.append("  " + why)
    else:
        L.append(f"  at {at:.1f} s: nothing from this layer (between events, or no preset's conditions matched)")
    return "\n".join(L)


def _why_its_own(seg: dict, react) -> str:
    """0.24.37: why a reaction is many short effects where one long one would do - the setting
    that changes from one to the next, and glides written as steps."""
    from . import reactive
    name = seg.get("preset")
    try:
        spec = reactive.get_preset(reactive.load_presets(), name) if name else None
    except Exception:  # noqa: BLE001
        spec = None
    if not spec:
        return ""
    eff = seg["selected"]["effect"]
    on = spec.get("on", "event")
    per = {"downbeat": "bar", "beat": "beat", "onset": "note onset", "word": "sung word", "lyric": "lyric line",
           "section": "section"}.get(on, reactive.WHY.get(on, on))
    varied = []
    for k, v in (spec.get("params") or {}).items():
        if isinstance(v, dict):
            if "from" in v:
                varied.append(f"{k} follows the {v['from']}")
            elif "cycle" in v:
                varied.append(f"{k} cycles through {len(v['cycle'])} values")
            elif "step" in v:
                varied.append(f"{k} steps with the position in the bar")
            elif "if" in v:
                varied.append(f"{k} depends on the music there")
    ramps = {k: v["ramp"] for k, v in (seg.get("parameters") or {}).items() if isinstance(v, dict) and "ramp" in v}
    parts = []
    if varied:
        parts.append(f"why its own effect: the reaction puts in one '{eff}' per {per} instead of one long '{eff}', "
                     f"so that {', '.join(varied)} (the value here is in the settings above)")
    if spec.get("keyframes") or spec.get("split"):
        kf = sorted({k for f in (spec.get("keyframes") or {}).values() for k in f if k not in
                     ("animation-timing-function", "timing")})
        parts.append(("this is one step of the " + per + "'s keyframes" if spec.get("keyframes")
                      else f"this is one of the {spec['split']} steps of each {per}")
                     + (f": {', '.join(kf)} changes from step to step" if kf else ""))
    if ramps:
        parts.append("a glide (" + ", ".join(f"{k} {a:.2f} -> {b:.2f}" for k, (a, b) in ramps.items())
                     + "): written to xLights as short effects of 0.1 s that step through it (value curves "
                     "aren't used)")
    return "{note}" + "; ".join(parts) + "{/}" if parts else ""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool-match", description=__doc__)
    ap.add_argument("--music", type=paths_arg, default=None,
                    help="music.json (default: the current song's newest analysis)")
    ap.add_argument("--profile", type=paths_arg, default=None,
                    help="default: next to the music.json, named like it (song.music-profile.json)")
    ap.add_argument("--models", type=paths_arg, default=None,
                    help="default: the stored show layout (seqtool layout), copied next to the output")
    ap.add_argument("--preferences", type=paths_arg, default=None,
                    help="user preference folder (default ~/seqtool-prefs); overlays the built-in defaults")
    ap.add_argument("--seed", type=int, default=None, help="default: the song's remembered seed")
    ap.add_argument("--output", "-o", type=paths_arg, default=None,
                    help="default: next to --music, named like it (song.matchup.json)")
    ap.add_argument("--feedback", type=paths_arg,
                    help="validation.json from a previous iteration; its feedback adjusts this run")
    ap.add_argument("--explain", nargs=2, metavar=("TARGET", "SECONDS"),
                    help="print the decision trace for one target at one time")
    ap.add_argument("--baseline", nargs="?", metavar="N", help="song N of your baseline instead (no N: each song in turn; 'baseline' lists them)")
    a = ap.parse_args(argv)
    from ..common.canonical import write_json as _wj
    from ..common.paths import seqtool_name, show, sibling
    from ..common import current as _cur
    given = a.music
    a.music = _cur.music_of(a.music)
    if given is None or str(given) != str(a.music):
        print(f"music: {show(a.music)}" + (" (the current song)" if given is None else ""))
    a.output = a.output or sibling(a.music, "matchup")
    a.profile = a.profile or sibling(a.music, "music-profile")
    if not Path(a.profile).exists():
        raise SystemExit(f"no {show(a.profile)} yet - 'classify-music \"{show(a.music, typed=True)}\"' makes it")
    if a.models is None:
        from ..layout import store
        cur = store.current(a.preferences)
        if cur is None:
            raise SystemExit("no --models given and no stored layout - run 'seqtool layout SHOWFOLDER' first")
        pipe = "-seqtool." not in Path(a.music).name               # a results folder: its layout.models.json
        a.models = Path(a.music).parent / "layout.models.json" if pipe else seqtool_name(a.music, "models")
        _wj(a.models, cur[1])
    fb = read_json(a.feedback).get("feedback") if a.feedback else None
    from ..common import songs
    _music = read_json(a.music)
    _sha = _music.get("lineage", {}).get("audio", "")
    if a.seed is not None and _sha:
        songs.update(_sha, _music["source"].get("filename"), seed=a.seed)
    a.seed = songs.seed(_sha) if _sha else (a.seed or 12345)
    _ovr = songs.seed_overrides(_sha) if _sha else {}
    m = engine.run(read_json(a.music), read_json(a.profile), read_json(a.models),
                   load_prefs(a.preferences), a.seed,
                   {"music": Path(a.music).name, "music_profile": Path(a.profile).name,
                    "models": Path(a.models).name}, feedback=fb, seed_overrides=_ovr,
                    pins=songs.get(_sha).get("pins") if _sha else None,
                    reacts=songs.get(_sha).get("react") if _sha else None,
                    cues=songs.get(_sha).get("cues") if _sha else None,
                    palette=songs.get(_sha).get("palette") if _sha else None,
                    feel=songs.get(_sha).get("feel") if _sha else None)
    write_json(a.output, m)
    from ..common import current
    current.remember(music=a.music, matchup=a.output)
    nseg = sum(len(p["segments"]) for p in m["plans"])
    print(f"wrote {show(a.output)} (iteration {m['settings']['iteration']}): {len(m['plans'])} targets, {nseg} segments, "
          f"{len(m['diagnostics']['skipped_targets'])} skipped")
    if a.explain:
        print(explain(m, a.explain[0], float(a.explain[1]), read_json(a.profile)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
