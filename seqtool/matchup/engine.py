"""Matchup engine: music.json + music-profile.json + models.json + prefs -> matchup.json"""
from __future__ import annotations

import re

from ..common.canonical import content_sha256
from ..common.vocab import canon_role, lit
from ..common.envelope import check_version, envelope
from ..common.schemas import validate
from . import scoring
from .continuity import transition_value, viterbi
from .parameters import build_palettes, parameters
from .windows import build_windows

COMPONENT_KEYS = ("model_fit", "capability_fit", "music_fit", "style_fit",
                  "section_fit", "user_preference", "random_variation")


def _target_prefs(name: str, prefs: dict, feedback: dict | None = None) -> dict:
    out = dict(prefs.get("defaults", {}))
    out.update(prefs.get("targets", {}).get(name, {}))
    fb = (feedback or {}).get("targets", {}).get(name)
    if fb:  # validator feedback: scale preferences, never override user exclusions
        ep = dict(out.get("effect_preferences", {}))
        for e, mult in fb.get("effect_preference_scale", {}).items():
            ep[e] = ep.get(e, 1.0) * mult
        out["effect_preferences"] = ep
        out["change_penalty_scale"] = out.get("change_penalty_scale", 1.0) * fb.get("change_penalty_scale", 1.0)
        out["section_effect_scale"] = fb.get("section_effect_scale", {})
    return out


def face_entries(tp: dict, model: dict, notes: list | None = None) -> list[dict]:
    """The faces a prop sings with (0.24.0): [{"face", "voice", "area"}] from 'face use' (several
    on one matrix, each its own voice and area), the older single 'face', else its only face."""
    got = [dict(e) for e in tp.get("sing") or [] if e.get("face")]
    if not got and tp.get("face") not in (None, "off", "none"):
        got = [{"face": tp["face"]}]
    known = [f["name"] for f in model.get("faces", [])]
    if not got and known:
        got = [{"face": known[0]}]
        if notes is not None and len(known) > 1:
            notes.append(f"face {model['id']}: sings with '{known[0]}' (it has {len(known)}: "
                         f"'face use {model['id']} FACE' picks one)")
    if not got and notes is not None:
        notes.append(f"face {model['id']}: has no singing face - 'face build {model['id']} IMAGE', then 'face write'")
    for e in got:
        if known and e["face"] not in known and notes is not None:
            notes.append(f"face {model['id']}: '{e['face']}' is not one of its faces ({', '.join(known[:6])}) - "
                         f"'face use {model['id']} {known[0]}', or 'layout' again if you just added it in xLights")
    return got


def voice_track(voice: str | None, lyrics: dict | None) -> str:
    """The timing track a voice's face follows: seqtool-lyrics, or seqtool-lyrics-VOICE."""
    from ..music.voices import names
    if not voice or voice.upper() == "ALL" or not any(v.upper() == voice.upper() for v in names(lyrics)):
        return "seqtool-lyrics"
    return "seqtool-lyrics-" + re.sub(r"[^A-Za-z0-9_-]+", "_", voice)


def _sing(plans, name, model, tp, jobs, music, profile, palettes, presets, effects_cfg, lyrics, mine, song_end,
          notes):
    """Rows for a prop's singing faces (0.24.0): one per face (several faces on one matrix:
    each its own row, voice and area), on top of its other rows; not 'over': its other
    effects rest while it sings."""
    from . import reactive
    from .passes import carve, intersect, merge_spans
    entries = face_entries(tp, model, notes)
    if not entries:
        return plans
    if not (lyrics or {}).get("lines"):
        notes.append(f"face {name}: no lyrics for this song, so nothing to sing - 'lyrics transcribe'")
        return plans
    if not any(ln.get("words") for ln in lyrics["lines"]):
        notes.append(f"face {name}: the lyrics have no word times, so there are no phonemes - "
                     "'lyrics transcribe' or 'lyrics align words.txt'")
    own = [p for p in plans if p["target"] == name]
    base_layer = 1 + max([p.get("layer", 0) for p in own] + [-1])
    sung_all = []
    for k, e in enumerate(entries):
        extra = {"face": e["face"], "voice": e.get("voice"), "track": voice_track(e.get("voice"), lyrics),
                 **({"area": e["area"]} if e.get("area") else {})}
        row = None
        for sp, mode, over, why in jobs:
            if why == "pref" and "sing_over" in tp:
                over = bool(tp["sing_over"])
            rp = reactive.plan(name, mode, music, profile, palettes, layer=base_layer + k, presets=presets,
                               effects=effects_cfg["effects"], lyrics=lyrics, extra=extra)
            if sp != [(0.0, song_end)]:
                rp["segments"] = intersect(rp["segments"], sp)
            if mine:
                rp["segments"] = sorted(carve(rp["segments"], mine), key=lambda g: g["start"])
            part = {"spans": [[round(a, 3), round(b, 3)] for a, b in sp], "react": mode, "scope": why}
            if not over:
                sung_all += [(g["start"], g["end"]) for g in rp["segments"]]
            if row is None:
                row = {**rp, "pass": "face", "face": e["face"], "voice": e.get("voice"), "area": e.get("area"),
                       "mode": "over" if over else "alone", "react_parts": [part], "target_kind": model["kind"]}
            else:
                row["segments"] = sorted(row["segments"] + rp["segments"], key=lambda g: g["start"])
                row["react_parts"].append(part)
        if row and row["segments"]:
            plans.append(row)
    if sung_all:                                     # 'alone': its other rows rest while it sings
        cut = merge_spans(sung_all)
        for p in plans:
            if p["target"] == name and p.get("pass") != "face" and p.get("pass") not in ("place", "pin", "borrowed"):
                keep = [x for x in p["segments"] if x.get("pinned")]
                p["segments"] = sorted(carve([x for x in p["segments"] if not x.get("pinned")], cut) + keep,
                                       key=lambda x: x["start"])
    return plans


