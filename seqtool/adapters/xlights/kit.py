# seqtool-inspect: xlights | inspect_xlights | learned xLights versions and their training data
# seqtool-command: xlights-kit | main | setup | teach seqtool your xLights version (one training file)
"""xLights reference-kit wizard (live, single file).

    seqtool xlights-kit [--dir DIR] [--update | --fresh]

Teaches seqtool how YOUR xLights version writes effects, one small step at a
time, using a single training file:

  1. you create an empty sequence in xLights and save it where the wizard says
     (this tells it your xLights version);
  2. for each step you add or change one effect in xLights and press Save;
     the wizard notices the save, checks the file at once, shows a check mark
     and moves on - or says what's wrong and waits for the next save.

For change steps it uses the right-most effect of that type and compares it
with the previous step and with the effect's defaults, so you can keep
editing the same effect or add a new copy each time. While waiting:
Enter = check now, s = skip step, b = back one step, a = accept anyway,
q = quit (progress is kept; run again to resume).

When seqtool adds kit steps (new effects, submodel rows), --update
(or answering yes when asked) runs only the new steps and merges them into
what was learned before.

Results go to seqtool-prefs/xlights-learned/<xLights version>/; afterwards the
training file can be deleted. Learned files are kept per xLights version, so
shipped (pre-learned) versions and your own can coexist.
"""
from __future__ import annotations

import argparse
import json
import re
import os
import shutil
import sys
import time
from pathlib import Path

from ...common import config
from ...common.log import good, info, warn
from ...common.paths import show
from ...common.prompt import ask, interactive
from . import xsq
from ...common.paths import arg as paths_arg

MANIFEST = Path(__file__).with_name("kit.json")
WORK_NAME = "seqtool-kit.xsq"


def manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def norm(name):  # kept for callers
    return xsq.norm(name)


def build_steps(known: dict | None = None) -> list[dict]:
    """All kit steps, or (known = an existing observations.json) only the ones it lacks.
    A missing setting of an effect that was learned still needs the 'add' step, so
    the change can be compared with the effect's defaults."""
    m = manifest()
    steps = [{"kind": "create"}]
    have_fx = {e.get("generic"): e for e in (known or {}).get("effects", {}).values()}
    have_st = set((known or {}).get("structure", {}))
    for e in m["effects"]:
        learned = have_fx.get(e["generic"], {}).get("params", {}) if known is not None else {}
        todo = [v for v in e["variants"] if v["param"] not in learned]
        if known is not None and e["generic"] in have_fx and not todo:
            continue
        steps.append({"kind": "add", "effect": e["effect"], "generic": e["generic"],
                      **({"on": e["on"]} if e.get("on") else {})})
        for v in (todo if known is not None else e["variants"]):
            steps.append({"kind": "change", "effect": e["effect"], "generic": e["generic"],
                          "param": v["param"], "do": v["do"]})
    for s in m["structure"]:
        if known is None or s["kind"] not in have_st:
            steps.append(dict(s))
    return steps


def mark_current(version: str) -> None:
    """A complete training made with an older kit (only wording changed since): record
    the current kit version, so it isn't reported as older any more."""
    d = config.user_dir() / "xlights-learned" / version
    f = d / "observations.json"
    if not f.exists():
        return
    obs = json.loads(f.read_text(encoding="utf-8"))
    if build_steps(obs)[1:]:
        return
    obs["kit_version"] = manifest()["kit_version"]
    f.write_text(json.dumps(obs, indent=2) + "\n", encoding="utf-8")


def missing_steps(version: str) -> tuple[dict | None, list[dict]]:
    """(observations, steps it lacks) for a learned version (steps exclude 'create')."""
    dirs = learned_dirs(version)
    if not dirs:
        return None, []
    obs = json.loads((dirs[0] / "observations.json").read_text(encoding="utf-8"))
    return obs, build_steps(obs)[1:]


STRUCTURE_LABELS = {"create": "New sequence", "palette": "Palette", "layers": "Layers", "group": "Groups",
                    "group_render": "Layer Settings", "rotation": "Layer Settings", "value_curve": "Value curves",
                    "value_curve_down": "Value curves", "value_curve_custom": "Value curves",
                    "timing": "Timing tracks", "submodel": "Submodels"}


def step_label(step: dict | None) -> str:
    """0.24.58: what a step is about - the effect's name, or the part of xLights it trains."""
    if not step:
        return ""
    return step.get("effect") or STRUCTURE_LABELS.get(step["kind"], step["kind"].replace("_", " ").capitalize())


def step_header(step: dict | None, i: int, n: int) -> str:
    """'Twinkle [35/79]'."""
    lab = step_label(step)
    return f"{lab} [{i}/{n}]" if lab else f"[{i}/{n}]"


def _text_param(generic: str | None, param: str | None) -> bool:
    """A step whose setting is a file path (param_map 'text' + 'path'): 0.24.58."""
    try:
        pm = json.loads((Path(__file__).with_name("param_map.json")).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return any(isinstance(sp, dict) and sp.get("text") == param and sp.get("path")
               for sp in (pm.get(generic or "") or {}).values())


def _pathy(v) -> bool:
    new = v[1] if isinstance(v, (list, tuple)) else v
    return isinstance(new, str) and bool(re.search(r"[\\/]|\.[A-Za-z0-9]{2,5}$", new.strip()))


def step_text(step: dict, work: Path, model: str | None) -> str:
    k = step["kind"]
    if k == "create":
        return ("In xLights: File > New Sequence > Animation (no audio); the defaults (30 s) are fine.\n"
                f"      Save it as: {show(work)}")
    if k == "add":
        if step.get("generic") == "dark":           # Off has nothing to set
            return f"Add an {step['effect']} effect to one model{f' (e.g. {model})' if model else ''}. Save."
        where = f"(e.g. {model})" if model else "(any pixel model; a matrix or tree lets you see each change)"
        if step.get("on"):                           # 0.24.58: the next steps need a certain kind of model
            where = f"({step['on']})"
        return f"Add {step['effect']} with its default settings to one model {where}. Save."
    if k == "change":
        return f"{step['effect']}: {step['do']}. Save."
    return step["do"] + " Save."


def _diff(a: dict, b: dict) -> dict:
    return {k: [a.get(k), b.get(k)] for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)}


