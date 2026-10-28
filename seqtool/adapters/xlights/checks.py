"""The xLights verification sequence (`xlights-export --checks`, 0.18.6).

One short .xsq with a labelled time slot for each export feature that still needs
checking in xLights: Fill, a glide written as steps, VU Meter, a submodel row, a
top-group row, and `dark` (Off) on a prop over a lit group row. A timing track
`seqtool-checks` names each slot and says what you should see; `seqtool-lyrics`
(phrases + words) is there to check too. Re-run it after every `xlights-kit --update`.

Nothing here is xLights-specific except the call to the exporter: the slots are an
ordinary generic plan, written by the same `build()` a real song uses.
"""
from __future__ import annotations

from pathlib import Path

from ...common import config
from ...common.log import good, info, warn
from ...common.paths import show
from . import encoding as enc_mod

SLOT = 6.0          # seconds per check
GAP = 1.0           # dark pause after each check, so slots are easy to tell apart

RED, GREEN, BLUE, AMBER = "#FF0000", "#00FF00", "#0000FF", "#FFA000"


def pick_targets(models: dict, prop: str | None = None, group: str | None = None,
                 submodel: str | None = None) -> dict:
    """The group, prop and submodel the checks use: the top group (as the top pass
    would pick it), its biggest usable member prop, and a submodel of that prop
    (else of any prop). Names given by the user win."""
    from ...matchup import rules
    from ...matchup.engine import group_role
    from ...common.suggest import suggest
    mprefs = rules.expand(config.load("models"), models)
    ms = models["models"]
    by_id = {m["id"]: m for m in ms}
    usable = [m for m in ms if m.get("supported_for_generation")]

    def named(name, kind):
        if name is None:
            return None
        hit = next((m for m in usable if m["id"].lower() == name.lower() and m["kind"] == kind), None)
        if hit is None:
            hint = suggest(name, [m["id"] for m in usable if m["kind"] == kind])
            raise SystemExit(f"no usable {kind} '{name}'" + hint)
        return hit

    g = named(group, "group")
    if g is None:
        tops = [m for m in usable if m["kind"] == "group" and group_role(m, mprefs) == "top"]
        tops.sort(key=lambda m: (-(m.get("role_guess") or {}).get("coverage", 0), m["id"]))
        groups = tops or sorted((m for m in usable if m["kind"] == "group"), key=lambda m: -m.get("node_count", 0))
        g = groups[0] if groups else None
    p = named(prop, "model")
    if p is None:
        members = set(g.get("members", [])) if g else set()
        props = [m for m in usable if m["kind"] == "model"]
        props.sort(key=lambda m: (m["id"] not in members, -m.get("node_count", 0), m["id"]))
        p = props[0] if props else None
    s = named(submodel, "submodel")
    if s is None:
        subs = [m for m in usable if m["kind"] == "submodel" and m.get("parent") in by_id
                and by_id[m["parent"]].get("supported_for_generation")]
        subs.sort(key=lambda m: (p is None or m.get("parent") != p["id"], -m.get("node_count", 0), m["id"]))
        s = subs[0] if subs else None
    return {"group": g, "prop": p, "submodel": s}


def slots(t: dict) -> list[dict]:
    """[{label, look, plans: [(target, effect, params, colours, pass)]}] - one per check."""
    g, p = (t[k]["id"] if t[k] else None for k in ("group", "prop"))
    s = t["submodel"]
    out = []
    if p:
        out += [
            {"name": "Fill", "label": f"Fill: {p} lit to half", "effect": "fill",
             "look": f"{p}: the lower half lit red, the upper half dark",
             "plans": [(p, "fill", {"position": 0.5, "direction": "up"}, [RED], "main")]},
            {"name": "Glide", "label": f"Glide: {p} fills up in steps", "effect": "fill",
             "look": f"{p}: red rising from empty to full - in the sequence, a run of short Fill effects",
             "plans": [(p, "fill", {"position": {"ramp": [0.05, 1.0]}, "direction": "up"}, [RED], "main")]},
            {"name": "VU Meter", "label": f"VU Meter: {p} follows the audio", "effect": "vu_meter",
             "look": f"{p}: Volume Bars - bars rising and falling with the music all through the slot "
                     "(needs media: --audio SONG)", "step": ("vu_meter", "type_volume_bars"),
             "plans": [(p, "vu_meter", {"style": "volume_bars", "sensitivity": 0.0}, [AMBER], "main")]},
        ]
    if s:
        parent = s.get("parent") or s["id"].split("/", 1)[0]
        out.append({"name": "Submodel", "label": f"Submodel row: only {s['id']}", "effect": "color_wash",
                    "look": f"only the '{s['name']}' part of {parent} lit blue; in the sequence the effect "
                            f"sits on the submodel row under {parent}",
                    "plans": [(s["id"], "color_wash", {}, [BLUE], "main")]})
    if g:
        out.append({"name": "Top group", "label": f"Top group: all of {g}", "effect": "color_wash",
                    "look": f"every prop in {g} lit green; its row is the first model row",
                    "plans": [(g, "color_wash", {}, [GREEN], "top")]})
        if p:
            out.append({"name": "Dark", "label": f"dark: {g} lit, {p} black", "effect": "dark",
                        "look": f"{g} green except {p}, which stays black (Off on {p}'s row wins over the group row)",
                        "plans": [(g, "color_wash", {}, [GREEN], "top"), (p, "dark", {}, [], "main")]})
    return out


