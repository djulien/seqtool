"""Planning passes after the main one (DESIGN.md section 9).

    main     unit groups and standalone props, layer 0 (engine.plan_target)
    top      role 'top' groups (e.g. an ALL group) take over whole sections
             (scoring.passes.top.sections, e.g. intro/outro): the yard moves as one,
             and the members' own effects are cut out of those sections
    detail   role 'detail' groups (e.g. a group of spokes or rings - submodels) and
             submodels you enabled, planned on top of their parents: accent
             effects only, preferring a different family from what the parent
             shows at that moment, resting ('transparent') when there is nothing to add
    enhance  layer 2 on focal props (the largest standalone props, or those you
             mark with enhance: true): sparse accents in loud passages only

Each pass is switched and tuned in scoring.json "passes".
"""
from __future__ import annotations

from ..common.vocab import canon, lit
from .engine import _target_prefs, group_role, plan_target


def _accent_cfg(effects_cfg: dict) -> dict:
    """effects allowed on layer >= 1, plus 'transparent' (a layer above may rest) and 'dark'."""
    effs = effects_cfg["effects"]
    keep = {k: v for k, v in effs.items() if 1 in v.get("layers", [0]) or not lit(k)}
    for k in [k for k in keep if not lit(k)]:
        keep[k] = {**keep[k], "layers": sorted(set(keep[k].get("layers", [0])) | {1})}
    return {**effects_cfg, "effects": keep}


def _reason(skipped: list[dict], tid: str, reason: str | None) -> None:
    """Replace a target's skip reason (None = it is planned after all)."""
    skipped[:] = [s for s in skipped if s["id"] != tid]
    if reason:
        skipped.append({"id": tid, "reason": reason})


def _family_at(plans: list[dict], t: float) -> str | None:
    for p in plans:
        for g in p["segments"]:
            if g["start"] <= t < g["end"]:
                return g["selected"].get("family")
    return None


def carve(segments: list[dict], spans: list[tuple[float, float]]) -> list[dict]:
    """Remove the parts of segments that fall inside spans (segments are cut, never moved)."""
    out = []
    for g in segments:
        pieces = [(g["start"], g["end"])]
        for a, b in spans:
            nxt = []
            for s, e in pieces:
                if e <= a or s >= b:
                    nxt.append((s, e))
                    continue
                if s < a:
                    nxt.append((s, a))
                if e > b:
                    nxt.append((b, e))
            pieces = nxt
        for s, e in pieces:
            if e - s >= 0.05:
                out.append({**g, "start": round(s, 3), "end": round(e, 3)})
    return out


def intersect(segments: list[dict], spans: list[tuple[float, float]]) -> list[dict]:
    """Keep only the parts of segments inside spans."""
    out = []
    for g in segments:
        for a, b in spans:
            s, e = max(g["start"], a), min(g["end"], b)
            if e - s >= 0.05:
                out.append({**g, "start": round(s, 3), "end": round(e, 3)})
    return out


def _models_under(m: dict, by_id: dict) -> set[str]:
    """Physical models a target drives (parents for submodels and groups of submodels)."""
    if m["kind"] == "submodel":
        return {m.get("parent", m["id"].split("/", 1)[0])}
    if m["kind"] == "group":
        out = set()
        for x in m.get("detail_members") or m.get("members", []):
            out.add(x.split("/", 1)[0])
        return out
    return {m["id"]}