def config_faces() -> dict:
    from ..common import config
    try:
        return config.load("faces")
    except Exception:  # noqa: BLE001
        return {}


def group_role(g: dict, mprefs: dict) -> str:
    return group_role_why(g, mprefs)[0]


def group_role_why(g: dict, mprefs: dict) -> tuple[str, str]:
    """(role, why): set by you (or a name rule), guessed from the layout ('auto'), or
    the default for its kind. A rule may also say what kind a group is (group_kind)."""
    explicit = mprefs.get("targets", {}).get(g["id"], {})
    by = "a name rule" if "role" in explicit.get("_from_rules", []) else "you"
    if "role" in explicit:
        return canon_role(explicit["role"]), f"set by {by}"
    if explicit.get("enabled"):
        return "unit", "enabled by you"
    kind = explicit.get("group_kind") or g.get("group_kind", "leaf")
    note = f" (a name rule makes it {kind})" if explicit.get("group_kind") not in (None, g.get("group_kind")) else ""
    role = canon_role(mprefs.get("group_roles", {}).get(kind, "unused"))
    info = g.get("role_guess")
    if role == "auto":
        if info:
            from ..models.analyze import guess_role
            r, why = guess_role(kind, info)
            return r, why + note
        return {"umbrella": "top", "submodel_view": "unit"}.get(kind, "unused"), KIND_WHY.get(kind, f"{kind} group") + note
    if role == "unit" and kind == "leaf" and info and info.get("coverage", 0) >= 0.9 and not explicit.get("group_kind"):
        from ..models.analyze import guess_role
        return guess_role(kind, info)                # a flat whole-yard group: top, not one big unit
    if info and info.get("duplicate_of") and kind in ("umbrella", "leaf"):
        return "unused", f"same props as {info['duplicate_of']}"
    return role, (KIND_WHY.get(kind, f"{kind} group") if role == DEFAULT_ROLE.get(kind) else f"default for {kind} groups") + note


KIND_WHY = {"leaf": "a group of props: sequenced as one, in place of the props themselves",
            "single": "one prop: sequenced as the prop itself",
            "empty": "no props in it", "umbrella": "made of other groups",
            "submodel_view": "parts of props (submodels): sequenced as one, in place of the props themselves"}
DEFAULT_ROLE = {"leaf": "unit", "single": "unused", "empty": "unused"}


def target_transitions(windows, effects: list[dict], ccfg: dict) -> tuple[list[float], list[float]]:
    """Per-target transition strengths: the section-based strength, combined with how
    much the music itself changes in the characteristics this target's effects care about.

    importance of a characteristic = how differently the target's candidate effects
    respond to it (spread of their ideal levels). The change between neighbouring
    windows is the importance-weighted difference of their features, divided by
    this song's own large changes (contrast_reference percentile), so the biggest
    musical changes in the song make changing effect nearly free."""
    import numpy as np
    base = [w.transition_strength for w in windows]
    relief = ccfg.get("contrast_relief", 1.0)
    if relief <= 0 or len(windows) < 3 or not effects:
        return base, [0.0] * len(windows)
    feats = sorted({k for e in effects for k in e.get("music_fit", {})})
    imp = {f: float(np.std([e["music_fit"].get(f, 0.5) for e in effects])) for f in feats}
    tot = sum(imp.values()) or 1.0
    d = [0.0]
    for a, b in zip(windows[:-1], windows[1:]):
        d.append(sum(imp[f] * abs(b.features.get(f, 0.5) - a.features.get(f, 0.5)) for f in feats) / tot)
    ref = float(np.quantile(d[1:], ccfg.get("contrast_reference", 0.9))) or 1e-9
    contrast = [min(1.0, x / ref) for x in d]
    # independent evidence for "this is a good place to change" reinforces: 1-(1-a)(1-b)
    return [1 - (1 - t) * (1 - relief * c) if i else t for i, (t, c) in enumerate(zip(base, contrast))], contrast