def build_inputs(checks: list[dict], offset: float = 0.0, song_duration: float = 0.0) -> tuple[dict, dict, dict, dict]:
    """A generic matchup, music, profile and lyrics for the slots, starting at offset
    seconds (so with a song, the slots can sit where the music is loud)."""
    dur = max(offset + len(checks) * (SLOT + GAP) + GAP, song_duration)
    bpm = 120.0
    beats = [{"time": round(i * 0.5, 3)} for i in range(int(dur / 0.5))]
    downs = beats[::4]
    music = {"source": {"filename": "seqtool-checks"}, "audio": {"duration": dur},
             "analysis": {"events": {"beats": beats, "downbeats": downs},
                          "summary": {"tempo": {"bpm": bpm}}}}
    sections, lines, plans_by = [], [], {}
    for i, c in enumerate(checks):
        a = offset + GAP + i * (SLOT + GAP)
        b = a + SLOT
        sections.append({"index": i + 1, "start": a, "end": b, "type": c["label"]})
        words = c["name"].split() + ["check"]
        step = SLOT / 2 / len(words)
        lines.append({"start": a, "end": a + SLOT / 2, "text": " ".join(words),
                      "words": [{"start": a + k * step, "end": a + (k + 1) * step, "text": w}
                                for k, w in enumerate(words)]})
        for target, effect, params, colours, pass_ in c["plans"]:
            seg = {"start": a, "end": b, "selected": {"effect": effect}, "parameters": params,
                   "palette": "base", "palette_colors": colours or ["#FFFFFF"], "alternatives": []}
            plan = plans_by.setdefault((target, pass_), {"target": target, "pass": pass_, "layer": 0, "segments": []})
            plan["segments"].append(seg)
    order = sorted(plans_by.values(), key=lambda p: (p["pass"] != "top", p["target"]))
    matchup = {"source": {"music": {"filename": "seqtool-checks"}}, "settings": {"seed": "checks"},
               "palettes": {"base": {"colors": ["#FFFFFF"]}}, "plans": order}
    profile = {"sections": sections}
    lyrics = {"lines": lines}
    return matchup, music, profile, lyrics