def top_pass(plans, models, mprefs, windows, effects_cfg, styles, scfg, seed, seed_overrides, cfg, profile,
             skipped, exclusions):
    by_id = {m["id"]: m for m in models["models"]}
    want = set(cfg.get("sections", ["intro", "outro"]))
    spans = [(s["start"], s["end"]) for s in profile["sections"] if s.get("type") in want]
    tops = [m for m in models["models"] if m["kind"] == "group" and m.get("supported_for_generation")
            and group_role(m, mprefs) == "top" and _target_prefs(m["id"], mprefs).get("enabled", True)]
    lvl = lambda g: (g.get("role_guess") or {}).get("level")                       # noqa: E731
    tops.sort(key=lambda g: (-(g.get("role_guess") or {}).get("coverage", 0), lvl(g) if lvl(g) is not None else 999,
                             -len(g.get("members", [])), g["id"]))
    chosen, covered = [], set()
    as_unit = {p["target"] for p in plans if p.get("pass", "main") == "main"}
    for g in tops:
        mem = set(g.get("members", []))
        if g["id"] in as_unit:                        # 0.20.7: already plays as one for its loose props
            _reason(skipped, g["id"], "top pass: plays as a unit in the main pass (loose_props_to_umbrella)")
            continue
        if mem & covered:
            _reason(skipped, g["id"], f"top pass: overlaps top group {chosen[-1]['id']} (one at a time)")
            continue
        if len(chosen) >= int(cfg.get("max_groups", 1)):
            _reason(skipped, g["id"], f"top pass: overlaps top group {chosen[-1]['id']} (max_groups)")
            continue
        chosen.append(g)
        covered |= mem
    for g in chosen:
        # pins on the top group (0.19): a pinned effect makes the group take over there too;
        # a pinned 'transparent' gives an intro/outro back to the members
        tpins = (_target_prefs(g["id"], mprefs).get("_pins") or {}).get("top", {})
        add = [(windows[i].start, windows[i].end) for i, e in tpins.items() if canon(e) not in ("transparent", "choreo")]
        drop = [(windows[i].start, windows[i].end) for i, e in tpins.items() if canon(e) in ("transparent", "choreo")]
        cho = [(windows[i].start, windows[i].end) for i, e in tpins.items() if canon(e) == "choreo"]
        gspans = merge_spans(span_minus(spans + add, drop))     # where it takes over (its members rest)
        if not gspans and not cho:
            _reason(skipped, g["id"], "top pass: no " + "/".join(sorted(want)) + " sections in this song")
            continue
        _reason(skipped, g["id"], None)
        plan, excl = plan_target(g, _target_prefs(g["id"], mprefs), windows, effects_cfg, styles, scfg, seed,
                                 scfg.get("top_alternatives", 3), seed_overrides=seed_overrides, pin_pass="top")
        plan["segments"] = intersect(plan["segments"], merge_spans(gspans + cho))   # a choreography: its parts play
        plan["pass"] = "top"
        if excl:
            exclusions[g["id"]] = excl
        # members (and groups made of them) rest in those sections so the yard moves as one;
        # segments you pinned on a member stay (its row comes after the group's, so it wins)
        mem = _models_under(g, by_id)
        for p in plans if gspans else []:
            tm = by_id.get(p["target"])
            if tm is not None and _models_under(tm, by_id) & mem:
                keep = [x for x in p["segments"] if x.get("pinned")]
                p["segments"] = sorted(carve([x for x in p["segments"] if not x.get("pinned")], gspans) + keep,
                                       key=lambda x: x["start"])
                p["rests"] = {"for": g["id"], "spans": [[round(a, 3), round(b, 3)] for a, b in gspans]}
        plans.insert(0, plan)
    return plans


def apply_rests(plans, models):
    """Where a top group plays, every other layer on its members rests too - detail groups
    and enhance layers included (they are planned after the top pass); pinned segments stay."""
    by_id = {m["id"]: m for m in models["models"]}
    for top in [p for p in plans if p.get("pass") == "top" and p["segments"]]:
        g = by_id.get(top["target"])
        if g is None:
            continue
        mem = _models_under(g, by_id)
        spans = merge_spans([(x["start"], x["end"]) for x in top["segments"]
                             if x["selected"]["effect"] != "choreo"])   # a choreography: its parts play (0.24.47)
        if not spans:
            continue
        for p in plans:
            tm = by_id.get(p["target"])
            if p is top or p.get("react") or p.get("pass") == "top" or tm is None or not (_models_under(tm, by_id) & mem):
                continue
            keep = [x for x in p["segments"] if x.get("pinned")]
            p["segments"] = sorted(carve([x for x in p["segments"] if not x.get("pinned")], spans) + keep,
                                   key=lambda x: x["start"])
            p["rests"] = {"for": g["id"], "spans": [[round(a, 3), round(b, 3)] for a, b in spans]}
    return plans