def split_change(d: dict) -> tuple[dict, dict]:
    """(primary, companions). xLights adds or drops related settings when an
    option enables or hides extra controls (e.g. Bars 'expand' adds
    Bars_Center=0; Meteors 'Explode' adds X/Y offsets). Keys whose value
    changed are primary; keys that only appeared or disappeared are
    companions - written alongside the primary, never mistaken for it."""
    changed = {k: v for k, v in d.items() if v[0] is not None and v[1] is not None}
    other = {k: v for k, v in d.items() if k not in changed}
    if changed:
        return changed, other
    return d, {}                       # only appearances (e.g. a checkbox stored for the first time)


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _vc_fields(val) -> tuple[list, str] | None:
    """A value-curve-like setting: 3+ 'name=value' fields joined by one separator (not ',')."""
    if not isinstance(val, str) or "=" not in val:
        return None
    for sep in "|;~":
        parts = [p_ for p_ in val.strip(sep).split(sep) if p_]
        if len(parts) >= 3 and all("=" in p_ for p_ in parts):
            return [list(p_.split("=", 1)) for p_ in parts], sep
    return None


def _points(v) -> list[tuple[float, float]]:
    """'0.00:0.00;0.50:1.00;1.00:0.00' (any two separators) -> [(x, y)], 3+ points, x rising."""
    m = re.findall(r"(-?\d+(?:\.\d+)?)\s*[:,]\s*(-?\d+(?:\.\d+)?)", str(v))
    if len(m) < 3:
        return []
    pts = [(float(a), float(b)) for a, b in m]
    return pts if all(pts[i][0] <= pts[i + 1][0] for i in range(len(pts) - 1)) else []


def _sig(e: xsq.EffectInst) -> str:
    return f"{e.element}|{e.layer}|{e.name}|{e.start:.3f}|{e.end:.3f}"


def find_groups(work: Path) -> set[str] | None:
    """Group names from xlights_rgbeffects.xml near the training file (or the
    remembered show folder); None if no layout file is found."""
    import xml.etree.ElementTree as ET
    cands = [work.parent, *work.parent.parents][:4]
    remembered = config.answer("xlights_show_dir")
    if remembered:
        cands.insert(0, Path(remembered))
    for d in cands:
        f = Path(d) / "xlights_rgbeffects.xml"
        if f.exists():
            try:
                return {g.get("name") for g in ET.parse(f).getroot().iter("modelGroup")}
            except ET.ParseError:
                return None
    return None


