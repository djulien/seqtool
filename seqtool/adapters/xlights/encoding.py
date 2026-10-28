"""Learned xLights encoding: turns generic effects + parameters into the exact
effect name, settings string and palette string a given xLights version
writes. Built from the kit wizard's observations.json (+ reference.xsq).

Accepts every kit_version written so far: older files store one "changes"
map per step; it is split into primary/companion settings here."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

PARAM_MAP = json.loads(Path(__file__).with_name("param_map.json").read_text(encoding="utf-8"))
UNITS = ("second", "beat", "bar")


def param_map() -> dict:
    """Built-in map, deep-merged with the user's xlights.json "param_map" overrides."""
    from ...common.config import _merge, load
    return _merge(PARAM_MAP, load("xlights").get("param_map", {}))


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _decimals(*vals) -> int:
    return max((len(str(v).split(".", 1)[1]) for v in vals if v is not None and "." in str(v)), default=0)


def _fmt(x: float, dec: int) -> str:
    return f"{x:.{dec}f}" if dec else str(int(round(x)))


def settings_string(d: dict) -> str:
    return ",".join(f"{k}={d[k]}" for k in sorted(d))


def _normalise_step(step: dict) -> dict:
    if "primary" in step:
        return step
    from .kit import split_change
    primary, companions = split_change(step.get("changes", {}))
    return {**step, "primary": primary, "companions": companions}


@dataclass
class Step:
    key: str
    default: str | None
    extreme: str | None
    companions: dict
    note: str = ""


def _texty(v) -> bool:
    new = v[1] if isinstance(v, (list, tuple)) else v
    return isinstance(new, str) and new.strip() != "" and _num(new) is None and new.lower() not in ("true", "false")


def text_key(learned: dict, pname: str, claimed: set | None = None) -> str | None:
    """The setting a text step (a face's name, a timing track's name) is stored in (0.24.18).
    Settings another step of the effect already stands for ('claimed' - e.g. the face's, when the
    phoneme-track step also shows the face changing) are not it (0.24.20). One changed setting
    left: that one. Several (xLights also switched a related option): the one holding text rather
    than a number or a yes/no - and, if still more than one, the one whose name has the step's
    words (timing_track -> ..._TimingTrack)."""
    claimed = claimed or set()
    prim = {k: v for k, v in (learned.get("primary") or {}).items() if k not in claimed}
    if len(prim) == 1 and _texty(next(iter(prim.values()))):
        return next(iter(prim))
    cands = {k: v for k, v in {**(learned.get("primary") or {}), **(learned.get("companions") or {})}.items()
             if k not in claimed}
    tx = [k for k, v in cands.items() if _texty(v)]
    if len(tx) == 1:
        return tx[0]
    want = pname.replace("_", "").lower()
    named = [k for k in (tx or cands) if want in k.replace("_", "").lower()]
    if len(named) == 1:
        return named[0]
    return next(iter(prim)) if len(prim) == 1 else None


def claimed_keys(params: dict, pname: str) -> set:
    """The settings the effect's EARLIER learned steps stand for (each one's single changed
    setting): a later step showing the same change again (the face, in the phoneme-track step)
    is that earlier step's, not this one's."""
    out = set()
    for k, st in params.items():
        if k == pname:
            break
        prim = st.get("primary") or {}
        if len(prim) == 1:
            out |= set(prim)
    return out