def write(out: Path | None = None, audio: Path | None = None, version: str | None = None,
          prop: str | None = None, group: str | None = None, submodel: str | None = None) -> Path | None:
    from ...layout import store
    from . import export_xsq, xsq
    stored = store.current()
    if stored is None:
        warn("no layout stored yet - e.g. 'seqtool layout path/to/xlights_rgbeffects.xml'")
        return None
    lay, models = stored
    if lay.get("units") != "xlights":
        warn("the stored layout is not from xLights - e.g. 'seqtool layout path/to/xlights_rgbeffects.xml'")
        return None
    enc = enc_mod.find(version)
    if enc is None:
        warn("nothing learned yet for any xLights version - run 'seqtool xlights-kit' first")
        return None
    t = pick_targets(models, prop, group, submodel)
    checks = slots(t)
    if not checks:
        warn("no usable props or groups in the stored layout - check it with 'groups --list'")
        return None
    missing = sorted({c["effect"] for c in checks if not enc.supports(c["effect"])})
    pmap = enc_mod.param_map()
    for c in checks:                                  # a setting the check relies on (VU Meter's Type)
        if c.get("step") and enc.supports(c["effect"]) and enc.step(*c["step"], pmap) is None:
            c["unlearned"] = c["step"][1]
    if any(c.get("unlearned") for c in checks):
        warn("the kit has new steps (VU Meter: Volume Bars, Spectrogram) - 'seqtool xlights-kit --update' "
             "learns them; until then the VU Meter slot shows xLights' default type")
    if missing:
        warn(f"not learned yet for xLights {enc.version}: {', '.join(missing)} - those slots stay empty; "
             "'seqtool xlights-kit --update' learns them")
    if audio is None:
        from ...common import current
        cur = current.song()
        audio = cur["audio"] if cur and cur.get("audio") and Path(cur["audio"]).exists() else None
    offset, song_dur, where = 0.0, 0.0, ""
    if audio is not None:                              # put the slots where the music is (the VU Meter needs it)
        from ...common import current
        from ...common.canonical import read_json
        cur = current.song(audio)
        if cur and cur.get("profile"):
            prof = read_json(cur["profile"])
            song_dur = prof["sections"][-1]["end"]
            need = len(checks) * (SLOT + GAP) + GAP
            loud = [x for x in prof["sections"] if x.get("type") in ("chorus", "drop")] or \
                sorted(prof["sections"], key=lambda x: -(x.get("energy") or 0))
            offset = max(0.0, min(loud[0]["start"], song_dur - need)) if loud else 0.0
            offset = round(offset - GAP, 3) if offset >= GAP else offset
            where = f" (from {int(offset // 60)}:{offset % 60:04.1f}, the first {loud[0].get('type', 'loud part')})" \
                if loud and offset else ""
    matchup, music, profile, lyrics = build_inputs(checks, offset, song_dur)
    view = lay.get("views", {}).get(lay.get("default_view", ""), None)
    tree, notes = export_xsq.build(matchup, music, profile, models, audio, enc, view,
                                   ["sections", "lyrics"], lyrics)
    root = tree.getroot()
    for el in root.iter("Element"):                       # the slot labels are the checks track
        if el.get("type") == "timing" and el.get("name") == "seqtool-sections":
            el.set("name", "seqtool-checks")
    head = root.find("head")
    if head is not None and head.find("comment") is not None:
        head.find("comment").text = "seqtool verification sequence: one slot per check, see the seqtool-checks track"
    if out is None:
        kd = config.answer("kit_dir")
        out = (Path(kd) if kd and Path(kd).is_dir() else Path.cwd()) / "seqtool-checks.xsq"
    tree.write(out, encoding="UTF-8", xml_declaration=True)
    problems = export_xsq.check(out, enc, models, music["audio"]["duration"])
    for n in notes:
        if not n.startswith(("__views__:", "__phon__")) and "skipped: not learned" not in n:
            info(f"  note: {n}")
    for p in problems[:20]:
        warn(f"  {p}")
    n_eff = sum(1 for e in xsq.read(out).effects if e.element_type == "model")
    (good if not problems else warn)(f"wrote {show(out)}: {len(checks)} checks, {n_eff} effects for xLights "
                                     f"{enc.version}" + ("" if not problems else f", {len(problems)} problem(s)"))
    info("{head}Open it in xLights and play it. What each slot should show:{/}")
    if where:
        info(f"  {{note}}the slots start where the song gets loud{where}{{/}}")
    for i, c in enumerate(checks):
        a = offset + GAP + i * (SLOT + GAP)
        flag = "  {warn}(not learned yet){/}" if c["effect"] in missing else \
            "  {warn}(its Type isn't learned yet: xLights' default type instead){/}" if c.get("unlearned") else ""
        info(f"  {{b}}{int(a // 60)}:{a % 60:04.1f}{{/}}  {c['name']}: {c['look']}{flag}")
    info("  also: the seqtool-lyrics track has a phrase layer and a word layer, one line per slot")
    if audio is None:
        info("  {note}no media: the VU Meter slot needs a song - e.g. 'xlights-export --checks --audio song.mp3'{/}")
    info("  {note}timing tracks not showing? add seqtool-checks and seqtool-lyrics to your Master View "
         "(View > Display Elements){/}")
    others = sorted((m for m in models["models"] if m["kind"] == "model" and m.get("supported_for_generation")
                     and m["id"] != (t["prop"] or {}).get("id")), key=lambda m: -m.get("node_count", 0))
    if others and t["group"]:
        info(f"  {{note}}other props: e.g. 'xlights-export --checks --prop {others[0]['id']} "
             f"--group {t['group']['id']}'{{/}}")
    return out