class Session:
    """State machine: evaluate(xsq) checks the current step against a parsed file."""

    def __init__(self, work: Path, state: dict | None = None, known: dict | None = None):
        self.work = work
        self.known = known if known is not None else (state or {}).get("update_base")
        self.steps = build_steps(self.known)
        self.s = state or {"index": 0, "version": None, "model": None, "stored": {}, "defaults": {},
                           "last": {}, "observations": [], "structure": {}, "seen": [], "skipped": []}
        self.pending = None

    # -- helpers
    @property
    def index(self) -> int:
        return self.s["index"]

    @property
    def step(self) -> dict | None:
        return self.steps[self.index] if self.index < len(self.steps) else None

    def done(self) -> bool:
        return self.index >= len(self.steps)

    def advance(self, x: xsq.Xsq | None = None):
        if x is not None:
            self.s["seen"] = [_sig(e) for e in x.effects]
            self.s["snap"] = {_sig(e): e.settings for e in x.effects}     # 0.24.48: settings as they were
        self.s["index"] += 1
        self.pending = None

    def back(self):
        if self.s["index"] > 0:
            self.s["index"] -= 1
            self.s["observations"] = [o for o in self.s["observations"] if o["step"] < self.s["index"]]

    def skip(self):
        self.s["skipped"].append(self.index)
        self.advance()

    def next_choice(self) -> str | None:
        """0.24.51: several candidates (value curves) - the next one becomes the one 'a' takes."""
        ch = getattr(self, "choices", None)
        if not ch or not self.pending:
            return None
        i = next((j for j, c in enumerate(ch) if c[0] is self.pending[0]), -1)
        self.pending = ch[(i + 1) % len(ch)]
        return self.pending[0]["key"].split("_", 2)[-1]

    def accept_pending(self) -> bool:
        if not self.pending:
            return False
        obs, x = self.pending
        self._record(obs)
        self.advance(x)
        return True

    def _record(self, obs: dict):
        obs["step"] = self.index
        self.s["observations"] = [o for o in self.s["observations"] if o["step"] != self.index] + [obs]
        if obs.get("kind") == "change":
            self.s["last"][obs["effect"]] = obs["settings"]

    # -- the check
    def evaluate(self, x: xsq.Xsq) -> tuple[str, str]:
        """-> (status, message); status ok | wait | multi."""
        st = self.step
        k = st["kind"]
        if k == "create":
            if not x.version:
                return "wait", "saved, but no xLights version found in the file"
            if self.known and self.known.get("xlights_version") not in (None, x.version):
                return "wait", (f"this file is from xLights {x.version}, but the training being updated is for "
                                f"{self.known.get('xlights_version')} - use that version, or run without --update")
            self.s["version"] = x.version
            self.s["timing"] = x.timing
            self.s["timing_baseline"] = x.timing_tracks
            self._record({"kind": "create", "version": x.version, "timing": x.timing})
            self.advance(x)
            return "ok", f"xLights {x.version}, {x.timing or '?'} timing"
        if k == "add":
            new = [e for e in x.of(st["effect"]) if _sig(e) not in set(self.s["seen"])]
            if not new:
                newest_any = [e for e in x.of() if _sig(e) not in set(self.s["seen"])]
                if newest_any:
                    n = max(newest_any, key=lambda e: e.start)
                    return "wait", f"the new effect is '{n.name}', expected {st['effect']}"
                return "wait", f"no new {st['effect']} effect found yet"
            e = max(new, key=lambda e: (e.start, e.end))
            self.s["stored"][st["effect"]] = e.name
            self.s["defaults"][st["effect"]] = e.settings
            self.s["last"][st["effect"]] = e.settings
            self.s["model"] = self.s["model"] or e.element
            self._record({"kind": "add", "effect": st["effect"], "generic": st["generic"], "stored_name": e.name,
                          "model": e.element, "defaults": e.settings, "palette": e.palette})
            self.advance(x)
            stored = f", stored as '{e.name}'" if e.name != st["effect"] else ""
            return "ok", f"{st['effect']} on {e.element}{stored}"
        if k == "change":
            e = x.rightmost(st["effect"])
            if e is None:
                return "wait", f"no {st['effect']} effect in the file"
            d_prev = _diff(self.s["last"].get(st["effect"], {}), e.settings)
            d_def = _diff(self.s["defaults"].get(st["effect"], {}), e.settings)
            if not d_prev:                    # 0.24.58: which effect was looked at
                at = f"the right-most {st['effect']} (on {e.element}, at {e.start:.2f}s)"
                return "wait", (f"no change since the previous step in {at} - change it on that effect (or add a "
                                "copy further right), then save" if d_def else f"{at} still has default settings")
            if not d_def:                     # a choice set back to its default value is a valid change
                d = d_prev
            else:                             # prefer the comparison with the fewest primary changes, then fewest overall
                d = min((d_prev, d_def), key=lambda dd: (len(split_change(dd)[0]), len(dd)))
            primary, companions = split_change(d)
            if len(primary) > 1 and _text_param(st.get("generic"), st.get("param")):
                paths = [k_ for k_, v_ in primary.items() if _pathy(v_)]
                if len(paths) == 1:           # 0.24.58: choosing a file also switched a related option (Scaling)
                    companions = {**companions, **{k_: v_ for k_, v_ in primary.items() if k_ != paths[0]}}
                    primary = {paths[0]: primary[paths[0]]}
            short = lambda kv: ", ".join(f"{k.split('_', 2)[-1]} {v[0]}->{v[1]}" for k, v in kv.items())  # noqa: E731
            obs = {"kind": "change", "effect": st["effect"], "generic": st["generic"], "param": st["param"],
                   "do": st["do"], "primary": primary, "companions": companions, "settings": e.settings}
            if len(primary) > 1:
                self.pending = (obs, x)
                return "multi", f"{len(primary)} settings changed ({short(primary)}); expected one. " \
                                "Undo the extra change and save, or type a to accept"
            (key, (old, new)), = primary.items()
            wants_extreme = "maximum" in st["do"] or "minimum" in st["do"]
            blank = new is None or str(new).strip() == ""
            if wants_extreme and (blank or (_num(old) is not None and _num(new) is None)):
                return "wait", (f"{key.split('_', 2)[-1]} was saved as '{new}' (not a number) - xLights may blank the "
                                "field past a certain value. Use the highest value that still shows, then save")
            self._record(obs)
            self.advance(x)
            extra = f"  (+{len(companions)} related setting{'s' * (len(companions) > 1)})" if companions else ""
            return "ok", f"{key.split('_', 2)[-1]}: {old} -> {new}{extra}"
        if k == "palette":
            cands = [e for e in x.of("Color Wash")]
            for e in sorted(cands, key=lambda e: -e.start):
                cols = xsq.enabled_colors(e.palette)
                if sorted(cols) == ["#0000FF", "#00FF00", "#FF0000"]:
                    self._record({"kind": "palette", "palette": e.palette})
                    self.advance(x)
                    return "ok", "3-colour palette (red, green, blue)"
            if not cands:
                return "wait", "no Color Wash found"
            cols = xsq.enabled_colors(max(cands, key=lambda e: e.start).palette)
            return "wait", f"the right-most Color Wash has {len(cols)} colour(s) enabled: {', '.join(cols) or 'none'}"
        if k == "layers":
            multi = {el: n for el, n in x.layers.items() if n >= 2}
            if not multi:
                return "wait", "no model has effects on two layers yet"
            el = self.s["model"] if self.s["model"] in multi else sorted(multi)[0]
            self._record({"kind": "layers", "model": el, "layers": multi[el]})
            self.advance(x)
            return "ok", f"{el} has {multi[el]} layers"
        if k == "group":
            groups = find_groups(self.work)
            fresh = [e for e in x.of("Color Wash") if _sig(e) not in set(self.s["seen"])]
            if groups is not None:
                hit = [e for e in fresh if e.element in groups] or [e for e in x.of() if e.element in groups]
                if not hit:
                    return "wait", "no effect on a model group found" + \
                        (f" (new Color Wash is on {fresh[0].element}, which is not a group)" if fresh else "")
                e = hit[0]
            else:
                if not fresh:
                    return "wait", "no new Color Wash found"
                e = fresh[0]
            self._record({"kind": "group", "element": e.element, "verified": groups is not None})
            self.advance(x)
            return "ok", f"effect on {e.element}" + ("" if groups is not None else " (not verified as a group)")
        if k == "group_render":                       # 0.24.36: how a group effect says 'Per Model Default'
            groups = find_groups(self.work)
            cands = [e for e in x.of() if groups is None or e.element in groups]
            for e in sorted(cands, key=lambda e: -e.start):
                hit = [(key, v) for key, v in (e.settings or {}).items()
                       if isinstance(v, str) and v.strip().lower().startswith("per model")]
                if hit:
                    key, val = hit[0]
                    self._record({"kind": "group_render", "key": key, "per_model": val, "element": e.element})
                    self.advance(x)
                    return "ok", f"render style on {e.element}: {key.split('_', 2)[-1]} = {val}"
            return "wait", ("no effect on a model group with Render Style 'Per Model ...' yet (Layer Settings / "
                            "Buffer tab > Render Style)")
        if k in ("value_curve", "value_curve_down", "value_curve_custom"):
            return self._value_curve(x, k)
        if k == "rotation":                           # 0.24.48: a Layer Settings slider, on any effect
            snap = self.s.get("snap") or {}
            for e in sorted(x.effects, key=lambda e: -e.start):
                before = snap.get(_sig(e))
                if before is None:
                    continue
                d = {kk: vv for kk, vv in _diff(before, e.settings).items()
                     if _num(vv[1]) is not None and not _vc_fields(vv[1])}
                if len(d) == 1:
                    (key, (old_, new_)), = d.items()
                    self._record({"kind": "rotation", "key": key, "default": old_, "extreme": new_,
                                  "element": e.element})
                    self.advance(x)
                    return "ok", f"rotation on {e.element}: {key.split('_', 2)[-1]} {old_} -> {new_}"
                if len(d) > 1:
                    return "wait", (f"{len(d)} settings of the effect on {e.element} changed "
                                    f"({', '.join(kk.split('_', 2)[-1] for kk in d)}) - change only Rotation, and save")
            return "wait", "no effect's Rotation (Layer Settings, the Buffer tab) changed yet"
        if k == "timing":
            base = self.s.get("timing_baseline", {})
            new = {t: n for t, n in x.timing_tracks.items() if t not in base or n > base[t]}
            good_ = {t: n for t, n in new.items() if n >= 3}
            if not good_:
                found = ", ".join(f"'{t}' ({n} marks)" for t, n in x.timing_tracks.items()) or "none"
                return "wait", f"no new timing track with 3+ marks yet; timing tracks in the file: {found}"
            t, n = max(good_.items(), key=lambda kv: (kv[1], kv[0]))     # 0.24.58: the fullest new track
            self._record({"kind": "timing", "track": t, "marks": n})
            self.advance(x)
            others = [f"'{o}'" for o in sorted(good_) if o != t]
            return "ok", f"timing track '{t}' with {n} marks" + (f" (also new: {', '.join(others)})" if others else "")
        if k == "submodel":
            seen = set(self.s["seen"])
            subs = [e for e in x.effects if e.element_type == "submodel"]
            fresh = [e for e in subs if _sig(e) not in seen] or subs
            if not fresh:
                return "wait", "no effect on a submodel row yet (expand a model with submodels in the sequencer)"
            e = fresh[0]
            parent, sub = e.element.split("/", 1)
            tag, attrs = next(((t, a) for p_, t, a in x.sub_layers if p_ == parent), ("SubModelEffectLayer", {}))
            self._record({"kind": "submodel", "tag": tag,
                          "attrs": {k_: v for k_, v in attrs.items() if k_ not in ("name",)},
                          "display": x.display_children.get(parent, []), "example": e.element})
            self.advance(x)
            return "ok", f"effect on submodel row {e.element} (stored as <{tag}>)"
        return "wait", f"unknown step {k}"

    def _value_curve(self, x: xsq.Xsq, k: str) -> tuple[str, str]:
        """0.24.48: how this xLights version writes a value curve - learned from one curve the
        user edits three times (a ramp up, the same ramp down, a custom curve with a point at the
        top). Nothing about the text is assumed but that it is 'name=value' fields joined by one
        separator; which fields are the limits, the start / end and the points comes from what
        changed between the steps. 0.24.51: xLights leaves out a field at its default (a start
        at 0) and drops the slider's own setting while its curve is on - a field that comes or
        goes counts as changed, and the slider is the setting that went; only a curve that is
        new or changed since the last save counts (an effect may have others already)."""
        first = next((o for o in self.s["observations"] if o["kind"] == "value_curve"), None)
        prev = next((o for o in reversed(self.s["observations"]) if o["kind"].startswith("value_curve")), None)
        snap = self.s.get("snap") or {}
        if k == "value_curve":
            seen = set(self.s.get("vc_seen") or [])           # curves in the file at this step's earlier saves
            now, cands = [], []
            for e in sorted(x.effects, key=lambda e: -e.start):
                before = snap.get(_sig(e))
                for key, val in sorted(e.settings.items()):
                    f = _vc_fields(val)
                    if not f:
                        continue
                    now.append(f"{_sig(e)}|{key}|{val}")
                    if (before is not None and before.get(key) == val) or f"{_sig(e)}|{key}|{val}" in seen:
                        continue                                  # there before: not the one just made
                    if len([n for n, v in f[0] if _num(v) is not None]) < 2:
                        continue
                    tail = key.split("_", 2)[-1]
                    gone = [kk for kk in (before or {}) if kk not in e.settings and kk.split("_", 2)[-1] == tail]
                    slider = gone[0] if gone else next(
                        (kk for kk in e.settings if kk != key and kk.split("_", 2)[-1] == tail
                         and not _vc_fields(e.settings[kk])), None)
                    cands.append(({"kind": "value_curve", "key": key, "slider": slider, "value": val,
                                   "sep": f[1], "fields": f[0], "element": e.element,
                                   "slider_dropped": bool(gone), "slider_value": (before or {}).get(slider)}, bool(gone)))
            self.s["vc_seen"] = now
            cands.sort(key=lambda c: not c[1])                 # the one whose slider went first
            if not cands:
                return "wait", "no new value curve found yet (one made since the last step, on any effect)"
            obs = cands[0][0]
            tail = obs["key"].split("_", 2)[-1]
            if len(cands) > 1 and not (cands[0][1] and not cands[1][1]):
                self.pending = (obs, x)
                self.choices = [(c[0], x) for c in cands]
                names = ", ".join(c[0]["key"].split("_", 2)[-1] for c in cands)
                return "multi", (f"{len(cands)} new value curves ({names}) - type a to take {tail}, "
                                 "n for the next one")
            self._record(obs)
            self.advance(x)
            return "ok", f"a value curve on {obs['element']} ({tail})" + ("" if obs["slider"] else
                                                                         " - its slider was not found")
        for e in sorted(x.effects, key=lambda e: -e.start):
            for key, val in sorted(e.settings.items()):
                f = _vc_fields(val)
                if not f:
                    continue
                if first is None or key != first["key"] or e.element != first["element"] or val == prev["value"]:
                    continue
                old_f, nf = dict(prev["fields"]), dict(f[0])
                changed = [n for n in dict.fromkeys(list(old_f) + list(nf)) if old_f.get(n) != nf.get(n)]
                if k == "value_curve_down":
                    swap = [n for n in changed if _num(nf.get(n)) is not None or _num(old_f.get(n)) is not None]
                    if len(swap) != 2:
                        return "wait", (f"the curve changed in {len(changed)} place(s) "
                                        f"({', '.join(changed) or 'none'}); expected only its start and end swapped")
                    self._record({"kind": "value_curve_down", "key": key, "value": val, "fields": f[0], "swapped": swap})
                    self.advance(x)
                    return "ok", f"start and end: {swap[0]} and {swap[1]}"
                pts = [n for n, v in f[0] if _points(v)]
                if not pts:
                    return "wait", "no curve points found yet - Type 'Custom' and add a point in the middle"
                kind_f = next((n for n in changed if n in nf and n not in pts and _num(nf[n]) is None), None)
                self._record({"kind": "value_curve_custom", "key": key, "value": val, "fields": f[0],
                              "points_field": pts[0], "type_field": kind_f})
                self.advance(x)
                return "ok", f"custom curve: {len(_points(nf[pts[0]]))} points in {pts[0]}"
        return "wait", ("no new value curve found yet (one made since the last step, on any effect)" if k == "value_curve"
                        else "that value curve hasn't changed yet (the same effect, the same slider)")

    # -- results
    def results(self) -> dict:
        new = self._results()
        if not self.known:
            return new
        merged = json.loads(json.dumps(self.known))             # update: keep everything learned before
        for name, e in new["effects"].items():
            old = merged["effects"].get(name)
            if old:
                old["params"].update(e["params"])
            else:
                merged["effects"][name] = e
        merged.setdefault("structure", {}).update(new["structure"])
        merged["kit_version"] = new["kit_version"]
        merged["skipped_steps"] = new["skipped_steps"]
        return merged

    def _results(self) -> dict:
        obs = self.s["observations"]
        effects = {}
        for o in obs:
            if o["kind"] == "add":
                effects[o["effect"]] = {"generic": o["generic"], "stored_name": o["stored_name"],
                                        "defaults": o["defaults"], "params": {}}
        for o in obs:
            if o["kind"] == "change" and o["effect"] in effects:
                effects[o["effect"]]["params"][o["param"]] = {"do": o["do"], "primary": o["primary"],
                                                              "companions": o["companions"]}
        return {"kit_version": manifest()["kit_version"], "xlights_version": self.s["version"],
                "timing": self.s.get("timing"), "effects": effects,
                "structure": {o["kind"]: o for o in obs if o["kind"] in ("palette", "layers", "group", "group_render",
                                                                         "value_curve", "value_curve_down",
                                                                         "value_curve_custom", "rotation",
                                                                         "timing", "submodel")},
                "skipped_steps": self.s["skipped"]}