@dataclass
class Encoding:
    version: str
    timing: str | None
    effects: dict                      # generic id -> {stored_name, defaults, params}
    palette_base: dict
    reference: Path | None
    kit_version: int = 0
    notes: list = field(default_factory=list)
    submodel: dict | None = None            # how submodel rows are stored (structure step 'submodel')
    group_render: dict | None = None        # 0.24.36: {"key", "per_model"} - a group effect drawn per prop
    raw: dict | None = None                 # observations.json as stored
    curves: "Curves | None" = None          # 0.24.48: how value curves are written (learned)
    rotation: dict | None = None            # 0.24.48: the Layer Settings rotation slider {"key", "default", "extreme"}

    @classmethod
    def load(cls, folder: Path) -> "Encoding":
        obs = json.loads((folder / "observations.json").read_text(encoding="utf-8"))
        effects = {}
        for e in obs["effects"].values():
            effects[e["generic"]] = {**e, "params": {k: _normalise_step(v) for k, v in e["params"].items()}}
        pal = dict(obs.get("structure", {}).get("palette", {}).get("palette", {}))
        base = {k: v for k, v in pal.items() if not k.startswith(("C_BUTTON_Palette", "C_CHECKBOX_Palette"))}
        ref = folder / "reference.xsq"
        st = obs.get("structure", {})
        return cls(obs.get("xlights_version") or folder.name, obs.get("timing"), effects, base,
                   ref if ref.exists() else None, obs.get("kit_version", 0),
                   submodel=st.get("submodel"), group_render=st.get("group_render"), raw=obs,
                   curves=Curves.learn(st), rotation=st.get("rotation"))

    def compatibility(self) -> tuple[str, str]:
        """('ok'|'older'|'retrain', message) - is this training still usable with the current kit?"""
        from .kit import manifest
        m = manifest()
        cur, oldest = m["kit_version"], m.get("min_compatible", m["kit_version"])
        if self.kit_version >= cur:
            return "ok", f"kit v{self.kit_version} (current)"
        if self.kit_version >= oldest:
            from .kit import build_steps
            todo = len(build_steps(self.raw)) - 1 if self.raw else 0
            if todo:
                return "older", (f"kit v{self.kit_version}, current v{cur}: usable as-is; "
                                 f"{{do}}xlights-kit --update{{/}} learns the {todo} new step(s)")
            return "older", (f"kit v{self.kit_version}, current v{cur}: complete - only the wording of the steps "
                             f"changed, nothing to re-learn ({{do}}xlights-kit --update{{/}} marks it current)")
        return "retrain", (f"kit v{self.kit_version} is too old (need v{oldest}+): "
                           f"re-run {{do}}seqtool xlights-kit --fresh{{/}}")

    def supports(self, generic: str) -> bool:
        return generic in self.effects

    def step(self, generic: str, kit_param: str, pmap: dict | None = None) -> Step | None:
        """The learned key/default/extreme for one kit step, with 'assume' fallbacks
        for values xLights doesn't store. None if unusable."""
        e = self.effects.get(generic)
        if not e or kit_param not in e["params"]:
            return None
        st = e["params"][kit_param]
        if len(st["primary"]) != 1:
            return None
        (key, (old, new)), = st["primary"].items()
        default = e["defaults"].get(key, old)
        assume = (pmap or param_map()).get("assume", {}).get(key, {})
        note = ""
        if _num(default) is None and "default" in assume:
            default, note = assume["default"], f"assumed default {assume['default']}"
        if (new is None or str(new).strip() == "") and "extreme" in assume:
            new = assume["extreme"]
            note = (note + "; " if note else "") + f"assumed extreme {new}" + \
                (f" ({assume['why']})" if assume.get("why") else "")
        return Step(key, default, new, st.get("companions", {}), note)

    def problems(self) -> list[str]:
        """Learned steps that can't be used even with assumptions (reported by inspect/export)."""
        out = []
        pm = param_map()
        for gen, e in sorted(self.effects.items()):
            scaled = {spec["scale"] for spec in pm.get(gen, {}).values() if isinstance(spec, dict) and "scale" in spec}
            for kp, st in e["params"].items():
                if kp not in scaled:                  # choice / text steps need no extreme value (0.19.1)
                    continue
                s = self.step(gen, kp, pm)
                if s is None:
                    out.append(f"{e['stored_name']} {kp}: {len(st['primary'])} primary settings")
                elif _num(s.extreme) is None and _num(s.default) is not None:
                    out.append(f"{e['stored_name']} {kp}: no usable extreme value for {s.key}")
        return out

    def effect(self, generic: str, params: dict, duration: float = 10.0, beat_s: float = 0.5,
               pmap_all: dict | None = None, yours=()) -> tuple[str, str]:
        """-> (stored effect name, settings string). duration = effect length (s); beat_s = beat length (s).
        yours: settings you gave (a pin's NAME=VALUE): on xLights' whole scale, not the span seqtool keeps
        its own choices in (0.24.36: 'density=dense' is dense)."""
        pm_all = pmap_all or param_map()
        e = self.effects[generic]
        s = dict(e["defaults"])
        pmap = pm_all.get(generic, {})
        set_numeric: dict[str, float] = {}
        unit_len = {"second": 1.0, "beat": beat_s, "bar": 4 * beat_s}
        for pname, spec in pmap.items():
            if pname not in params:
                continue
            v = params[pname]
            pts = curve_points(v)                         # 0.24.48: a glide or a curve over the effect
            if pts is not None:
                v = pts[0][1]
            if "scale" in spec and isinstance(v, (int, float)):
                st = self.step(generic, spec["scale"], pm_all)
                if st is None:
                    continue

                def place(vv, st=st, spec=spec if pname not in yours else {k: v for k, v in spec.items() if k != "span"}):
                    """generic 0..1 -> (stored text, number) for this setting"""
                    lo_n, hi_n = _num(st.default), _num(st.extreme)
                    vv = max(0.0, min(1.0, float(vv)))
                    if spec.get("invert"):
                        vv = 1.0 - vv
                    if "range" in spec:
                        a, b = spec["range"]
                        x = a + (b - a) * vv
                        return _fmt(x, _decimals(st.default, st.extreme)), x
                    if lo_n is None or hi_n is None:
                        return None, None
                    if {lo_n, hi_n} <= {0.0, 1.0} and _decimals(st.default, st.extreme) == 0 and "rate" not in spec:
                        return (st.extreme if vv >= 0.5 else st.default), None          # checkbox-like
                    if "rate" in spec:
                        r = spec["rate"]
                        lo_r, hi_r = r.get("range", [0.25, 1.0])
                        per = unit_len.get(r.get("per", "bar"), 1.0)
                        x = (lo_r + (hi_r - lo_r) * vv) * max(duration, 0.05) / per
                        x = max(min(x, max(lo_n, hi_n)), min(lo_n, hi_n) if r.get("min_is_default", False) else 0.0)
                        return _fmt(x, max(1, _decimals(st.default, st.extreme))), x
                    a, b = spec.get("span", [0.0, 1.0])
                    x = lo_n + (hi_n - lo_n) * (a + (b - a) * vv)
                    return _fmt(x, _decimals(st.default, st.extreme)), x
                text, x = place(v)
                if text is None:
                    continue
                s[st.key] = text
                if x is not None:
                    set_numeric[st.key] = x
                if pts is not None and x is not None and self.curves and "rate" not in spec:
                    real = [(t, place(y)[1]) for t, y in pts]
                    if all(r is not None for _, r in real):
                        kv = self.curves.write(st.key, real, [_num(st.default), _num(st.extreme)],
                                               _decimals(st.default, st.extreme))
                        if kv:
                            s[kv[0]] = kv[1]
                            if self.curves.slider_dropped:     # as xLights writes it: the curve instead
                                s.pop(st.key, None)
                s.update({k: c[1] for k, c in st.companions.items() if c[1] is not None})
            elif "text" in spec:                      # 0.19.1: the setting takes the parameter's own text
                if v in (None, ""):
                    continue
                learned = e["params"].get(spec["text"])
                key = text_key(learned, spec["text"], claimed_keys(e["params"], spec["text"])) if learned else None
                if key is None:                          # 0.24.18: said, not silently left at xLights' default
                    n_ = (f"{e['stored_name']} effects: '{spec['text'].replace('_', ' ')}' is left as xLights' default - "
                          + ("the kit hasn't learned that step yet: 'xlights-kit --update'" if learned is None else
                             "the kit's step for it changed several settings and none is clearly the name: "
                             "'xlights-kit --redo " + e["stored_name"] + "." + spec["text"] + "' (change only that one setting)"))
                    if n_ not in self.notes:
                        self.notes.append(n_)
                    continue
                s[key] = str(v)
                for ck, cv in (learned.get("companions") or {}).items():   # xLights drops a related one (0.24.20)
                    if ck != key and isinstance(cv, (list, tuple)) and cv[1] is None:
                        s.pop(ck, None)
            elif "choice" in spec:
                kstep = spec["choice"].get(str(v), "default")
                learned = e["params"].get(kstep)
                if kstep == "default" or learned is None:
                    continue
                for key, (old, new) in learned["primary"].items():
                    if key in set_numeric and _num(new) is not None:          # sign only
                        sign = -1 if _num(new) < 0 else 1
                        s[key] = _fmt(sign * abs(set_numeric[key]), _decimals(s[key], new))
                    else:
                        s[key] = new
                for key, (old, new) in learned.get("companions", {}).items():
                    if new is None:
                        s.pop(key, None)
                    else:
                        s[key] = new
        if params.get("rotation") is not None:          # 0.24.48: Layer Settings rotation (any effect)
            self._rotate(s, params["rotation"])
        if params.get("area"):                         # 0.24.0: where on the prop (the effect's sub-buffer)
            kv = self.area(params["area"])
            if kv:
                s[kv[0]] = kv[1]
        if params.get("render") == "per_model":        # 0.24.36: a group's effect drawn on each of its props
            gr = self.group_render
            if gr and gr.get("key"):
                s[gr["key"]] = gr.get("per_model", "Per Model Default")
            else:
                n_ = ("group effects meant for each prop (render per model) are drawn as one picture - the kit "
                      "hasn't learned xLights' Render Style setting yet: 'xlights-kit --update'")
                if n_ not in self.notes:
                    self.notes.append(n_)
        return e["stored_name"], settings_string(s)

    def can_curve(self, generic: str, pname: str, pmap_all: dict | None = None) -> bool:
        """Can this setting follow a curve within one effect (a learned value curve)?"""
        if not self.curves:
            return False
        if pname == "rotation":
            return bool(self.rotation)
        spec = (pmap_all or param_map()).get(generic, {}).get(pname, {})
        if "scale" not in spec or "rate" in spec:
            return False
        st = self.step(generic, spec["scale"], pmap_all)
        if st is None or _num(st.default) is None or _num(st.extreme) is None:
            return False
        return not ({_num(st.default), _num(st.extreme)} <= {0.0, 1.0} and _decimals(st.default, st.extreme) == 0)

    def _rotate(self, s: dict, v) -> None:
        """rotation: 0..1 of the rotation slider's range (0 = as drawn, 1 = its highest), or a glide."""
        r = self.rotation
        if not r:
            n_ = "rotation is left out - the kit hasn't learned Layer Settings > Roto-Zoom > Z rotation yet: 'xlights-kit --update'"
            if n_ not in self.notes:
                self.notes.append(n_)
            return
        lo, hi = _num(r.get("default")), _num(r.get("extreme"))
        if lo is None:
            lo = 0.0                                   # xLights leaves a setting at its default out of the file
        if hi is None:
            return
        dec = _decimals(r.get("default"), r.get("extreme"))
        pts = curve_points(v) or [(0.0, float(v)), (1.0, float(v))]
        from ...common.config import load
        if not load("xlights").get("rotation_clockwise", True):   # your xLights turns the other way
            pts = [(t, (1.0 - y) % 1.0) for t, y in pts]
        real = [(t, lo + (hi - lo) * max(0.0, min(1.0, float(y)))) for t, y in pts]
        s[r["key"]] = _fmt(real[0][1], dec)
        if len({y for _, y in real}) > 1 and self.curves:
            kv = self.curves.write(r["key"], real, [lo, hi], dec)
            if kv:
                s[kv[0]] = kv[1]
                if self.curves.slider_dropped:
                    s.pop(r["key"], None)

    def area(self, rect) -> tuple[str, str] | None:
        """(setting, value) putting an effect in part of the prop - rect = [x, y, w, h] in percent
        from the top left - in the form this xLights version writes (learned from the kit's
        three sub-buffer steps: the right edge moved, then the left, then the top; nothing about
        the value is assumed but that it holds four numbers). None if not learned."""
        got = getattr(self, "_area", False)
        if got is False:
            got = self._area = _learn_area(self.effects)
        if not got:
            return None
        x, y, w, h = [float(v) for v in rect]
        want = {"left": x, "right": x + w}
        top, bottom = (100 - y, 100 - y - h) if got["top_full"] > 50 else (y, y + h)   # y up or down
        want.update(top=top, bottom=bottom)
        vals = [None] * 4
        for side, i in got["index"].items():
            vals[i] = want[side]
        text = got["template"]
        for i, v in enumerate(vals):
            text = text.replace("{%d}" % i, _fmt(v, got["decimals"][i]))
        return got["key"], text

    def palette(self, colors: list[str]) -> str:
        d = dict(self.palette_base)
        filler = ["#FFFFFF", "#FF0000", "#00FF00", "#0000FF", "#FFFF00", "#000000", "#00FFFF", "#FF00FF"]
        cols = [c.upper() for c in colors][:8]
        for i in range(8):
            d[f"C_BUTTON_Palette{i + 1}"] = cols[i] if i < len(cols) else filler[i]
            if i < len(cols):
                d[f"C_CHECKBOX_Palette{i + 1}"] = "1"
        return settings_string(d)