def merge_spans(spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[list[float]] = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1] + 1e-6:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def span_minus(spans, cut) -> list[tuple[float, float]]:
    """spans with the parts inside cut removed."""
    return [(g["start"], g["end"]) for g in carve([{"start": a, "end": b} for a, b in spans], cut)]


def pin_rows(plans, models, mprefs, windows, effects_cfg, styles, scfg, seed, seed_overrides, skipped,
             exclusions, notes):
    """Pins on a prop that a group sequences (0.19): the prop gets a row of its own that
    plays only where pinned (pass 'pin'). The exporter writes these rows last, so they win
    over the group's row - e.g. 'pin Tree @1:08 dark' blacks out Tree while its group plays."""
    by_id = {m["id"]: m for m in models["models"]}
    for tid, tp in sorted(mprefs.get("targets", {}).items()):
        slot = (tp.get("_pins") or {}).get("pin")
        if not slot:
            continue
        m = by_id.get(tid)
        if m is None or not m.get("supported_for_generation"):
            notes.append(f"pin {tid}: not a usable model - 'pin' lists your pins, 'unpin {tid}' removes them")
            continue
        plan, excl = plan_target(m, _target_prefs(tid, mprefs), windows, effects_cfg, styles, scfg, seed,
                                 scfg.get("top_alternatives", 3), seed_overrides=seed_overrides, pin_pass="pin")
        spans = merge_spans([(windows[i].start, windows[i].end) for i in slot])
        plan["segments"] = [g for g in intersect(plan["segments"], spans) if g.get("pinned")]
        plan["pass"] = "pin"
        if excl:
            exclusions.setdefault(tid, []).extend(x for x in excl if x["reason"].startswith("pinned, but"))
        if plan["segments"]:
            plans.append(plan)
    return plans


def place_rows(plans, models, mprefs, windows, effects_cfg, styles, scfg, seed, seed_overrides, notes,
               exclusions: dict | None = None):
    """Effects placed with promote / demote (0.21, pins of pass 'place'): the target plays the
    effect there, and every layer of what is inside it rests (a group's own other layers too).
    Larger targets first, so a smaller one placed inside (written later) shows over it."""
    by_id = {m["id"]: m for m in models["models"]}
    placed = []
    for tid, tp in mprefs.get("targets", {}).items():
        slot = (tp.get("_pins") or {}).get("place")
        if not slot:
            continue
        m = by_id.get(tid)
        if m is None or not m.get("supported_for_generation", True):
            notes.append(f"promote/demote {tid}: not a usable prop or group - 'pin' lists your pins, "
                         f"'unpin {tid}' removes them")
            continue
        plan, excl = plan_target(m, _target_prefs(tid, mprefs), windows, effects_cfg, styles, scfg, seed,
                                 scfg.get("top_alternatives", 3), seed_overrides=seed_overrides, pin_pass="place")
        for x in excl:                                 # 0.21.3: an effect the target can't play was dropped silently
            if x["reason"].startswith("pinned, but"):
                notes.append(f"promote/demote {tid}: {x['effect']} can't play on it ({x['reason'][len('pinned, but '):]})"
                             f" - nothing placed there; promote again with --effect (one {tid} can play)")
                if exclusions is not None:
                    exclusions.setdefault(tid, []).append(x)
        spans = merge_spans([(windows[i].start, windows[i].end) for i in slot])
        plan["segments"] = [g for g in intersect(plan["segments"], spans) if g.get("pinned")]
        for g in plan["segments"]:
            g["reasons"] = ["placed here with promote / demote (a pin)"] + [r for r in g.get("reasons", [])
                                                                             if "pinned" not in r]
        plan["pass"] = "place"
        if plan["segments"]:
            placed.append((plan, _models_under(m, by_id), spans))
    placed.sort(key=lambda x: -len(x[1]))
    for plan, under, spans in placed:
        for p in plans:
            if p.get("pass") in ("face", "borrowed") or p in [q for q, _, _ in placed]:
                continue
            tm = by_id.get(p["target"])
            if tm is not None and _models_under(tm, by_id) <= under:
                p["segments"] = sorted(carve(p["segments"], spans), key=lambda x: x["start"])
    plans.extend(q for q, _, _ in placed)
    return plans