# ---------------------------------------------------------------- watching --
def _file_sig(p: Path):
    try:
        st = p.stat()
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _read_key_line(timeout: float) -> str | None:
    """A line typed by the user within `timeout` seconds, else None (non-blocking wait)."""
    if os.name == "nt":
        import msvcrt
        end = time.time() + timeout
        buf = getattr(_read_key_line, "buf", "")
        while time.time() < end:
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in "\r\n":
                    _read_key_line.buf = ""
                    print()
                    return buf
                buf += ch
                print(ch, end="", flush=True)
            time.sleep(0.05)
        _read_key_line.buf = buf
        return None
    import select
    r, _, _ = select.select([sys.stdin], [], [], timeout)
    if r:
        line = sys.stdin.readline()
        return line.strip() if line else "q"
    return None


def _mark(ok: bool) -> str:
    enc = (getattr(sys.stdout, "encoding", "") or "").lower()
    if os.name == "nt" and not os.environ.get("WT_SESSION"):     # 0.24.58: the old console's fonts lack the tick
        return "\u221a" if ok else "x"
    return ("\u2713" if ok else "\u2717") if "utf" in enc else ("OK" if ok else "X")


def _choices(ses, gui: bool = False) -> str:
    """0.24.58: the keys a step takes, said each time (a/n only while there is something to accept)."""
    c = ["Enter = check" if gui else "save in xLights (or Enter = check)", "s skip"]
    if ses.index > 0:
        c.append("b back")
    if ses.pending:
        c.append("a accept")
        if len(getattr(ses, "choices", None) or []) > 1:
            c.append("n next choice")
    c.append("q quit")
    return "(" + " \u00b7 ".join(c) + ")" if os.name != "nt" or os.environ.get("WT_SESSION") else "(" + ", ".join(c) + ")"