def find(version: str | None = None) -> Encoding | None:
    """Exact learned version if given and present, else the nearest older, else the newest."""
    from ...common.log import warn
    from .kit import learned_dirs, learned_versions
    vers = learned_versions()
    if not vers:
        return None
    if version and version not in vers:
        older = [v for v in vers if _vkey(v) <= _vkey(version)]
        pick = older[-1] if older else vers[-1]
        warn(f"no kit learned for xLights {version}; using {pick} ('xlights-kit' learns yours)")
        version = pick
    version = version or max(vers, key=_vkey)
    return Encoding.load(learned_dirs(version)[0])


def _vkey(v: str):
    return tuple(int(p) if p.isdigit() else 0 for p in v.split("."))


_NUMS = re.compile(r"-?\d+(?:\.\d+)?")


def _learn_area(effects: dict) -> dict | None:
    """From the kit's three sub-buffer steps (0.24.3: the Sub-Buffer's own right-click presets -
    Halves > Left Half, Thirds > Middle Third, Halves > Bottom Half): which of the value's four
    numbers is the left, right, top and bottom edge, and whether 'top' counts up or down."""
    near = lambda a, b: abs(a - b) <= 5                                      # noqa: E731
    for e in effects.values():
        ps = e.get("params", {})
        steps = [ps.get(k) for k in ("subbuffer_left_half", "subbuffer_middle_third", "subbuffer_bottom_half")]
        if not all(steps) or any(len(st.get("primary", {})) != 1 for st in steps):
            continue
        key = next(iter(steps[0]["primary"]))
        if any(next(iter(st["primary"])) != key for st in steps):
            continue
        vals = [str(next(iter(st["primary"].values()))[1] or "") for st in steps]
        half, third, bottom = [[float(n) for n in _NUMS.findall(v)] for v in vals]
        if any(len(n) != 4 for n in (half, third, bottom)):
            continue
        right = [i for i in range(4) if near(half[i], 50)]                   # left half: the right edge at 50
        left = [i for i in range(4) if near(third[i], 100 / 3)]               # middle third: 33 and 67
        if len(right) != 1 or len(left) != 1 or right[0] == left[0] or not near(third[right[0]], 200 / 3):
            continue
        ys = [i for i in range(4) if i not in (right[0], left[0])]
        top = [i for i in ys if near(bottom[i], 50)]                          # bottom half: its top edge at 50
        if len(top) != 1:
            continue
        b = next(i for i in ys if i != top[0])
        texts = _NUMS.findall(vals[2])
        pieces, pos, k = [], 0, 0
        for m in _NUMS.finditer(vals[2]):
            pieces.append(vals[2][pos:m.start()] + "{%d}" % k)
            pos, k = m.end(), k + 1
        return {"key": key, "template": "".join(pieces) + vals[2][pos:],
                "index": {"right": right[0], "left": left[0], "top": top[0], "bottom": b},
                "decimals": [_decimals(t) for t in texts], "top_full": half[top[0]]}
    return None