def select_targets(models: dict, mprefs: dict) -> tuple[list[dict], list[dict]]:
    """Return (targets, skipped[{id, reason}]).

    Groups are chosen by kind (preferences group_targets; a target entry with
    "enabled": true forces one on), largest first, never overlapping an already
    chosen group, so no pixel is driven by two plans. Everything left over is
    planned per model."""
    entries = models["models"]
    roles = mprefs.get("group_roles", {"leaf": "unit"})
    skipped: list[dict] = []
    usable: dict[str, dict] = {}
    for m in entries:
        if m["kind"] != "model":                      # groups below; submodels: detail pass
            continue
        tp = _target_prefs(m["id"], mprefs)
        if not tp.get("enabled", True):
            skipped.append({"id": m["id"], "reason": "disabled by preference"})
        elif not m["supported_for_generation"]:
            skipped.append({"id": m["id"], "reason": m.get("unsupported_reason", "unsupported")})
        else:
            usable[m["id"]] = m
    cands = []
    for g in entries:
        if g["kind"] != "group":
            continue
        explicit = mprefs.get("targets", {}).get(g["id"], {})
        kind = g.get("group_kind", "leaf")
        role = group_role(g, mprefs)
        mem = [x for x in dict.fromkeys(g.get("members", [])) if x in usable]
        if explicit.get("enabled") is False or role == "unused":
            skipped.append({"id": g["id"], "reason": f"{kind} group, role unused" if role == "unused"
                            else "disabled by preference"})
        elif role in ("top", "detail"):
            skipped.append({"id": g["id"], "reason": f"{kind} group, role '{role}': for the "
                            f"{'top' if role == 'top' else 'detail'} pass (off in scoring.passes, or not used)"})
        elif not g["supported_for_generation"]:
            skipped.append({"id": g["id"], "reason": g.get("unsupported_reason", "unsupported")})
        elif len(mem) < 2:
            skipped.append({"id": g["id"], "reason": "fewer than 2 usable members"})
        else:
            cands.append((g, mem, bool(explicit.get("enabled"))))
    cands.sort(key=lambda c: (not c[2], -len(c[1]), c[0]["id"]))     # forced first, then largest
    covered: dict[str, str] = {}
    targets = []
    for g, mem, _ in cands:
        clash = sorted({covered[x] for x in mem if x in covered})
        if clash:
            skipped.append({"id": g["id"], "reason": f"overlaps group {clash[0]}"})
            continue
        targets.append(g)
        for x in mem:
            covered[x] = g["id"]
    # props no unit group covers (0.20.7, the user's report: floods, spinners, sheep each
    # sequenced on their own although groups held them): the closest umbrella group whose
    # props are all loose plays as one, in place of them - not the whole-yard group
    unit_why: dict[str, str] = {}
    whole = [g for g in entries if g["kind"] == "group" and group_role(g, mprefs) == "top"]
    whole.sort(key=lambda g: (-(g.get("role_guess") or {}).get("coverage", 0), -len(g.get("members", []))))
    widest = whole[0]["id"] if whole else None                  # the top pass's group
    if mprefs.get("loose_props_to_umbrella", True):
        loose = []
        for g in entries:
            if g["kind"] != "group" or g["id"] == widest or not g.get("supported_for_generation"):
                continue
            explicit = mprefs.get("targets", {}).get(g["id"], {})
            if explicit.get("enabled") is False or "role" in explicit or group_role(g, mprefs) != "top" \
                    or (g.get("role_guess") or {}).get("coverage", 0) >= 0.9:
                continue
            mem = [x for x in dict.fromkeys(g.get("members", [])) if x in usable]
            if len(mem) >= 2:
                loose.append((g, mem))
        loose.sort(key=lambda c: (len(c[1]), c[0]["id"]))       # the closest (smallest) first
        for g, mem in loose:
            if any(x in covered for x in mem):
                continue
            targets.append(g)
            unit_why[g["id"]] = (f"its {len(mem)} props are in no unit group, so this umbrella group plays as one in "
                                 "place of them (models.json loose_props_to_umbrella)")
            for x in mem:
                covered[x] = g["id"]
            skipped[:] = [s for s in skipped if s["id"] != g["id"]]
    drive_all = mprefs.get("drive_members_of_enabled_groups", False)
    sk_by = {}
    for s in skipped:
        sk_by.setdefault(s["id"], s["reason"])
    for mid, m in usable.items():
        if mid in covered and not drive_all and \
                not _target_prefs(mid, mprefs).get("drive_individually", False):
            skipped.append({"id": mid, "reason": f"driven via group {covered[mid]}"})
        else:
            targets.append(m)
            if mid in covered:
                unit_why[mid] = (f"sequenced on its own as well as in {covered[mid]} "
                                 "(drive_individually / drive_members_of_enabled_groups)")
            else:
                unit_why[mid] = alone_why(entries, mid, mprefs, sk_by, covered, widest)
    targets = [{**t, "_alone": unit_why[t["id"]]} if unit_why.get(t["id"]) else t for t in targets]
    order = {m["id"]: i for i, m in enumerate(entries)}
    targets.sort(key=lambda t: order[t["id"]])
    return targets, skipped


def alone_why(entries: list[dict], mid: str, mprefs: dict, sk_by: dict, covered: dict | None = None,
              widest: str | None = None) -> str:
    """Why a prop is sequenced on its own rather than through a group (0.20.7): its groups,
    closest first, and why none of them carries it."""
    from ..models.analyze import containing_groups
    gs = containing_groups(entries, mid)
    if not gs:
        return ""                                   # in no group: nothing to explain
    covered = covered or {}
    parts = []
    for g, d, _ in gs[:4]:
        role = group_role(g, mprefs)
        mem = list(dict.fromkeys(g.get("members", [])))
        taken = sorted({covered[x] for x in mem if x in covered})
        sk = sk_by.get(g["id"], "")
        if g["id"] == widest:
            why = "the whole-yard group: top pass only"
        elif sk.startswith("overlaps group"):
            why = sk.replace("overlaps group", "overlaps unit group")
        elif sk.startswith("fewer than 2"):
            why = "fewer than 2 sequenced props in it"
        elif role == "top" and taken:
            why = f"top pass only; some of its props are already in {taken[0]}"
        elif role == "top":
            why = "top pass only"
        elif role == "detail":
            why = "accents only (detail pass)"
        elif role == "unused":
            why = "one prop: the prop itself" if g.get("group_kind") == "single" else "role unused"
        else:
            why = sk or f"role {role}"
        parts.append(f"{g['id']} ({why})")
    more = f" and {len(gs) - 4} more" if len(gs) > 4 else ""
    first = next((g["id"] for g, _, _ in gs if g.get("group_kind") != "single"), gs[0][0]["id"])
    return ("sequenced on its own - no group carries it in the main pass: " + "; ".join(parts) + more
            + f". 'groups {first}' shows that group; 'pref models/targets/{first}/role = unit' sequences it as one")