def live(kit_dir: Path, work: Path, fresh: bool = False, known: dict | None = None, gui: bool = False) -> bool:
    """The wizard. Terminal: it notices each save by itself (and reads keys as they come).
    GUI (0.24.2): no key watching there - each step asks; save in xLights, then Enter."""
    state_file = kit_dir / "kit-session.json"
    state = None
    if fresh:
        state_file.unlink(missing_ok=True)
        info("starting fresh at step 1" + (f" (saving the new sequence over {show(work)} replaces the old one)"
                                           if work.exists() else ""))
    if state_file.exists():
        prev = json.loads(state_file.read_text())
        if prev.get("index", 0) > 0 and ask(f"Resume the previous session at step {prev['index'] + 1}? [Y/n]",
                                            "y", show_default=False).lower() not in ("n", "no"):
            state = prev
    if state is not None and state.get("update_base") and known is None:
        known = state["update_base"]
    elif state is not None and known is not None and not state.get("update_base"):
        state = None                                   # a full session was saved; start the update afresh
    ses = Session(work, state, known)
    if known is not None:
        ses.s["update_base"] = known
        info(f"updating the training for xLights {known.get('xlights_version')}: "
             f"{len(ses.steps) - 1} new step(s); everything learned before is kept")
    n = len(ses.steps)
    print(f"\nTraining file: {show(work)}   ({n} steps; Enter = check now, s = skip, b = back, q = quit)")
    info(f"  relative paths are taken from the working folder: {os.getcwd()}")
    if gui:
        info("  in the GUI: after each save in xLights, press Enter here (seqtool then checks the file)")
    # fresh start: wait for a new save even if an old training file is there
    last_sig = _file_sig(work) if (ses.index > 0 or fresh) else None
    shown = -1
    while not ses.done():
        if shown != ses.index:
            print(f"\n{{head}}{step_header(ses.step, ses.index + 1, n)}{{/}} {{do}}{step_text(ses.step, work, ses.s['model'])}{{/}}")
            if not gui:                          # 0.24.58: the choices, on every step
                print(f"      {{note}}{_choices(ses)}{{/}}")
            shown = ses.index
        if gui:
            from ...common.prompt import Cancelled
            try:
                key = ask(f"{step_header(ses.step, ses.index + 1, n)} saved? {_choices(ses, gui=True)}",
                          "", show_default=False).strip()
            except Cancelled:
                key = "q"
            shown = -1 if key.lower() == "b" else shown
        else:
            key = _read_key_line(0.4)
        check = False
        if key is not None:
            k = key.lower()
            if k == "q":
                state_file.write_text(json.dumps(ses.s, indent=1))
                info(f"stopped at step {ses.index + 1}/{n}; run 'seqtool xlights-kit' to resume")
                return False
            if k == "s":
                warn(f"  skipped step {ses.index + 1}")
                ses.skip()
            elif k == "b":
                ses.back()
                shown = -1
            elif k == "a":
                if not ses.accept_pending():
                    info("  nothing to accept")
            elif k == "n":
                nm = ses.next_choice()
                info(f"  a now takes {nm}" if nm else "  nothing to choose from")
            else:
                check = True
        sig = _file_sig(work)
        if gui and check:
            last_sig = sig
        elif sig is not None and sig != last_sig:
            time.sleep(0.3)                      # let xLights finish writing
            if _file_sig(work) != sig:
                continue
            last_sig = sig
            check = True
        if check:
            if not work.exists():
                warn(f"  {show(work)} not found yet")
                continue
            try:
                x = xsq.read(work)
            except Exception as e:  # half-written or not an xsq
                warn(f"  can't read the file yet ({e.__class__.__name__})")
                continue
            status, msg = ses.evaluate(x)
            if status == "ok":
                good(f"  {_mark(True)} {msg}")
            else:
                warn(f"  {_mark(False)} {msg}")
                if status == "multi" and not gui:
                    print(f"      {{note}}{_choices(ses)}{{/}}")
            state_file.write_text(json.dumps(ses.s, indent=1))
    finish(ses, kit_dir, work, state_file)
    return True


