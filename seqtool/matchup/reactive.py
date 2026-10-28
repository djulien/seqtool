"""Music-reactive targets: effects triggered by musical events instead of chosen per section.

A *preset* (preferences/presets.json, 'help presets') says:

    on          the triggering event: beat | downbeat | onset | section | lyric | word, or
                with stems ('run --stems', 0.22.0): kick | snare | hat (drum hits),
                bass (bass notes), melody (melody notes) - any event list in music.json;
                sung (0.24.0): each passage the prop's voice sings (lyric lines, from a little
                before to a little after, close ones joined - faces.json 'sing')
    when        optional conditions on the music at that moment (all must hold), e.g.
                {"section": ["chorus", "drop"], "energy": ">=0.6", "downbeat": true, "beat": [1, 3]}
    every       optional: use only every Nth matching event
    keyframes   optional, CSS-style: {"0%": {...}, "37.5%": {...}} steps at any point of the
                event, for syncopation; glides with animation-timing-function (keyframes.py)
    split       optional: divide each event into N equal steps (on downbeat with split 8 =
                eighth notes in a 4/4 bar); 'step' counts them from the start of the bar
    effect      a generic effect (effects.json), e.g. pulse, chase, color_wash, sparkles
    params      effect parameters; each is a constant, or
                  {"from": "energy", "range": [lo, hi]}  driven by the music at that moment
                  {"if": {...conditions...}, "then": A, "else": B}
                  {"cycle": [A, B, ...]}                 next value on each event
                  {"step": [A, B, ...]}                  by position in the bar (a step sequencer)
    palette     base | accent (or an "if")
    colors      "cycle": one colour per event, stepping through the base palette
                (or {"cycle": "accent"}); {"from": "height"} picks the palette colour by a
                value 0..1 (low = first colour), e.g. how high a melody note is
    max_length  optional cap in seconds (an event otherwise lasts until the next one)
    "auto"      a parameter given as "auto" takes the prop's own setting (0.24.0): face (the
                face 'face use' gave it), track (its voice's timing track), area (where on
                the prop - several faces on one matrix)

A target can use one preset or a list. Like conditional formatting, earlier
presets win: a later preset's event that starts inside an earlier preset's
event is dropped, and one that runs into it is cut short.

Values a condition or "from" can use at the moment of an event:
    energy, energy_end (at the end of the event), onset, brightness, ... (any
    analysed *_norm field, without the suffix), downbeat (true/false), beat
    (beat number in the bar, 1 = first), bar (bar number), section (its type),
    section_index, time (seconds), index (event number for this preset), lyric and
    word (the current text, with imported lyrics; test with "~regex"), step
    (position in the bar: beat number - 1, times split, plus the split part);
    with stems: vocal, drums, bassline, other (each part's level 0..1), melody (how
    high the tune is, 0..1), and from the event itself: strength, and for bass and
    melody notes midi (the pitch; 60 = middle C), note ("E4"), height (0..1 within the
    song's range) and, for melody, source (vocals | other)
"""
from __future__ import annotations

import json
import re

import numpy as np

MODES = ("beat", "downbeat", "onset", "energy")       # the original built-in presets
STEM_TRIGGERS = ("kick", "snare", "hat", "bass", "melody")     # events from the stems (0.22.0)
CALL_TRIGGERS = ("call", "response", "call_phrase", "response_phrase", "pair")   # from tagged cues (0.24.49)
TRIGGERS = ("beat", "downbeat", "onset", "section", "lyric", "word", "sung", "cue") + STEM_TRIGGERS   # cue: yours (0.24.18)
STEM_LEVELS = ("vocal", "drums", "bassline", "other")           # level fields without a _norm suffix
WHY = {"cue": "your cue ('cue add')", "sung": "singing", "onset": "note onset", "section": "start of a section", "lyric": "lyric line", "word": "lyric word",
       "kick": "kick drum", "snare": "snare", "hat": "hi-hat", "bass": "bass note", "melody": "melody note"}
_CMP = re.compile(r"^\s*(>=|<=|!=|==|>|<)\s*(-?[\d.]+)\s*$")