def _reasons(eff_id: str, avg: dict, w0, cont: dict | None) -> list[str]:
    r = []
    labels = {"model_fit": "suits this prop type", "capability_fit": "geometry supports it",
              "music_fit": "matches the music here", "style_fit": "fits the song style",
              "section_fit": f"fits a {w0.section_type or 'unlabeled'} section"}
    top = sorted(labels, key=lambda k: -avg[k])[:2]
    r += [labels[k] for k in top]
    f = w0.features
    if f.get("energy", 0) > 0.7:
        r.append("high energy")
    elif f.get("energy", 1) < 0.3:
        r.append("low energy")
    if f.get("beat", 0) > 0.7:
        r.append("strong beat")
    if cont:
        if cont["previous_effect"] == eff_id:
            r.append("continues previous effect")
        elif cont["transition_strength"] >= 0.6:
            r.append("strong musical transition permits change")
    return r


def plan_target(target: dict, tprefs: dict, windows, effects_cfg: dict, styles: dict,
                scfg: dict, seed: int, top_n: int, layer: int = 0,
                seed_overrides: dict | None = None, adjust=None, pin_pass: str = "main") -> tuple[dict, list[dict]]:
    from ..common.songs import effective_seed
    so = seed_overrides or {}
    wseed = lambda w: effective_seed(seed, so, target["id"], w.section_repeat_key)  # noqa: E731
    effs = effects_cfg["effects"]
    order = list(effs)
    allowed, excluded = [], []
    for e in order:
        why = scoring.gate(e, effs[e], target, tprefs)
        if why is None and layer not in effs[e].get("layers", [0, 1]):
            why = f"not used on layer {layer}"
        (excluded.append({"effect": e, "reason": why}) if why else allowed.append(e))
    # pins (seqtool pin): window index -> effect, forced whatever the scores say
    pins = dict((tprefs.get("_pins") or {}).get(pin_pass, {}))
    pin_params = (tprefs.get("_pin_params") or {}).get(pin_pass, {})
    for t_, e in list(pins.items()):
        if e not in allowed:
            why = next((x["reason"] for x in excluded if x["effect"] == e), "unknown effect")
            excluded.append({"effect": e, "reason": f"pinned, but not possible here: {why}"})
            del pins[t_]
    # effects that are never chosen automatically (dark): only where pinned
    manual = {e for e in allowed if effs[e].get("auto", True) is False}
    for e in sorted(manual - set(pins.values())):
        allowed.remove(e)
        excluded.append({"effect": e, "reason": "only used where you pin it ('pin')"})
    if not allowed:
        return {"target": target["id"], "target_kind": target["kind"], "layer": layer,
                "segments": []}, excluded

    comps = [{e: scoring.score(e, effs[e], target, tprefs, w, styles, scfg, wseed(w)) for e in allowed}
             for w in windows]
    static = [{e: c[e].static for e in allowed} for c in comps]
    if adjust is not None:                     # later passes: complement / rest multipliers per window
        static = [{e: v * adjust(w, e) for e, v in row.items()} for row, w in zip(static, windows)]
    fi = scfg.get("feel_intensity")
    if fi:                                     # 0.24.30: 'feel intensity' - calm or intense effects win
        from .feel import intensity_factor
        static = [{e: v * intensity_factor(fi, w, effs[e]) for e, v in row.items()} for row, w in zip(static, windows)]
    # motif consistency: repeated sections share emissions position-by-position,
    # so chorus 2 tends to look like chorus 1 (continuity can still differ)
    pos: dict[tuple[str, int], list[int]] = {}
    k = 0
    for t, w in enumerate(windows):
        k = 0 if w.is_section_start else k + 1
        pos.setdefault((w.section_repeat_key, k), []).append(t)
    for idxs in pos.values():
        if len(idxs) > 1:
            avg = {e: sum(static[t][e] for t in idxs) / len(idxs) for e in allowed}
            for t in idxs:
                static[t] = dict(avg)
    static0 = [dict(row) for row in static]   # real scores, for the explanation and the alternatives
    for t in range(len(windows)):
        forced = pins.get(t)
        if forced is not None:
            static[t] = {e: v if e == forced else v - 10.0 for e, v in static[t].items()}
        elif manual:
            static[t] = {e: v - 10.0 if e in manual else v for e, v in static[t].items()}
    fam = {e: effs[e]["family"] for e in allowed}
    inertia = {e: effs[e].get("inertia", 0.7) for e in allowed}
    ts, contrast = target_transitions(windows, [effs[e] for e in allowed if lit(e)], scfg["continuity"])
    ccfg = dict(scfg["continuity"])
    ccfg["change_penalty"] *= tprefs.get("change_penalty_scale", 1.0)
    path = viterbi(static, allowed, fam, inertia, ts, ccfg)
    # second pass: repeated sections get a bonus for the effect their first
    # occurrence used at the same position -> recurring visual motifs
    bonus = ccfg.get("motif_bonus", 0.0)
    if bonus:
        first: dict[tuple[str, int], str] = {}
        k = 0
        motif = []
        for t, w in enumerate(windows):
            k = 0 if w.is_section_start else k + 1
            key = (w.section_repeat_key, k)
            if key in first and w.section_repeat_key != w.section_id:
                motif.append((t, first[key]))
            first.setdefault(key, path[t])
        if motif:
            for t, e in motif:
                static[t] = {**static[t], e: static[t][e] + bonus}
            path = viterbi(static, allowed, fam, inertia, ts, ccfg)

    # merge consecutive windows into segments; always split at section starts
    groups: list[list[int]] = []
    for t, e in enumerate(path):
        if groups and path[groups[-1][-1]] == e and not windows[t].is_section_start:
            groups[-1].append(t)
        else:
            groups.append([t])

    segments, prev_eff, prev_start = [], None, 0.0
    for g in groups:
        eff_id = path[g[0]]
        ws = [windows[t] for t in g]
        w0 = ws[0]
        n = len(g)
        avg = {k: sum(getattr(comps[t][eff_id], k) for t in g) / n for k in COMPONENT_KEYS}
        avg_static = sum(static0[t][eff_id] for t in g) / n
        pinned = all(pins.get(t) == eff_id for t in g)
        feats = {}
        for k in ws[0].features:
            feats[k] = sum(w.features.get(k, 0) * w.duration for w in ws) / sum(w.duration for w in ws)
        cont = None
        cont_val = 0.0
        if prev_eff is not None:
            cont_val = transition_value(prev_eff, eff_id, fam, inertia, ts[g[0]], ccfg)
            t0 = g[0]
            why = []
            if w0.is_section_start:
                why.append(f"section change {w0.transition_strength:.2f}")
            if contrast[t0] > 0.05:
                why.append(f"music contrast {contrast[t0]:.2f}")
            cont = {"previous_effect": prev_eff, "previous_family": fam[prev_eff],
                    "effect_age": round(w0.start - prev_start, 3),
                    "change_penalty": round(max(0.0, -cont_val), 4),
                    "transition_strength": round(ts[t0], 4), "why": ", ".join(why)}
        alts = sorted(((e, sum(static0[t][e] for t in g) / n) for e in allowed if e != eff_id),
                      key=lambda x: (-x[1], order.index(x[0])))[:top_n]
        seg = {
            "start": w0.start, "end": ws[-1].end, "section": w0.section_id,
            "section_index": w0.section_index,
            "selected": {"effect": eff_id, "family": fam[eff_id], "score": avg_static},
            "parameters": parameters(eff_id, effs[eff_id], feats, target["id"],
                                     w0.section_repeat_key, wseed(w0), target.get("geometry_class")),
            "palette": "accent" if feats.get("energy", 0) >= 0.75 else "base",
            "score_breakdown": {**avg, "static": avg_static, "continuity": cont_val,
                                "final": avg_static + cont_val},
            "alternatives": [{"effect": e, "score": s} for e, s in alts],
            "reasons": (["pinned by you"] if pinned else []) + _reasons(eff_id, avg, w0, cont),
        }
        rstyle = scoring.render_fit(effs[eff_id], target, tprefs)[1]
        if rstyle is not None and lit(eff_id):        # 0.24.36: a group's effect as one picture or per prop
            seg["parameters"]["render"] = rstyle
            if rstyle == "per_model":
                seg["reasons"].append("drawn on each of the group's props (render per model)")
        if pinned:
            seg["pinned"] = True
            mine = pin_params.get(g[0])
            if mine:                                   # 0.24.36: the settings you gave the pin
                seg["parameters"].update({k: v for k, v in mine.items() if k in seg["parameters"] or k in
                                          effs[eff_id].get("parameters", {}) or k in ("render", "area", "rotation")})
                seg["reasons"].insert(1, "settings yours: " + ", ".join(f"{k}={v}" for k, v in mine.items()))
                seg["yours"] = sorted(mine)
        if cont:
            seg["continuity"] = cont
        if not lit(eff_id):
            seg.pop("palette")
        segments.append(seg)
        if prev_eff != eff_id:
            prev_start = w0.start
        prev_eff = eff_id
    trims = (tprefs.get("_pin_trim") or {}).get(pin_pass)
    if trims:
        segments = trim_pinned(segments, trims)
    _glides_over(segments)
    return {"target": target["id"], "target_kind": target["kind"], "layer": layer,
            "segments": segments}, excluded