def learned_dirs(version: str | None) -> list[Path]:
    """Where learned encodings for an xLights version are looked up, best first:
    the user's own (seqtool-prefs/xlights-learned/<v>), then shipped ones."""
    roots = [config.user_dir() / "xlights-learned", Path(__file__).with_name("learned")]
    if not version:
        return []
    return [r / version for r in roots if (r / version).is_dir()]


def learned_versions() -> list[str]:
    roots = [config.user_dir() / "xlights-learned", Path(__file__).with_name("learned")]
    return sorted({d.name for r in roots if r.is_dir() for d in r.iterdir()
                   if (d / "observations.json").exists()})


def finish(ses: Session, kit_dir: Path, work: Path, state_file: Path) -> Path:
    res = ses.results()
    ver = res["xlights_version"] or "unknown"
    out = config.user_dir() / "xlights-learned" / ver
    out.mkdir(parents=True, exist_ok=True)
    (out / "observations.json").write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8")
    if work.exists():
        shutil.copy2(work, out / "reference.xsq")          # skeleton for the exporter
    good(f"kit complete for xLights {ver}: {show(out / 'observations.json')}")
    if ses.s.get("skipped"):                                     # 0.24.58: which, and how to come back to them
        names = list(dict.fromkeys(step_header(ses.steps[i], i + 1, len(ses.steps)) for i in ses.s["skipped"]
                                   if i < len(ses.steps)))
        warn(f"  {len(names)} step(s) skipped: {', '.join(names)} - 'xlights-kit --update' learns them later")
    if state_file.exists():
        state_file.unlink()
    fseqs = fseq_files(work)
    if (work.exists() or fseqs) and ask(
            f"Delete the training file {show(work)} (and its xLights backups"
            + (", and its fseq" if len(fseqs) == 1 else f", and its {len(fseqs)} fseq files" if fseqs else "") + ")? [Y/n]",
            "y", show_default=False).lower() not in ("n", "no"):
        for f in [work, *work.parent.glob(work.stem + "*.xbkp"), *fseqs]:
            f.unlink(missing_ok=True)
        info("  deleted")
    return out