def onsets(music: dict, threshold: float = 0.5, min_gap: float = 0.12) -> list[float]:
    """Note onsets: local peaks of the onset curve above `threshold`, at least `min_gap` apart."""
    an = music["analysis"]
    f = an["frames"]["fields"].get("onset_norm")
    if not f:
        return []
    x, dt = np.asarray(f), an["frame_interval"]
    peaks = [i for i in range(1, len(x) - 1) if x[i] >= threshold and x[i] >= x[i - 1] and x[i] > x[i + 1]]
    out: list[float] = []
    for i in peaks:
        t = i * dt
        if not out or t - out[-1] >= min_gap:
            out.append(round(t, 3))
    return out


def load_presets(presets: dict | None = None) -> dict:
    if presets is not None:
        return presets.get("presets", presets)
    from ..common.config import load
    return load("presets").get("presets", {})


_WORDS = re.compile(r"^(?P<base>[^\[\]@]+)(?:@(?P<on>[a-z]+))?(?:\[(?P<words>[^\]]*)\])?$")


def get_preset(presets: dict, name: str) -> dict | None:
    """A preset by name, or one made from a preset (0.24.25, the general form):
        NAME@TRIGGER   its look, on another event - spoke-bounce@word, beat-chase@kick
        NAME[w1|w2]    only on those sung words (0.24.24): an event counts where the word sung
                       then (the line, for lyric lines) holds one of them (whole words, any case)
        NAME@word[star|night]   both"""
    p = presets.get(name)
    if p is not None:
        return p
    m = _WORDS.match(name or "")
    if not m or m["base"] not in presets or (m["on"] is None and m["words"] is None):
        return None
    out = dict(presets[m["base"]])
    help_ = out.get("help") or "a preset"
    if m["on"]:
        if m["on"] not in TRIGGERS:
            return {**out, "on": m["on"]}                  # check() says what is wrong with it
        out["on"] = m["on"]
        help_ += f" - on each {WHY.get(m['on'], m['on'])} instead"
    if m["words"] is not None:
        words = [w.strip() for w in m["words"].split("|") if w.strip()]
        out["_words"] = words
        help_ += f" - only on: {', '.join(words)}"
    out["help"] = help_
    return out


def with_words(name: str, words: list[str] | None = None, on: str | None = None) -> str:
    """'word-flash', ['star', 'night'] -> 'word-flash[star|night]'; on='word' -> 'NAME@word[...]'"""
    m = _WORDS.match(name)
    base, on0, w0 = (m["base"], m["on"], m["words"]) if m else (name, None, None)
    on = on or on0
    if words is None:
        ws = [x for x in (w0 or "").split("|") if x] if w0 is not None else None
    else:
        ws = [w.strip().replace("|", "").replace(",", "").replace("[", "").replace("]", "") for w in words]
        ws = [w for w in ws if w]
    return base + (f"@{on}" if on else "") + (f"[{'|'.join(ws)}]" if ws else "")


