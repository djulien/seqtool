"""The base pass: whole-yard moments (0.20, DESIGN §13f).

After the per-prop passes, a few moments make the yard act together:

    unison          every prop flashes at once on a strong section start or a drop
    sweep           the props flash one after another, left to right (or back), over
                    the bar before a strong section start - the sweep lands on it
    call_response   the left half and the right half answer each other on 2-bar
                    phrases at the start of a quieter section (verse, bridge ...)

Candidates are scored from the music (transition strength, energy jump); repeated
sections score higher the later they come (escalation: chorus 3 gets more than
chorus 1). A budget (`per_minute`) keeps them rare enough to stay special. Nothing
happens inside the top pass's sections (the yard already moves as one there).

What the props' own effects do during a moment (`members`, the user's option):
    cut     they rest for the whole moment, so only the moment shows (default)
    over    they keep playing; the moment is drawn above them
    under   they keep playing and win; the moment shows only where they rest
per prop or group: models targets.<name>.base_members; targets.<name>.base = false
leaves a prop out of the moments.

Moments are listed in the matchup ("moments"), and each moment's flashes are plans
of pass "base" on the props' own rows (above their groups), with the moment named
in every segment's reasons, so 'explain' says why the prop flashes there.
"""
from __future__ import annotations

from bisect import bisect_left

from ..common.seed import sub_rng
from ..common.vocab import lit
from .passes import _models_under, carve, merge_spans

DEFAULTS = {"enabled": True, "per_minute": 1.5, "members": "cut", "min_props": 3, "min_gap_s": 6.0,
            "types": {"unison": True, "sweep": True, "call_response": True},
            "escalation": 0.3, "unison_min_strength": 0.6, "drop_energy_jump": 0.25,
            "call_sections": ["verse", "bridge", "breakdown", "pre_chorus"], "effect": "pulse"}
MODES = ("cut", "over", "under")


def _beats(music: dict) -> tuple[list[float], list[float], float]:
    ev = music["analysis"]["events"]
    beats = sorted(e["time"] for e in ev.get("beats", []))
    downs = sorted(e["time"] for e in ev.get("downbeats", [])) or beats[::4]
    bpm = music["analysis"]["summary"].get("tempo", {}).get("bpm") or 120.0
    return beats, downs, 60.0 / bpm


def _bar_before(downs: list[float], t: float, beat: float) -> float:
    i = bisect_left(downs, t - 1e-3)
    return downs[i - 1] if i > 0 and t - downs[i - 1] <= 8 * beat else t - 4 * beat


def candidates(music: dict, profile: dict, windows, cfg: dict, seed: int, top_spans) -> list[dict]:
    beats, downs, beat = _beats(music)
    secs = sorted(profile["sections"], key=lambda s: s["start"])
    dur = music["audio"]["duration"]
    esc = float(cfg.get("escalation", 0.3))
    types = cfg.get("types", {})
    out = []

    def inside_top(a, b):
        return any(a < y and b > x for x, y in top_spans)

    for k, s in enumerate(secs[1:], 1):
        t = s["start"]
        ts = float((s.get("transition") or {}).get("incoming_strength", 0.5))
        rep = 1 + esc * int(s.get("repeat_index", 0) or 0)
        rise = max(0.0, float(s.get("energy", 0.5)) - float(secs[k - 1].get("energy", 0.5)))
        where = f"{s.get('type') or 'section'} #{s['index']}" + (f" (repeat {s['repeat_index'] + 1})"
                                                                 if s.get("repeat_index") else "")
        if types.get("unison", True) and ts >= float(cfg.get("unison_min_strength", 0.6)) and not inside_top(t, t + 2 * beat):
            out.append({"type": "unison", "start": t, "end": min(dur, t + 2 * beat), "section_index": s["index"],
                        "score": (ts + rise) * rep, "reason": f"unison hit on the start of {where} "
                                                              f"(section change {ts:.2f})"})
        a = _bar_before(downs, t, beat)
        if types.get("sweep", True) and ts >= 0.5 and t - a >= 2 * beat and not inside_top(a, t):
            out.append({"type": "sweep", "start": a, "end": t, "section_index": secs[k - 1]["index"],
                        "score": (0.8 * ts + rise) * rep,
                        "reason": f"sweep across the yard in the bar before {where}"})
    for s in secs:                                    # call and response at the start of quieter sections
        if not types.get("call_response", True) or s.get("type") not in cfg.get("call_sections", []):
            continue
        a = min((d for d in downs if d >= s["start"] - 1e-3), default=s["start"])
        bar = 4 * beat
        b = min(s["end"], a + 8 * bar)
        if b - a < 4 * bar or inside_top(a, b):
            continue
        rep = 1 + esc * int(s.get("repeat_index", 0) or 0)
        out.append({"type": "call_response", "start": a, "end": b, "section_index": s["index"],
                    "score": (0.35 + 0.3 * float(s.get("energy", 0.5))) * rep,
                    "reason": f"call and response, left and right halves, in {s.get('type')} #{s['index']}"})
    for w in windows[1:]:                             # drops inside a section: a sudden jump in loudness
        prev = windows[w.index - 1]
        jump = w.features.get("energy", 0) - prev.features.get("energy", 0)
        if not w.is_section_start and jump >= float(cfg.get("drop_energy_jump", 0.25)) and types.get("unison", True) \
                and not inside_top(w.start, w.start + 2 * beat):
            out.append({"type": "unison", "start": w.start, "end": min(dur, w.start + 2 * beat),
                        "section_index": w.section_index, "score": jump * 1.5,
                        "reason": f"unison hit on a drop (loudness up {jump:.2f})"})
    rng = sub_rng(seed, "base-moments")
    for c in out:                                     # a hair of seeded jitter decides ties
        c["score"] = round(c["score"] + rng.random() * 1e-3, 4)
    return out