def detail_pass(plans, models, mprefs, windows, effects_cfg, styles, scfg, seed, seed_overrides, cfg,
                skipped, exclusions):
    by_id = {m["id"]: m for m in models["models"]}
    cands = []
    for m in models["models"]:
        if not m.get("supported_for_generation"):
            continue
        tp = _target_prefs(m["id"], mprefs)
        if m["kind"] == "group" and group_role(m, mprefs) == "detail" and tp.get("enabled", True):
            cands.append(m)
        elif m["kind"] == "submodel" and (mprefs.get("targets", {}).get(m["id"], {}).get("enabled")
                                          or tp.get("role") == "detail"):
            cands.append(m)
    cands.sort(key=lambda g: (-(len(g.get("detail_members") or g.get("members", [])) if g["kind"] == "group" else 1),
                              g["id"]))
    accent = _accent_cfg(effects_cfg)
    comp, rest = float(cfg.get("complement", 0.6)), float(cfg.get("rest", 1.1))
    taken: dict[str, str] = {}
    for g in cands:
        under = _models_under(g, by_id)
        clash = sorted({taken[x] for x in under if x in taken})
        if clash:
            _reason(skipped, g["id"], f"detail pass: overlaps {clash[0]} (one detail target per prop; "
                                      f"to use this one instead: 'pref models/targets/{clash[0]}/role = unused')")
            continue
        base = [p for p in plans if not p.get("react") and _models_under(by_id.get(p["target"], {"kind": "model",
                                                                                                  "id": p["target"]}),
                                                                           by_id) & under]

        def adjust(w, e, base=base):
            f = _family_at(base, (w.start + w.end) / 2)
            x = comp if f and accent["effects"][e]["family"] == f and lit(e) else 1.0
            return x * (rest if e == "transparent" else 1.0)
        tp = _target_prefs(g["id"], mprefs)
        plan, excl = plan_target(g, tp, windows, accent, styles, scfg, seed, scfg.get("top_alternatives", 3),
                                 layer=1, seed_overrides=seed_overrides, adjust=adjust, pin_pass="detail")
        plan["pass"] = "detail"                      # 0.24.15: pins on a detail row are used (they weren't)
        if excl:
            exclusions[g["id"]] = excl
        _reason(skipped, g["id"], None)
        for x in under:
            taken[x] = g["id"]
        plans.append(plan)
    return plans


def enhance_pass(plans, models, mprefs, windows, effects_cfg, styles, scfg, seed, seed_overrides, cfg,
                 exclusions):
    by_id = {m["id"]: m for m in models["models"]}
    main = {p["target"]: p for p in plans if p.get("pass", "main") == "main" and not p.get("react")}
    marked = [t for t in main if _target_prefs(t, mprefs).get("enhance")]
    props = sorted((t for t in main if by_id.get(t, {}).get("kind") == "model"),
                   key=lambda t: (-by_id[t].get("node_count", 0), t))
    focal = list(dict.fromkeys(marked + props[:int(cfg.get("focal_count", 2))]))
    focal = [t for t in focal if _target_prefs(t, mprefs).get("enhance", True) is not False]
    accent = _accent_cfg(effects_cfg)
    comp, min_e = float(cfg.get("complement", 0.6)), float(cfg.get("min_energy", 0.6))
    for t in focal:
        base = [main[t]]

        def adjust(w, e, base=base):
            if e == "transparent":
                return 1.0
            if w.features.get("energy", 0) < min_e:
                return 0.0                          # quiet: the accent layer rests
            f = _family_at(base, (w.start + w.end) / 2)
            return comp if f and accent["effects"][e]["family"] == f else 1.0
        plan, excl = plan_target(by_id[t], _target_prefs(t, mprefs), windows, accent, styles, scfg, seed,
                                 scfg.get("top_alternatives", 3), layer=1, seed_overrides=seed_overrides,
                                 adjust=adjust, pin_pass="enhance")
        plan["pass"] = "enhance"
        if any(s["selected"]["effect"] != "transparent" for s in plan["segments"]):   # kept: explain says why
            plans.append(plan)
    return plans