def fseq_files(work: Path) -> list[Path]:
    """The .fseq files xLights rendered from the training file (0.19.4): next to it, or
    in a folder of fseq files beside it or in the show folder (xLights' FSEQ folder
    setting lives outside the layout, so the usual places are looked at)."""
    folders = [work.parent, work.parent / "fseq", work.parent / "FSEQ"]
    try:
        from ...layout import store
        src = store.source_info()
        if src:
            show_dir = Path(src["path"]).parent
            folders += [show_dir, show_dir / "fseq", show_dir / "FSEQ"]
    except Exception:  # noqa: BLE001
        pass
    out = []
    for d in dict.fromkeys(folders):
        f = d / (work.stem + ".fseq")
        if f.is_file() and f not in out:
            out.append(f)
    return out


def run(kit_dir: Path | None = None, interactive_mode: bool | None = None, fresh: bool = False,
        update: bool | None = None, redo: list[str] | None = None) -> bool:
    from ...common.prompt import gui_asker, terminal
    gui = interactive_mode is None and gui_asker() is not None      # 0.24.2: the wizard runs in the GUI too
    live_ok = (terminal() or gui) if interactive_mode is None else interactive_mode
    vers = learned_versions()
    if not live_ok:
        info("xLights kit: " + (f"learned for xLights {', '.join(vers)}" if vers else "nothing learned yet"))
        work = (kit_dir or Path("xlights-kit")) / WORK_NAME
        steps = build_steps()
        if vers and not fresh:                       # what the training lacks, not every step (0.24.2)
            from .encoding import find
            enc = find()
            todo = missing_steps(enc.version)[1] if enc else []
            if todo:
                info(f"  the training lacks {len(todo)} step(s); --update learns only these (step 1 starts a new empty "
                     "sequence) - run 'xlights-kit --update' in the GUI's console or at the seqtool> prompt:")
                steps = build_steps(missing_steps(enc.version)[0])
            elif update:
                info("  nothing new to learn")
                return True
        for i, st in enumerate(steps, 1):
            print(f"  {i:>2}. {step_text(st, work, None)}")
        return bool(vers)
    known = None
    if vers:
        from .encoding import find
        enc = find()
        status, msg = enc.compatibility() if enc else ("ok", "")
        obs, todo = missing_steps(enc.version) if enc else (None, [])
        if redo and obs is not None:
            obs, gone = forget_steps(obs, redo)
            if not gone:
                raise SystemExit(f"--redo {' '.join(redo)}: no such learned step - e.g. 'xlights-kit --redo Faces.timing_track' "
                                 "('inspect xlights' lists what was learned)")
            todo = build_steps(obs)[1:]
            info(f"  learning again: {', '.join(gone)}")
        info(f"already learned for xLights {', '.join(vers)} ({msg})"
             + (f"; {len(todo)} step(s) still to learn: {todo_names(todo)}" if todo and not fresh else ""))
        if fresh:
            info("  --fresh: every step again; the result replaces what was learned for this version")
        if todo and update is not False and not fresh:
            if update or ask(f"Learn only the {len(todo)} step(s) the training for xLights {enc.version} doesn't have "
                             f"yet (new effects, submodel rows)? [Y/n]", "y",
                             show_default=False).lower() not in ("n", "no"):
                known = obs
        elif update:
            mark_current(enc.version)
            good(f"nothing new to learn for xLights {enc.version}: the training is complete "
                 f"(now marked as kit v{manifest()['kit_version']})")
            return True
        if known is None:
            info("a full run adds or replaces a version")
    if kit_dir is None:
        from ...common.paths import expand
        kit_dir = expand(ask("Folder for the training file (it can be your xLights show folder; Tab completes)",
                             config.answer("kit_dir", "xlights-kit"), complete="dir"), "dir").resolve()
        config.remember("kit_dir", str(kit_dir))
    kit_dir.mkdir(parents=True, exist_ok=True)
    return live(kit_dir, kit_dir / WORK_NAME, fresh, known, gui=gui)


def todo_names(todo: list[dict]) -> str:
    """'Pictures (3 settings), Timing tracks' - the steps a training lacks, by what they are about."""
    out: dict[str, int] = {}
    for st in todo:
        lab = step_label(st)
        out[lab] = out.get(lab, 0) + (st["kind"] == "change")
    return ", ".join(f"{k} ({v} setting{'s' * (v != 1)})" if v else k for k, v in out.items())