def choose(cands: list[dict], cfg: dict, duration: float) -> list[dict]:
    budget = max(1, int(round(float(cfg.get("per_minute", 1.5)) * duration / 60.0))) if cands else 0
    gap = float(cfg.get("min_gap_s", 6.0))
    picked: list[dict] = []
    used = 0
    for c in sorted(cands, key=lambda c: (-c["score"], c["start"])):
        clash, pair = False, False
        for p in picked:
            touching = (p["type"] == "sweep" and c["type"] == "unison" and abs(p["end"] - c["start"]) < 0.05) or \
                       (c["type"] == "sweep" and p["type"] == "unison" and abs(c["end"] - p["start"]) < 0.05)
            if touching:                              # a sweep that lands on a unison hit: one moment, two parts
                pair = True
                continue
            if c["start"] < p["end"] + gap and p["start"] < c["end"] + gap:
                clash = True
                break
        if clash or (not pair and used >= budget):
            continue
        picked.append(c)
        used += 0 if pair else 1
    picked.sort(key=lambda c: c["start"])
    for i, c in enumerate(picked, 1):
        c["id"] = f"m{i}"
    return picked


def _flash(start, end, eff, eff_cfg, moment, palette="accent", extra=""):
    params = {}
    for name, spec in eff_cfg.get("parameters", {}).items():
        if "range" in spec:
            lo, hi = spec["range"]
            params[name] = round(hi if name in ("intensity", "brightness") else (lo + hi) / 2, 3)
        elif "choices" in spec:
            params[name] = spec["choices"][0]
    from .parts import segment
    seg = segment(start, end, eff, {"id": f"moment {moment['id']}", "index": moment["section_index"]},
                  family=eff_cfg.get("family", ""), params=params, palette=palette, moment=moment["id"],
                  why=f"moment {moment['id']}: {moment['reason']}" + extra)
    seg["selected"]["family"] = eff_cfg.get("family", "")
    return seg