def curve_points(v, start: float | None = None, end: float | None = None) -> list[tuple[float, float]] | None:
    """A setting's glide as points over the effect: {"ramp": [a, b]} -> [(0, a), (1, b)];
    {"curve": [[t, y], ...]} -> those (t 0..1 of the effect); a plain value -> None.
    With "over": [t0, t1] (song seconds - a pin's whole span, 0.24.48) and the effect's start /
    end: the part of the glide inside the effect, as points over the effect."""
    pts = None
    if isinstance(v, dict) and isinstance(v.get("ramp"), (list, tuple)) and len(v["ramp"]) == 2:
        pts = [(0.0, float(v["ramp"][0])), (1.0, float(v["ramp"][1]))]
    elif isinstance(v, dict) and isinstance(v.get("curve"), (list, tuple)) and len(v["curve"]) >= 2:
        pts = [(float(t), float(y)) for t, y in v["curve"]]
    if pts is None or not v.get("over") or start is None or end is None or end <= start:
        return pts
    t0, t1 = (float(x) for x in v["over"])
    if t1 <= t0:
        return pts
    g = [(t0 + t * (t1 - t0), y) for t, y in pts]

    def at(T):
        if T <= g[0][0]:
            return g[0][1]
        for (a, ya), (b, yb) in zip(g, g[1:]):
            if T <= b:
                return ya if b <= a else ya + (yb - ya) * (T - a) / (b - a)
        return g[-1][1]
    inner = [((T - start) / (end - start), y) for T, y in g if start < T < end]
    return [(0.0, at(start))] + inner + [(1.0, at(end))]