def _glides_over(segments: list[dict]) -> None:
    """0.24.48: a pinned setting that glides ('speed=0.2..0.9') glides over the pin's whole run of
    segments (one after another, the same effect), not again in each - 'over' holds that span, so
    later cuts (durations, reactions) keep their share of it."""
    run: list[dict] = []

    def close():
        if run:
            a, b = run[0]["start"], run[-1]["end"]
            for g in run:
                for k, v in list(g["parameters"].items()):
                    if isinstance(v, dict) and ("ramp" in v or "curve" in v) and "over" not in v:
                        g["parameters"][k] = {**v, "over": [round(a, 3), round(b, 3)]}
        run.clear()
    for g in segments:
        glide = g.get("pinned") and any(isinstance(v, dict) and ("ramp" in v or "curve" in v)
                                        for v in g.get("parameters", {}).values())
        if glide and run and (abs(run[-1]["end"] - g["start"]) > 1e-3
                              or run[-1]["selected"]["effect"] != g["selected"]["effect"]):
            close()
        if glide:
            run.append(g)
        else:
            close()
    close()


def trim_pinned(segments: list[dict], trims: list) -> list[dict]:
    """0.24.37: a pin's onset / offset - in each section [s0, s1] its effect plays [a, b] only;
    the pinned segments are cut there (as the exporter cuts glides into steps) and the parts
    outside are 'transparent': nothing from this pin, what is underneath shows."""
    out = []
    for g in segments:
        pieces = [g]
        if g.get("pinned"):
            for s0, s1, a, b, how in trims:
                nxt = []
                for p in pieces:
                    cuts = sorted({x for x in (s0, a, b, s1) if p["start"] + 1e-6 < x < p["end"] - 1e-6})
                    bounds = [p["start"], *cuts, p["end"]]
                    for lo, hi in zip(bounds, bounds[1:]):
                        q = {**p, "start": round(lo, 3), "end": round(hi, 3)}
                        mid = (lo + hi) / 2
                        if s0 <= mid < s1 and not (a <= mid < b):
                            q = {**q, "selected": {"effect": "transparent", "family": "none", "score": 0.0},
                                 "parameters": {}, "reasons": [f"your pin's {how}: nothing from it here "
                                                               "(what is underneath shows)"]}
                            q.pop("pinned", None)
                            q.pop("palette", None)
                            q.pop("yours", None)
                        elif s0 <= mid < s1:
                            q = {**q, "reasons": list(q.get("reasons", [])) +
                                 [f"plays {a - s0:.2f}-{b - s0:.2f} s into its section ({how})"]}
                        nxt.append(q)
                pieces = nxt
        out.extend(pieces)
    return out