def flashes(moment: dict, props: list[dict], beats: list[float], beat: float, eff: str, eff_cfg: dict) -> dict:
    """{prop id: [segments]} for one moment."""
    a, b = moment["start"], moment["end"]
    out: dict[str, list] = {}
    if moment["type"] == "unison":
        for p in props:
            out[p["id"]] = [_flash(a, b, eff, eff_cfg, moment)]
    elif moment["type"] == "sweep":
        order = sorted(props, key=lambda p: ((p.get("yard") or {}).get("x", 0.5), p["id"]))
        if moment.get("reverse"):
            order.reverse()
        n = len(order)
        step = (b - a) / n
        for k, p in enumerate(order):
            s = a + k * step
            out[p["id"]] = [_flash(s, min(b, s + max(step * 1.6, 0.15)), eff, eff_cfg, moment,
                                   extra=f" ({k + 1} of {n}, {'right to left' if moment.get('reverse') else 'left to right'})")]
    elif moment["type"] == "call_response":
        xs = sorted((p.get("yard") or {}).get("x", 0.5) for p in props)
        mid = xs[len(xs) // 2] if xs else 0.5
        left = [p for p in props if (p.get("yard") or {}).get("x", 0.5) < mid] or props[: len(props) // 2]
        right = [p for p in props if p not in left]
        bar2 = 8 * beat                               # 2-bar phrases, left first
        k, t = 0, a
        while t < b - 1e-3:
            side, who = (left, "left") if k % 2 == 0 else (right, "right")
            e = min(b, t + bar2)
            hits = [x for x in beats if t - 1e-3 <= x < e - 1e-3] or [t]
            for p in side:
                for i, h in enumerate(hits):
                    end = hits[i + 1] if i + 1 < len(hits) else e
                    out.setdefault(p["id"], []).append(
                        _flash(h, min(e, h + max(0.12, 0.6 * (end - h))), eff, eff_cfg, moment,
                               extra=f" ({who} half, phrase {k + 1})"))
            k += 1
            t = e
    return out


def _mode(pid: str, mprefs: dict, by_id: dict, default: str) -> str:
    tg = mprefs.get("targets", {})
    v = (tg.get(pid) or {}).get("base_members")
    if v in MODES:
        return v
    for g in sorted(by_id.values(), key=lambda g: g["id"]):
        if g["kind"] == "group" and pid in g.get("members", []) and (tg.get(g["id"]) or {}).get("base_members") in MODES:
            return tg[g["id"]]["base_members"]
    return default


def _lit_spans(plans, pid, by_id) -> list[tuple[float, float]]:
    spans = []
    for p in plans:
        tm = by_id.get(p["target"])
        if tm is None or pid not in _models_under(tm, by_id):
            continue
        spans += [(g["start"], g["end"]) for g in p["segments"] if lit(g["selected"]["effect"])]
    return merge_spans(spans)


def base_pass(plans: list[dict], models: dict, mprefs: dict, music: dict, profile: dict, windows,
              effects_cfg: dict, cfg: dict, seed: int, notes: list) -> tuple[list[dict], list[dict]]:
    cfg = {**DEFAULTS, **(cfg or {})}
    if not cfg.get("enabled", True):
        return plans, []
    by_id = {m["id"]: m for m in models["models"]}
    tg = mprefs.get("targets", {})
    phys: set[str] = set()
    for p in plans:                                   # the props the per-prop passes light
        if p.get("react") or p.get("pass") in ("face", "pin"):
            continue
        tm = by_id.get(p["target"])
        if tm is not None and any(lit(g["selected"]["effect"]) for g in p["segments"]):
            phys |= _models_under(tm, by_id)
    sing = {p["target"] for p in plans if p.get("pass") == "face"}
    props = [by_id[x] for x in sorted(phys) if x in by_id and by_id[x]["kind"] == "model"
             and x not in sing and (tg.get(x) or {}).get("base", True) is not False]
    if len(props) < int(cfg.get("min_props", 3)):
        notes.append(f"base pass: only {len(props)} prop(s) to move together - no moments "
                     f"(scoring.passes.base.min_props is {cfg.get('min_props', 3)})")
        return plans, []
    eff = cfg.get("effect", "pulse")
    eff_cfg = effects_cfg["effects"].get(eff)
    if eff_cfg is None:
        notes.append(f"base pass: effect '{eff}' isn't available - no moments")
        return plans, []
    top_spans = merge_spans([(g["start"], g["end"]) for p in plans if p.get("pass") == "top" for g in p["segments"]
                            if g["selected"]["effect"] != "choreo"])   # a choreography: its parts (0.24.49)
    beats, downs, beat = _beats(music)
    moments = choose(candidates(music, profile, windows, cfg, seed, top_spans), cfg, music["audio"]["duration"])
    rng = sub_rng(seed, "base-sweep")
    default_mode = cfg.get("members", "cut") if cfg.get("members") in MODES else "cut"
    per_prop: dict[str, list] = {}
    for m in moments:
        if m["type"] == "sweep":
            m["reverse"] = bool(rng.randrange(2))
        m["targets"] = [p["id"] for p in props]
        for pid, segs in flashes(m, props, beats, beat, eff, eff_cfg).items():
            per_prop.setdefault(pid, []).extend(segs)
    modes = {p["id"]: _mode(p["id"], mprefs, by_id, default_mode) for p in props}
    for m in moments:
        ms = {modes[x] for x in m["targets"]}
        m["members"] = ms.pop() if len(ms) == 1 else "mixed"
    # cut: everything else on the props rests for the whole moment (groups over them included)
    cut_props = {pid for pid, md in modes.items() if md == "cut"}
    spans = merge_spans([(m["start"], m["end"]) for m in moments])
    if cut_props and spans:
        for p in plans:
            tm = by_id.get(p["target"])
            if p.get("react") or p.get("pass") in ("face", "pin") or tm is None:
                continue
            if _models_under(tm, by_id) & cut_props:
                keep = [x for x in p["segments"] if x.get("pinned")]
                p["segments"] = sorted(carve([x for x in p["segments"] if not x.get("pinned")], spans) + keep,
                                       key=lambda x: x["start"])
    out = list(plans)
    for pid, segs in sorted(per_prop.items()):
        segs.sort(key=lambda g: g["start"])
        clean = []
        for g in segs:                                # flashes on one row never overlap
            if clean and g["start"] < clean[-1]["end"]:
                clean[-1] = {**clean[-1], "end": g["start"]}
                if clean[-1]["end"] - clean[-1]["start"] < 0.05:
                    clean.pop()
            clean.append(g)
        if modes[pid] == "under":                     # only where the prop otherwise rests
            busy = _lit_spans(plans, pid, by_id)
            clean = carve(clean, busy)
        if not clean:
            continue
        own = [p for p in plans if p["target"] == pid]
        layer = 1 + max(p.get("layer", 0) for p in own) if own else 0
        out.append({"target": pid, "target_kind": "model", "layer": layer, "pass": "base",
                    "members": modes[pid], "segments": clean})
    return out, moments