def at_start(argv: list[str]) -> tuple[str, str]:
    """For 'start' (0.24.47): ('skip', why) when there is nothing to do - no layout yet, or the
    training is complete - else ('ask', what is lacking): run it where someone can answer."""
    try:
        from ...layout import store
        if not store.source_info():
            return "skip", "no layout yet"
    except Exception:  # noqa: BLE001
        return "skip", "no layout yet"
    vers = learned_versions()
    if not vers:
        return "ask", "nothing has been learned about your xLights version yet - run xlights-kit"
    from .encoding import find
    enc = find()
    todo = missing_steps(enc.version)[1] if enc else []
    if not todo:
        return "skip", "the training is complete"
    return "ask", (f"the xLights training for {enc.version} lacks {len(todo)} step(s) ({todo_names(todo)}) - "
                   "run xlights-kit --update (in the GUI's console or at the seqtool> prompt)")


def offer(context: str = "export") -> bool:
    """When the xLights training is missing or lacks steps, ask whether to run the wizard
    now (terminal only - it watches keys and files). Returns True if a usable training exists after."""
    from ...common.prompt import gui_asker, interactive, terminal
    vers = learned_versions()
    todo, ver = [], None
    if vers:
        from .encoding import find
        enc = find()
        ver = enc.version if enc else None
        todo = missing_steps(ver)[1] if ver else []
        if not todo:
            return True
    what = (f"the xLights training for {ver} lacks {len(todo)} step(s) ("
            + ", ".join(dict.fromkeys(st.get("effect") or st["kind"] for st in todo if st["kind"] != "change"))
            + ")") if vers else "nothing has been learned about your xLights version yet"
    if gui_asker() is not None or not interactive() or not terminal():
        (info if vers else warn)(f"  {what} - run {{do}}xlights-kit{' --update' if vers else ''}{{/}} "
                                 "(in the GUI's console or at the seqtool> prompt)")
        return bool(vers)
    ans = ask(f"{what[0].upper() + what[1:]}. Run the training wizard now, before the {context}? [Y/n]", "y",
              remember_as=f"kit_offer_{context}", show_default=False)
    if ans.lower() in ("n", "no"):
        if vers:
            info("  continuing with what was learned; effects it lacks are not used "
                 "({do}xlights-kit --update{/} later)")
        return bool(vers)
    run(update=True if vers else None)
    return bool(learned_versions())


def inspect_xlights(args) -> list[str]:
    from .encoding import Encoding
    roots = [("yours", config.user_dir() / "xlights-learned"), ("shipped", Path(__file__).with_name("learned"))]
    out = []
    for label, root in roots:
        for d in sorted(root.iterdir()) if root.is_dir() else []:
            if not (d / "observations.json").exists():
                continue
            enc = Encoding.load(d)
            n_steps = sum(len(e["params"]) for e in enc.effects.values())
            out.append(f"xLights {enc.version}  ({label}): {len(enc.effects)} effects, "
                       f"{n_steps} learned settings, template {'yes' if enc.reference else 'no'}")
            out.append(f"  training: {enc.compatibility()[1]}")
            out.append("  value curves: " + ("not learned yet ('xlights-kit --update')" if not enc.curves else
                                             ("ramps and custom curves" if enc.curves.custom else "ramps"))
                       + "; rotation: " + (enc.rotation["key"] if enc.rotation else "not learned yet"))
            out.append("  effects: " + ", ".join(e["stored_name"] for e in enc.effects.values()))
            from .encoding import param_map
            pm = param_map()
            notes = [f"{e['stored_name']} {kp}: {st.note}" for gen, e in enc.effects.items()
                     for kp in e["params"] for st in [enc.step(gen, kp, pm)] if st and st.note]
            for n in notes:
                out.append(f"  assumed: {n}")
            for p in enc.problems():
                out.append(f"  problem: {p}")
            out.append(f"  folder:  {show(d)}")
    kd = config.answer("kit_dir")
    if kd and (Path(kd) / "kit-session.json").exists():
        st = json.loads((Path(kd) / "kit-session.json").read_text())
        out.append(f"training in progress: step {st.get('index', 0) + 1}/{len(build_steps())} "
                   f"in {show(Path(kd) / WORK_NAME)}  (xLights {st.get('version') or '?'})")
    return out or ["nothing learned yet - run: seqtool xlights-kit"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool xlights-kit", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", type=paths_arg, default=None, help="folder for the training file (asked if omitted)")
    ap.add_argument("--fresh", action="store_true", help="forget saved progress and start at step 1")
    ap.add_argument("--update", action="store_true",
                    help="learn only what the existing training lacks (after a seqtool update adds steps)")
    ap.add_argument("--redo", metavar="[EFFECT.]STEP", action="append", default=[],
                    help="learn these steps again, as with --update (e.g. --redo Faces.timing_track)")
    a = ap.parse_args(argv)
    return 0 if run(a.dir, fresh=a.fresh, update=True if (a.update or a.redo) else None, redo=a.redo) else 1


def forget_steps(obs: dict, redo: list[str]) -> tuple[dict, list[str]]:
    """0.24.18: observations without the named change steps ('Faces.timing_track' or 'timing_track'),
    so --update asks for them again. (copy, the steps taken out)"""
    obs = json.loads(json.dumps(obs))
    gone = []
    for want in redo:
        eff, _, par = want.rpartition(".")
        for name, e in (obs.get("effects") or {}).items():
            if eff and name.lower() != eff.lower():
                continue
            for k in [k for k in (e.get("params") or {}) if k.lower() == par.lower()]:
                e["params"].pop(k)
                gone.append(f"{name}.{k}")
    return obs, gone


if __name__ == "__main__":
    sys.exit(main())