def run(music: dict, profile: dict, models: dict, prefs: dict, seed: int,
        source_names: dict | None = None, feedback: dict | None = None,
        pass_no: int = 1, seed_overrides: dict | None = None, lyrics: dict | None = None,
        available: set | None = None, pins: list | None = None, borrowed: dict | None = None,
        reacts: list | None = None, cues: list | None = None, palette: dict | None = None,
        adjust: list | None = None,
        feel: dict | None = None) -> dict:
    """All passes: main (layer 0), then top, detail and enhance (passes.py), then
    music-reactive targets. pass_no is kept for compatibility (1 = everything)."""
    for doc, name in ((music, "seqtool.music"), (profile, "seqtool.music-profile"), (models, "seqtool.models")):
        check_version(doc, name)
        validate(doc, name)
    from ..common.freshness import check_inputs, consistency
    check_inputs("match", music=(music, None), music_profile=(profile, None), models=(models, None))
    consistency(profile, "music", music, "match")
    prefs_sha = content_sha256(prefs)
    from . import rules as name_rules
    prefs = {**prefs, "models": name_rules.expand(prefs["models"], models)}
    effects_cfg, scfg = prefs["effects"], prefs["scoring"]
    if available is not None:                  # what the output can draw (e.g. effects the xLights kit learned)
        effects_cfg = {**effects_cfg, "effects": {k: v for k, v in effects_cfg["effects"].items()
                                                  if k in available or not lit(k)}}
    if feel:                                   # 0.24.30: the song's creative controls
        from .feel import apply_scoring, intensity_map, with_warmth
        scfg = apply_scoring(scfg, feel)
        prefs = {**prefs, "scoring": scfg}
        palette = with_warmth(palette, feel)
    windows = build_windows(music, profile, scfg["decision"], scfg["continuity"])
    if feel:
        fi = intensity_map(feel, profile, windows)
        if fi:
            scfg = {**scfg, "feel_intensity": fi}
            prefs = {**prefs, "scoring": scfg}
    pin_notes, face_notes = [], []
    if pins:
        from .pins import apply_pins
        prefs = {**prefs, "models": apply_pins(prefs["models"], pins, windows, profile, pin_notes)}
    styles = profile["profile"]["styles"]
    targets, skipped = select_targets(models, prefs["models"])
    palettes, _, _ = build_palettes(styles, prefs["palettes"], seed, palette)

    plans, exclusions = [], {}
    for t in targets:
        plan, excl = plan_target(t, _target_prefs(t["id"], prefs["models"], feedback), windows,
                                 effects_cfg, styles, scfg, seed, scfg.get("top_alternatives", 3),
                                 seed_overrides=seed_overrides)
        hits = prefs["models"].get("targets", {}).get(t["id"], {}).get("_rules")
        if hits:
            plan["rules"] = hits
        if t.get("_alone"):
            plan["why_target"] = t["_alone"]          # why this prop or group, not another (0.20.7)
        plans.append(plan)
        if excl:
            exclusions[t["id"]] = excl

    names = source_names or {}

    # later passes (DESIGN.md section 9): top-down sections, detail (submodels), enhancement layer
    from . import passes
    pcfg = scfg.get("passes", {})
    mp = prefs["models"]
    args = (models, mp, windows, effects_cfg, styles, scfg, seed, seed_overrides)
    if pcfg.get("top", {}).get("enabled", True):
        plans = passes.top_pass(plans, *args, pcfg.get("top", {}), profile, skipped, exclusions)
    if pcfg.get("detail", {}).get("enabled", True):
        plans = passes.detail_pass(plans, *args, pcfg.get("detail", {}), skipped, exclusions)
    if pcfg.get("enhance", {}).get("enabled", True):
        plans = passes.enhance_pass(plans, *args, pcfg.get("enhance", {}), exclusions)
    plans = passes.apply_rests(plans, models)
    from . import base, durations                      # 0.20: duration limits, then whole-yard moments
    pass_notes: list[str] = []
    durations.apply(plans, music, profile, effects_cfg, palettes, scfg, pass_notes)
    plans, moments = base.base_pass(plans, models, mp, music, profile, windows, effects_cfg,
                                    pcfg.get("base", {}), seed, pass_notes)
    plans = passes.pin_rows(plans, *args, skipped, exclusions, pin_notes)
    plans = passes.place_rows(plans, *args, pin_notes, exclusions)   # promote / demote (0.21)
    if lyrics is None:
        from ..music.lyrics import for_music
        lyrics = for_music(music)

    def ref(doc, key):
        r = {"schema": doc["schema"], "schema_version": doc["schema_version"],
             "content_sha256": content_sha256(doc)}
        if key in names:
            r["filename"] = names[key]
        return r

    # music-reactive targets: event-synced plans replace (or with react_over, sit on top of) normal ones.
    # 0.21.4: also per song (songs.json 'react': this song only) and per section (with its repeats)
    from . import reactive
    from .passes import carve, intersect, merge_spans, span_minus
    by_id = {m["id"]: m for m in models["models"]}
    presets = reactive.load_presets(prefs.get("presets"))
    song_end = profile["sections"][-1]["end"] if profile["sections"] else music["audio"]["duration"]
    sec_ids = {x["id"]: x for x in profile["sections"]}

    def root(x):
        while x.get("repeat_of") in sec_ids:
            x = sec_ids[x["repeat_of"]]
        return x["id"]

    def spans_of(e):
        if e.get("at") is None:
            return [(0.0, song_end)]
        from .pins import _section_at
        own = _section_at(profile, float(e["at"]))
        return merge_spans([(x["start"], x["end"]) for x in profile["sections"] if x is own or
                            (e.get("repeats", True) and root(x) == root(own))])
    want: dict[str, list] = {}                       # target -> [(spans, mode, over, why)] later ones win
    for name, tp in sorted(prefs["models"].get("targets", {}).items()):
        if tp.get("react"):
            want.setdefault(name, []).append(([(0.0, song_end)], tp["react"], bool(tp.get("react_over")), "pref"))
        elif tp.get("face") not in (None, "off", "none") and "sing" not in tp:
            # set with 'face use' before 0.24.0: the whole song, as then
            want.setdefault(name, []).append(([(0.0, song_end)], "sing", tp.get("face_mode") == "over", "pref"))
    for e in reacts or []:
        want.setdefault(e["target"], []).append((spans_of(e), e.get("preset", "off"), bool(e.get("over")),
                                                 "song" if e.get("at") is None else "section"))
    for name, parts in sorted(want.items()):
        res = []                                     # spans each setting finally has
        for k, (sp, mode, over, why) in enumerate(parts):
            later = merge_spans([x for q in parts[k + 1:] for x in q[0]])
            left = span_minus(sp, later) if later else sp
            if left:
                res.append((left, mode, over, why))
        res = [r for r in res if r[1] and r[1] != "off"]
        if not res:
            continue
        m_ = by_id.get(name)
        if m_ is None or not m_.get("supported_for_generation"):
            skipped.append({"id": name, "reason": f"react '{res[0][1]}': not a usable model or group"})
            continue
        tp = prefs["models"].get("targets", {}).get(name, {})
        mine = merge_spans([(g["start"], g["end"]) for p in plans if p["target"] == name
                            and p.get("pass") in ("place", "pin", "face", "borrowed") for g in p["segments"]])
        existing = [p for p in plans if p["target"] == name and not p.get("react")
                    and p.get("pass") not in ("place", "pin", "face", "borrowed")]   # 0.21.5: your choices stay
        top_layer = max((p.get("layer", 0) for p in existing), default=0)
        merged: dict[bool, dict] = {}                # one react row per layer: parts merged in time order
        sing_jobs = []                               # 0.24.0: singing faces, done after the rest
        for sp, mode, over, why in res:
            nm = reactive.names_of(mode)
            sung = [n for n in nm if (reactive.get_preset(presets, n) or {}).get("on") == "sung"]
            if sung:
                sing_jobs.append((sp, ",".join(sung), over, why))
                if len(sung) == len(nm):
                    continue
                mode = ",".join(n for n in nm if n not in sung)
            bad = reactive.check(mode, presets, effects_cfg["effects"])
            if bad:
                exclusions.setdefault(name, []).append({"effect": "react", "reason": "; ".join(bad)})
                continue
            rplan = reactive.plan(name, mode, music, profile, palettes, layer=(top_layer + 1) if over and existing else 0,
                                  presets=presets, effects=effects_cfg["effects"], lyrics=lyrics,
                                  cues=[c for c in cues or [] if not c.get("tag")     # 0.24.49: call/response marks
                                        and (not c.get("for") or name in c["for"])])
            whole = sp == [(0.0, song_end)]
            if not whole:
                rplan["segments"] = intersect(rplan["segments"], sp)
            if mine:                                 # placed / pinned / face / borrowed effects win over reactions
                rplan["segments"] = sorted(carve(rplan["segments"], mine), key=lambda g: g["start"])
            if not over:                             # the normal effects give way there
                for p in existing:
                    p["segments"] = sorted(carve(p["segments"], sp), key=lambda g: g["start"])
                if whole:
                    plans = [p for p in plans if not (p["target"] == name and not p.get("react")
                                                      and p.get("pass") not in ("place", "pin", "face", "borrowed"))]
            part = {"spans": [[round(a, 3), round(b, 3)] for a, b in sp], "react": rplan["react"], "scope": why}
            if over in merged:
                q = merged[over]
                q["segments"] = sorted(q["segments"] + rplan["segments"], key=lambda g: g["start"])
                q["react_parts"].append(part)
                q["react"] = ",".join(dict.fromkeys(q["react"].split(",") + rplan["react"].split(",")))
            else:
                rplan["react_parts"] = [part]
                if tp.get("_rules") and why == "pref":
                    rplan["rules"] = tp["_rules"]
                rplan["target_kind"] = m_["kind"]
                merged[over] = rplan
                plans.append(rplan)
        if sing_jobs:
            plans = _sing(plans, name, m_, tp, sing_jobs, music, profile, palettes, presets, effects_cfg, lyrics,
                          mine, song_end, face_notes)
        skipped = [x for x in skipped if x["id"] != name]
    from . import choreo as _choreo                      # 0.24.47: choreographies -> the parts they play
    plans = _choreo.expand(plans, models, music, profile, palettes, effects_cfg["effects"], lyrics, cues, pin_notes,
                           presets)
    if adjust is None and (music.get("lineage") or {}).get("audio"):     # 0.24.57: settings over what plays
        from ..common import songs as _songs
        adjust = _songs.get(music["lineage"]["audio"]).get("adjust")
    if adjust:
        from . import adjust_cmd
        plans = adjust_cmd.apply(plans, adjust, profile, song_end, pin_notes)
    # a pin that ended up nowhere is said, not silently dropped
    for tid, tp in sorted(prefs["models"].get("targets", {}).items()):
        for ps, slot in (tp.get("_pins") or {}).items():
            if not slot:
                continue
            hit = any(p["target"] == tid and p.get("pass", "main") == ps and not p.get("react")
                      and any(g.get("pinned") for g in p["segments"]) for p in plans)
            if not hit and not any(x["reason"].startswith("pinned, but") for x in exclusions.get(tid, [])):
                why = next((s_["reason"] for s_ in skipped if s_["id"] == tid), f"nothing is planned for it in the {ps} pass")
                nm = tid + (f" ({ps})" if ps != "main" else "")
                nq = f'"{nm}"' if re.search(r"[\s\"'#]", nm) else nm
                pin_notes.append(f"pin {nm} not used: {why} - 'pin' lists your pins, 'unpin {nq}' removes them")
    if borrowed is None and (music.get("lineage") or {}).get("audio"):
        from ..common import songs as _songs
        borrowed = _songs.get(music["lineage"]["audio"]).get("borrowed")
    from . import borrow as _borrow                      # effects kept from an existing .xsq (0.20.4)
    if (borrowed or {}).get("only"):                     # 0.21.7: an .xsq opened as it is - no effects of
        for p in plans:                                  # seqtool's own, only what you pin, place or make react
            if not p.get("react") and p.get("pass") not in ("place", "face"):
                p["segments"] = [g for g in p["segments"] if g.get("pinned")]
        plans = [p for p in plans if p["segments"] or p.get("react")]
        pass_notes.append("the opened .xsq as it is: seqtool adds only what you pin, place or make react "
                          "('open-xsq --fill' lets it plan the rest)")
    plans = _borrow.apply(plans, models, borrowed, pass_notes)
    from ..common.envelope import merge_lineage
    lineage = merge_lineage(music, profile, models, extra={"preferences": prefs_sha})
    src = {"music": ref(music, "music"), "music_profile": ref(profile, "music_profile"),
           "models": ref(models, "models"), "preferences_sha256": prefs_sha}
    if feedback:
        src["feedback_sha256"] = content_sha256(feedback)
    if lyrics:
        src["lyrics_sha256"] = content_sha256(lyrics)
    if available is not None:
        src["available_effects"] = sorted(available)
    if (borrowed or {}).get("items"):
        src["borrowed_sha256"] = content_sha256(borrowed)
    out = envelope("seqtool.matchup", "seqtool-match", src, lineage)
    out["settings"] = {"seed": seed, "seed_overrides": dict(seed_overrides or {}), "pins": list(pins or []),
                       "cues": list(cues or []),
                       "pass": pass_no, "decision": scfg["decision"],
                       "weights": scfg["weights"], "random_amplitude": scfg["random_amplitude"],
                       "window_count": len(windows),
                       "beat_s": round(60.0 / (music["analysis"]["summary"].get("tempo", {}).get("bpm") or 120.0), 4),
                       "durations": {k: v for k, v in (scfg.get("durations") or durations.DEFAULTS).items() if not k.startswith("_")},
                       "iteration": (feedback or {}).get("iteration", 0) + (1 if feedback else 0)}
    if feedback:
        out["settings"]["applied_feedback"] = feedback   # validator merges new feedback into this
    out["palettes"] = palettes
    out["plans"] = plans
    out["moments"] = moments
    out["diagnostics"] = {"skipped_targets": skipped, "excluded_effects": exclusions}
    if pass_notes:
        out["diagnostics"]["passes"] = pass_notes
    if pin_notes:
        out["diagnostics"]["pins"] = pin_notes
    if face_notes:
        out["diagnostics"]["faces"] = face_notes
    validate(out, "seqtool.matchup")
    return out