def _word_hit(p: dict, trig: str, ctx: dict) -> bool:
    ws = p.get("_words")
    if not ws:
        return True
    text = (ctx.get("lyric") if trig == "lyric" else ctx.get("word")) or ""
    return any(re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", text, re.I) for w in ws)


def names_of(react) -> list[str]:
    """'a,b' or ['a', 'b'] or 'a' -> ['a', 'b']"""
    if isinstance(react, (list, tuple)):
        return [str(x).strip() for x in react if str(x).strip()]
    return [x.strip() for x in str(react or "").split(",") if x.strip()]


def check(react, presets: dict, effects: dict | None = None) -> list[str]:
    """Problems with a react setting (unknown preset, trigger or effect)."""
    out = []
    for n in names_of(react):
        p = get_preset(presets, n)
        if p is None:
            out.append(f"unknown preset {n!r} (see 'presets')")
            continue
        if p.get("on") not in TRIGGERS:
            out.append(f"preset {n!r}: 'on' must be one of {', '.join(TRIGGERS)}")
        if effects is not None and p.get("effect") not in effects:
            out.append(f"preset {n!r}: unknown effect {p.get('effect')!r}")
    return out


def test(cond: dict | None, ctx: dict) -> bool:
    for key, want in (cond or {}).items():
        have = ctx.get(key)
        if isinstance(want, bool):
            ok = bool(have) == want
        elif isinstance(want, list):
            ok = have in want
        elif isinstance(want, str) and want.startswith("~"):
            ok = have is not None and re.search(want[1:], str(have)) is not None
        elif isinstance(want, str) and _CMP.match(want):
            op, num = _CMP.match(want).groups()
            if have is None:
                return False
            num, have = float(num), float(have)
            ok = {">": have > num, "<": have < num, ">=": have >= num, "<=": have <= num,
                  "==": have == num, "!=": have != num}[op]
        else:
            ok = have == want
        if not ok:
            return False
    return True


def value(spec, ctx: dict, idx: int):
    if isinstance(spec, dict):
        if "if" in spec:
            return value(spec.get("then") if test(spec["if"], ctx) else spec.get("else"), ctx, idx)
        if "step" in spec:
            seq = spec["step"]
            return seq[int(ctx.get("step") or 0) % len(seq)] if seq else None
        if "cycle" in spec:
            seq = spec["cycle"]
            return seq[idx % len(seq)] if seq else None
        if "from" in spec:
            x = float(ctx.get(spec["from"], 0.0) or 0.0)
            lo, hi = spec.get("range", [0.0, 1.0])
            return round(lo + (hi - lo) * x, 3)
    return spec


class _Music:
    """What a preset can look at, at any moment of the song."""

    def __init__(self, music: dict, profile: dict, lyrics: dict | None = None, extra: dict | None = None):
        self.extra = extra or {}
        self.lyrics = lyrics
        from ..music.rhythm import beat_numbers
        self.lines = list((lyrics or {}).get("lines", []))
        self.words = [w for ln in self.lines for w in ln.get("words", [])]
        an = music["analysis"]
        self.dur = music["audio"]["duration"]
        self.beats = [b["time"] for b in an["events"]["beats"]]
        self.downs = sorted(round(d["time"], 3) for d in an["events"].get("downbeats", []))
        self.down_set = set(self.downs)
        self.beat_no = dict(zip((round(t, 3) for t in self.beats),
                                beat_numbers(an["events"]["beats"], an["events"].get("downbeats", []))))
        self.fields = an["frames"]["fields"]
        self.dt = an["frame_interval"]
        self.secs = profile["sections"]
        self._onsets = None
        self.music = music
        self.cues = sorted((c for c in (self.extra.get("_cues") or []) if 0 <= float(c["t"]) < self.dur),
                           key=lambda c: c["t"])

    def beat_len(self, t: float) -> float:
        """The beat's length around t (for a cue with no length of its own)."""
        import bisect
        b = self.beats
        if len(b) < 2:
            return 0.5
        i = min(max(bisect.bisect_right(b, t), 1), len(b) - 1)
        return max(0.05, b[i] - b[i - 1])

    def field(self, name: str, t: float) -> float:
        f = self.fields.get(name + "_norm") or self.fields.get(name)
        if not f:
            return 0.0
        return float(f[min(max(int(t / self.dt), 0), len(f) - 1)])

    def section(self, t: float) -> dict:
        return next((s for s in self.secs if s["start"] <= t < s["end"]), self.secs[-1])

    def times(self, trigger: str) -> list[float]:
        if trigger == "beat":
            return self.beats
        if trigger == "downbeat":
            return self.downs
        if trigger == "onset":
            if self._onsets is None:
                self._onsets = onsets(self.music)
            return self._onsets
        if trigger == "section":
            return [s["start"] for s in self.secs]
        if trigger == "lyric":
            return [ln["start"] for ln in self.lines]
        if trigger == "word":
            return [w["start"] for w in self.words]
        if trigger == "sung":
            return [a for a, _ in self.sung()]
        if trigger == "cue":
            return [float(c["t"]) for c in self.cues]
        if trigger in CALL_TRIGGERS:                       # 0.24.49: call and response (calls.py)
            return [e["time"] for e in self.call_events(trigger)]
        return [e["time"] for e in self.events(trigger)]

    def call_events(self, kind: str) -> list[dict]:
        if not hasattr(self, "_calls"):
            from .calls import derive
            self._calls = derive(self.music, {"sections": self.secs}, self.cues, None)
        return [e for e in self._calls if e["kind"] == kind]

    def sung(self) -> list[tuple[float, float]]:
        if not hasattr(self, "_sung"):
            from ..music.voices import sung_spans
            from ..common.config import load
            cfg = load("faces").get("sing", {})
            self._sung = sung_spans(self.lyrics, self.extra.get("voice"), float(cfg.get("lead", 0.15)),
                                    float(cfg.get("tail", 0.25)), float(cfg.get("join", 1.0)), self.dur)
        return self._sung

    def events(self, trigger: str) -> list[dict]:
        """Any other event list in music.json (kick, snare, hat, bass, melody ...)."""
        return self.music["analysis"]["events"].get(trigger) or []

    def own_end(self, trigger: str, i: int) -> float | None:
        if trigger in CALL_TRIGGERS:
            ev = self.call_events(trigger)
            return ev[i]["end"] if i < len(ev) else None
        if trigger == "lyric":
            return self.lines[i].get("end")
        if trigger == "word":
            return self.words[i].get("end")
        if trigger == "sung":
            return self.sung()[i][1]
        if trigger == "cue":
            c = self.cues[i]
            nxt = self.cues[i + 1]["t"] if i + 1 < len(self.cues) else self.dur
            return min(float(c["t"]) + float(c.get("len") or self.beat_len(float(c["t"]))), nxt, self.dur)
        ev = self.events(trigger)
        return ev[i].get("end") if trigger not in ("beat", "downbeat", "onset", "section") and i < len(ev) else None

    def event_info(self, trigger: str, i: int) -> dict:
        """What the event itself says (strength; a note's midi, note, height, source)."""
        if trigger in CALL_TRIGGERS:
            ev = self.call_events(trigger)
            return {k: v for k, v in ev[i].items() if k in ("pair", "derived")} if i < len(ev) else {}
        if trigger in ("beat", "downbeat", "onset", "section", "lyric", "word", "sung", "cue"):
            return {}
        ev = self.events(trigger)
        return {k: v for k, v in ev[i].items() if k not in ("time", "end")} if i < len(ev) else {}

    def lyric_at(self, t: float) -> tuple[str | None, str | None]:
        ln = next((x for x in self.lines if x["start"] <= t + 1e-3 < (x.get("end") or 1e9)), None)
        w = next((x for x in self.words if x["start"] <= t + 1e-3 < (x.get("end") or 1e9)), None)
        return (ln or {}).get("text"), (w or {}).get("text")

    def context(self, t: float, end: float, idx: int) -> dict:
        s = self.section(t)
        bar = sum(1 for d in self.downs if d <= t + 1e-3)
        ctx = {k[:-5]: None for k in self.fields if k.endswith("_norm")}
        ctx.update({k: None for k in STEM_LEVELS if k in self.fields})
        ctx = {k: self.field(k, t) for k in ctx}
        ctx.update({"energy": self.field("energy", t), "energy_end": self.field("energy", end - 1e-3),
                    "downbeat": round(t, 3) in self.down_set, "beat": self.beat_no.get(round(t, 3)),
                    "bar": bar, "section": s.get("type"), "section_index": s.get("index", 0),
                    "time": t, "index": idx})
        if self.lines:
            ctx["lyric"], ctx["word"] = self.lyric_at(t)
        return ctx


def _events(name: str, p: dict, m: _Music, palettes: dict, effects: dict | None) -> list[dict]:
    trig = p["on"]
    pts = m.times(trig)
    out, kept = [], 0
    for i, t in enumerate(pts):
        own = m.own_end(trig, i)
        if trig == "section":
            end = m.section(t)["end"]
        elif own:
            end = own
        else:
            end = pts[i + 1] if i + 1 < len(pts) else min(m.dur, t + 0.5)
        if p.get("max_length"):
            end = min(end, t + float(p["max_length"]))
        ctx = {**m.context(t, end, kept), **m.event_info(trig, i)}
        if trig == "lyric" or p.get("_words"):
            if trig == "lyric" and m.lines and i < len(m.lines):
                ctx["lyric"] = m.lines[i].get("text")
            if trig == "word" and i < len(m.words):
                ctx["word"] = m.words[i].get("text")
        if not test(p.get("when"), ctx) or not _word_hit(p, trig, ctx):
            continue
        idx = kept
        kept += 1
        if p.get("every", 1) > 1 and idx % int(p["every"]):
            continue
        ctx["index"] = idx
        if p.get("keyframes"):
            from . import keyframes as kfm
            parts = kfm.steps_for(kfm.parse(p["keyframes"]), p.get("params", {}),
                                  p.get("animation-timing-function"))
            if '"step"' not in json.dumps({k: p.get(k) for k in ("params", "palette", "colors")}):
                from .parts import glide_runs           # 0.24.53: a run of glides is one effect (a value curve)
                parts = glide_runs(parts)
        else:
            n_split = max(1, int(p.get("split", 1)))
            parts = [(k / n_split, (k + 1) / n_split, None, k) for k in range(n_split)]
        n_steps = max(1, len({q[3] for q in parts}))
        base_step = ((ctx["beat"] or 1) - 1) * n_steps if trig == "beat" else 0
        for k, (fa, fb, vals, si) in enumerate(parts):
            a = t + (end - t) * fa
            b = t + (end - t) * fb
            sub = ctx if len(parts) == 1 else dict(m.context(a, b, idx), **m.event_info(trig, i), index=idx, sub=k)
            sub["step"] = base_step + si
            seg = _segment(name, p, m, a, b, sub, idx * len(parts) + k if len(parts) > 1 else idx,
                           trig, palettes, effects, vals)
            if seg:
                out.append(seg)
    return out


def _segment(name, p, m, t, end, ctx, idx, trig, palettes, effects, params=None):
    if end - t < 0.02:
        return None
    s = m.section(t)
    eff = p["effect"]
    fam = (effects or {}).get(eff, {}).get("family", eff)
    why = p.get("why") or {"beat": "first beat of a bar" if ctx["downbeat"] else "beat",
                           "downbeat": "first beat of a bar"}.get(trig) or WHY.get(trig, trig)
    if trig == "sung" and not p.get("why"):
        why = "singing" + (f" ({m.extra['voice']}'s words)" if m.extra.get("voice") else "") + \
            (f" with the face {m.extra['face']}" if m.extra.get("face") else "")
    if trig in ("bass", "melody") and ctx.get("note") and not p.get("why"):
        why += f" {ctx['note']}"
    pars = {k: value(v, ctx, idx) for k, v in (p.get("params", {}) if params is None else params).items()}
    for k, v in list(pars.items()):                        # 0.24.0: "auto" = the prop's own setting
        if v == "auto":
            if m.extra.get(k) is not None:
                pars[k] = m.extra[k]
            else:
                pars.pop(k)
    if m.extra.get("area") and "area" not in pars:
        pars["area"] = m.extra["area"]
    from .parts import segment
    seg = segment(t, end, eff, s, family=fam, params=pars, why=why,
                  palette=value(p.get("palette", "base"), ctx, idx), preset=name)
    cyc = p.get("colors")
    if isinstance(cyc, dict) and "from" in cyc:               # colour by a value: low = first colour
        cols = palettes.get(cyc.get("palette", "base"), {}).get("colors", ["#FFFFFF"])
        x = float(np.clip(float(ctx.get(cyc["from"]) or 0.0), 0, 1))
        seg["palette_colors"] = [cols[min(len(cols) - 1, int(x * len(cols)))]]
    elif cyc:
        src = cyc.get("cycle", "base") if isinstance(cyc, dict) else "base"
        cols = palettes.get(src, {}).get("colors", ["#FFFFFF"])
        seg["palette_colors"] = [cols[idx % len(cols)]]
    return seg


def plan(target: str, react, music: dict, profile: dict, palettes: dict, layer: int = 0,
         presets: dict | None = None, effects: dict | None = None, lyrics: dict | None = None,
         extra: dict | None = None, cues: list | None = None) -> dict:
    """Event-synced plan for one target from one preset or a list of presets (earlier wins).
    cues (0.24.18): your own trigger marks [{"t", "len"?}] - extra hits of the target's first
    preset, forced (they cut what is there), unless a preset of its list reacts to cues itself."""
    presets = load_presets(presets)
    names = names_of(react)
    problems = check(names, presets)
    if problems:
        raise ValueError("; ".join(problems))
    m = _Music(music, profile, lyrics, {**(extra or {}), "_cues": cues or []})
    for n in names:
        trig = get_preset(presets, n).get("on")
        if trig in STEM_TRIGGERS and trig not in music["analysis"]["events"]:
            _warn_once(f"preset {n!r} reacts to {trig} events, which come from the stems - this song was "
                       "analysed without them, so it has none: 'run --stems' (or 'pref stems = true')")
    placed: list[dict] = []
    for n in names:
        for seg in _events(n, get_preset(presets, n), m, palettes, effects):
            a, b = seg["start"], seg["end"]
            if any(x["start"] <= a < x["end"] for x in placed):
                continue                                   # an earlier preset already owns this moment
            nxt = min((x["start"] for x in placed if x["start"] > a), default=None)
            if nxt is not None and nxt < b:
                if nxt - a < 0.02:
                    continue
                seg["end"] = round(nxt, 3)
            placed.append(seg)
    if m.cues and not any(get_preset(presets, n).get("on") == "cue" for n in names):
        n0 = next((n for n in names if get_preset(presets, n).get("on") != "sung"), None)
        if n0:
            p0 = {k: v for k, v in get_preset(presets, n0).items() if k not in ("when", "every", "_words")}
            p0["on"] = "cue"
            for seg in _events(n0, p0, m, palettes, effects):
                a = seg["start"]
                nxt = min((x["start"] for x in placed if x["start"] > a + 0.02), default=None)
                if nxt is not None and nxt < seg["end"]:   # the next real event still comes when it comes
                    seg["end"] = round(nxt, 3)
                keep = []
                for x in placed:                           # a cue is forced: what plays at it stops there
                    if x["end"] <= a or x["start"] > a + 0.02:
                        keep.append(x)
                    elif a - x["start"] >= 0.02:
                        keep.append({**x, "end": round(a, 3)})
                seg["why"] = WHY["cue"]
                seg["reasons"] = [WHY["cue"]]
                seg["cue"] = True
                placed = keep + [seg]
    placed.sort(key=lambda s: s["start"])
    return {"target": target, "target_kind": "model", "layer": layer, "react": ",".join(names),
            "segments": placed}


_WARNED: set = set()


def _warn_once(msg: str) -> None:
    if msg not in _WARNED:
        _WARNED.add(msg)
        from ..common.log import warn
        warn(msg)


def describe(react, presets: dict | None = None) -> str:
    presets = load_presets(presets)
    parts = []
    for n in names_of(react):
        p = get_preset(presets, n) or {}
        parts.append(f"'{n}': {p.get('help') or 'a preset'}"
                     + (f" (only when {fmt_when(p['when'])})" if p.get("when") else ""))
    return "; then ".join(parts)


def fmt_when(cond: dict) -> str:
    return ", ".join(f"{k} {v if isinstance(v, str) and _CMP.match(v) else ('in ' + '/'.join(map(str, v)) if isinstance(v, list) else '= ' + str(v))}"
                     for k, v in cond.items())


def sings(react, presets: dict | None = None) -> bool:
    """Does this react setting use the 'sung' trigger (a singing face)?"""
    presets = load_presets(presets)
    return any((get_preset(presets, n) or {}).get("on") == "sung" for n in names_of(react))