class Curves:
    """xLights value curves as this version writes them (0.24.48), learned from the kit's three
    value-curve steps on one slider: a ramp lowest -> highest, the same highest -> lowest, then a
    custom curve with one point dragged to the top. From those:
      the key        the curve's setting is the slider's with its second word changed
                     (E_SLIDER_X -> E_VALUECURVE_X), and names of it inside the text follow
      start / end    the two numbers that swapped; the start is the one that was lowest first
      limits         numbers that stayed, equal to the lowest / highest: the curve stores real
                     values; else start / end are a share of the limits (0-100 or 0-1)
      points         the custom curve's field of x:y pairs, its separators, x's scale (the last
                     x) and y's (the point at the top: the highest value, 100 or 1)
    write() gives (key, text) for a curve over one effect, or None when it can't be written."""

    def __init__(self, first, down, custom):
        self.first, self.down, self.custom = first, down, custom
        f1, fd = dict(first["fields"]), dict(down["fields"])
        order = [n for n, _ in first["fields"]]               # xLights leaves a field at its default out
        for src in (down["fields"], (custom or {}).get("fields") or []):
            names = [n for n, _ in src]
            for i, n in enumerate(names):
                if n not in order:
                    nxt = next((m for m in names[i + 1:] if m in order), None)
                    order.insert(order.index(nxt) if nxt else len(order), n)
        self.order = order
        a, b = down["swapped"]
        lowest = float("-inf")
        val = lambda d, n: _num(d.get(n)) if _num(d.get(n)) is not None else lowest   # noqa: E731
        # the ramp down starts at the highest: its start is the one that is highest there
        self.start, self.end = (a, b) if val(fd, a) >= val(fd, b) else (b, a)
        i, j = self.order.index(self.start), self.order.index(self.end)
        if i > j:                                      # the start before the end, as xLights lists them
            self.order[i], self.order[j] = self.order[j], self.order[i]
        hi = max(x for x in (_num(f1.get(self.end)), _num(fd.get(self.start))) if x is not None)
        lo = next((x for x in (_num(f1.get(self.start)), _num(fd.get(self.end))) if x is not None), None)
        same = [n for n in order if n not in (a, b) and _num(f1.get(n)) is not None and fd.get(n) == f1.get(n)]
        self.hi_f = next((n for n in same if _num(f1[n]) == hi), None)
        rest = sorted((n for n in same if n != self.hi_f), key=lambda n: _num(f1[n]))
        self.lo_f = next((n for n in rest if lo is not None and _num(f1[n]) == lo), rest[0] if rest else None)
        self.real = self.hi_f is not None
        if not self.real:                              # shares: the limits are the two numbers that stayed
            self.lo_f, self.hi_f = (rest[0], rest[-1]) if len(rest) >= 2 else (None, None)
            self.share = hi or 100.0                   # what 'the highest' was written as (100 or 1)
        self.dec = _decimals(*[v for v in (f1.get(self.end), fd.get(self.start)) if v is not None]) or 2
        self.slider_dropped = bool(first.get("slider_dropped"))
        self.sep, self.trail = first["sep"], first["value"].endswith(first["sep"])
        own = first["key"].split("_", 1)[1]            # e.g. VALUECURVE_Bars_BarCount
        self.own = own
        sl = first.get("slider") or ""
        self.token = first["key"].split("_", 2)[1] if first["key"].count("_") >= 2 else None
        self.slider_token = sl.split("_", 2)[1] if sl.count("_") >= 2 else None
        self.type_f = (custom or {}).get("type_field")
        self.ramp_word = f1.get(self.type_f) if self.type_f else None
        if custom:
            fc = dict(custom["fields"])
            self.pf = custom["points_field"]
            raw = fc[self.pf]
            m = re.match(r"\s*-?[\d.]+(\D)-?[\d.]+(\D)?", raw)
            self.pair_sep = m.group(1) if m else ":"
            self.pt_sep = (m.group(2) if m and m.group(2) else ";")
            self.pt_trail = raw.endswith(self.pt_sep)
            from .kit import _points
            pts = _points(raw)
            self.x_scale = max(x for x, _ in pts) or 1.0
            top = max(y for _, y in pts)
            hi_c = _num(fc.get(self.hi_f)) if self.hi_f else None
            self.y_real = hi_c is not None and abs(top - hi_c) < 1e-6 and top not in (1.0, 100.0)
            self.y_scale = top or 1.0
            self.custom_word = fc.get(self.type_f) if self.type_f else None
            self.pdec = _decimals(*re.findall(r"-?\d+(?:\.\d+)?", raw)) or 2      # as written there

    @classmethod
    def learn(cls, structure: dict) -> "Curves | None":
        f, d = structure.get("value_curve"), structure.get("value_curve_down")
        if not f or not d or len(d.get("swapped") or []) != 2:
            return None
        try:
            return cls(f, d, structure.get("value_curve_custom"))
        except (KeyError, TypeError, ValueError):
            return None

    def key_for(self, key: str) -> str | None:
        parts = key.split("_", 2)
        if len(parts) != 3 or not self.token:
            return None
        return f"{parts[0]}_{self.token}_{parts[2]}"

    def write(self, key: str, pts: list[tuple[float, float]], bounds: list, dec: int) -> tuple[str, str] | None:
        """pts: [(t 0..1, real value)] -> (curve key, text). Two points: a ramp; more: a custom
        curve (when learned; else None - the exporter splits it into ramps)."""
        vk = self.key_for(key)
        if vk is None:
            return None
        lo = min([b for b in bounds if b is not None] + [y for _, y in pts])
        hi = max([b for b in bounds if b is not None] + [y for _, y in pts])
        if hi <= lo:
            hi = lo + 1.0
        ramp = len(pts) == 2 or (len(pts) > 2 and _straight(pts))
        if not ramp and not self.custom:
            return None
        tmpl = self.first if ramp else self.custom
        own = vk.split("_", 1)[1]
        out = []
        dd = max(dec, self.dec)

        def num(x, d=dd):
            return f"{x:.{d}f}"
        share = lambda y: (y - lo) / (hi - lo)      # noqa: E731
        tf = dict(tmpl["fields"])
        for n in self.order:
            if n not in tf and n not in (self.start, self.end):
                continue                                   # left out by xLights in this kind of curve
            v = str(tf.get(n, "")).replace(self.own, own)
            if n == self.lo_f:
                v = num(lo)
            elif n == self.hi_f:
                v = num(hi)
            elif n == self.start:
                y = pts[0][1]
                v = num(y) if self.real else num(share(y) * self.share)
            elif n == self.end:
                y = pts[-1][1]
                v = num(y) if self.real else num(share(y) * self.share)
            elif not ramp and n == self.pf:
                ys = [(y if self.y_real else share(y) * self.y_scale) for _, y in pts]
                v = self.pt_sep.join(f"{t * self.x_scale:.{self.pdec}f}{self.pair_sep}{yv:.{self.pdec}f}"
                                     for (t, _), yv in zip(pts, ys)) + (self.pt_sep if self.pt_trail else "")
            elif n == self.type_f and ramp and self.ramp_word:
                v = self.ramp_word
            out.append(f"{n}={v}")
        return vk, self.sep.join(out) + (self.sep if self.trail else "")


def _straight(pts) -> bool:
    (t0, y0), (t1, y1) = pts[0], pts[-1]
    if t1 <= t0:
        return False
    return all(abs(y0 + (y1 - y0) * (t - t0) / (t1 - t0) - y) < 1e-6 for t, y in pts)
