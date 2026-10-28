"""The choreography effect (0.24.47) - a named plan of effects, played like one effect.

    pin "All Props" @#3 choreo name="both arms wave"

pins it like any effect (a section, its repeats, from= / until=). What it plays is the
definition of that name ('define', definitions.py) - its machine form (--data), read for the
pinned prop or group and the time it plays at, so a definition kept per kind of prop ('for
spinners', 'for Matrix') plays each prop's own version:

    define set "left arm wave" --show --for spinners one spoke dips 10 to 7 and back
        --data '{"effect": "wipe", "settings": {"direction": "down"}, "length": "1beat"}'

Where it plays: the entries that apply are sorted by where they are for - none (the pinned
target itself), a kind of prop (each prop of that kind in the target), a group or one prop (that
one, when it is the target or inside it). When any entries are for something, the ones for
nothing are their defaults (merged under them); else they play on the target. The pinned target
itself shows nothing of its own there (like 'transparent'); the parts play on a layer of their
own above each prop's other effects.

The machine form: one step, or {"steps": [step, ...]} (all played). A step:

    effect     an effect name (as in 'effects'), with "settings": {name: value} as 'pin' takes them
    react      instead of an effect: a reaction preset ('presets' lists them; "beat-chase@word[bat]"
               too) - its events inside this step's time, on the target (0.24.53)
    motif      instead of an effect: another definition's name, played inside this step's time
    steps      instead of an effect: a list of steps, played inside this step's time
    target     a prop, group or submodel ("Spinner1/Spoke10") instead of where it plays;
               "/NAME": that submodel of each prop it plays on ("/seqtool-10oclock" - 'submodel
               angles' makes clock-position ones)
    spread     "each": on every prop inside the target at once; "cycle": one prop per time
               (the 1st on the 1st prop, the 2nd on the 2nd ...); "pitch": one prop per time by
               how high it sounds - low on the left, high on the right (the melody's note with
               stems, else the sound's brightness); "order": "left_to_right" | "right_to_left"
               (by where the props stand) for each / cycle
    at         when it starts, after the start of the time it has: 0.5 (s), "1b" (bars),
               "2beats", "25%" (of that time)
    length     how long (the same forms; default: to the end of that time, or with 'per' to the
               end of that event - a word's end, the next beat)
    per        once per event inside that time: word, last_word, first_word, lyric (a line),
               beat, downbeat, onset, cue, section - or any event list the analysis has
               (kick, snare, melody ...); "words": [..] keeps only those words; call, response,
               call_phrase, response_phrase, pair (calls.py - from cues tagged 'call'); "tag":
               with per cue, only cues with that tag
    only       which of those times: [1, 3], [-1] (the last), "first", "last", "odd", "even"
    every      again every N (s, "1b", "2beats") until the end of that time; "count": N times
    color      a colour for it ("blue", "#3060FF"); "colors": [..] one per time, in turn - on a
               motif / steps, the parts inside take that time's colour
    settings   as 'pin' takes them, also "a..b" (a glide over the part) and "rotation" (Layer
               Settings > Rotation: "90deg", "10oclock" - 12 = 0, clockwise - or a share of a turn)
    keyframes  CSS-style, over the part (0.24.48): {"0%": {"rotation": "10oclock"}, "50%":
               {"rotation": "7oclock"}, "100%": {"rotation": "10oclock"}} - settings glide between
               them ("easing": linear (the default here), ease-in-out ..., step-end holds); xLights
               gets one effect with value curves once the kit has learned them
    generator  "file.py:function" (in the show folder or seqtool-prefs) - your own Python:
               function(window=(start, end), target=NAME, music=MUSIC, step=STEP) returns steps
               with "start" and "end" in song seconds (and the rest as above)

Each part's reasons name the choreography and the step, so 'explain' says why it is there.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

DEPTH = 6
KNOWN_PER = {"word", "last_word", "first_word", "lyric", "line", "phrase", "beat", "downbeat", "onset", "cue",
             "section", "sung", "call", "response", "call_phrase", "response_phrase", "pair"}


def _props(models: dict):
    from ..common.definitions import Props
    P = Props.__new__(Props)
    ms = models["models"]
    P.by = {m["id"].lower(): m for m in ms}
    P.groups = {m["id"].lower(): [x.lower() for x in m.get("members", [])] for m in ms if m["kind"] == "group"}
    return P


class Expander:
    def __init__(self, music, profile, models, palettes, effects, lyrics, cues, notes, presets=None):
        from .reactive import _Music
        self.m = _Music(music, profile, lyrics, {"_cues": cues or []})
        self.lyrics, self.cues, self.presets = lyrics, cues or [], presets
        self.music, self.profile, self.models = music, profile, models
        self.palettes, self.effects, self.notes = palettes, effects, notes
        self.P = _props(models)
        self.ids = {m["id"].lower(): m["id"] for m in models["models"]}
        self.sha = (music.get("lineage") or {}).get("audio")
        self.out: dict[str, list[dict]] = {}      # target -> segments
        self.limit = float("inf")                 # the pinned segment's end: nothing plays past it
        self._inherit = None                      # a colour from the step around this one

    # -- where ---------------------------------------------------------------------------
    def _id(self, name: str) -> str | None:
        return self.ids.get(str(name).lower())

    def _leaves(self, target: str) -> list[str]:
        t = target.lower()
        if t not in self.P.groups:
            return [self.ids[t]] if t in self.ids else []
        seen, out = set(), []
        for x in self.P.groups[t]:
            for y in (self._leaves(self.ids.get(x, x)) if x in self.P.groups else [self.ids.get(x)]):
                if y and y not in seen:
                    seen.add(y)
                    out.append(y)
        return out

    def bundles(self, name: str, target: str, at: float) -> list[tuple[str, dict, list[str]]]:
        """[(where it plays, merged data, where the entries come from)] for one definition."""
        from ..common import definitions as DF
        es = DF.applying(self.sha, self.profile, None, at, name)
        if not es:
            return []
        P, t = self.P, target.lower()
        inside = P.members(t) | {t} if t in P.groups else {t}
        general, keyed = [], {}
        for e in es:
            f = (e.get("for") or "").strip()
            if not f:
                general.append((0, e))
                continue
            fl = f.lower()
            if fl in P.by or fl.rstrip("s") in P.by:
                fl = fl if fl in P.by else fl.rstrip("s")
                if fl in inside:
                    keyed.setdefault(self.ids[fl], []).append((3 if fl not in P.groups else 2, e))
                continue
            for leaf in self._leaves(target):
                if P.rank(f, leaf) == 1:
                    keyed.setdefault(leaf, []).append((1, e))
        order = lambda xs: [e for _, e in sorted(xs, key=lambda r: (DF.LEVELS.index(r[1].get("level", "song")), r[0]))]  # noqa: E731
        if not keyed:
            return [(target, DF.merge(order(general)), [e["where"] for _, e in general])] if general else []
        return [(k, DF.merge(order(general + v)), [e["where"] for _, e in general + v]) for k, v in keyed.items()]

    # -- when ----------------------------------------------------------------------------
    def _beat(self, t: float) -> float:
        return self.m.beat_len(t)

    def dur(self, v, a: float, b: float, what: str) -> float | None:
        if v is None:
            return None
        from .parts import duration
        try:
            return duration(v, b - a, self._beat(a))
        except ValueError as ex:
            self.note(f"{what}={v!r}: {ex}")
            return None

    def instances(self, st: dict, a: float, b: float) -> list[tuple[float, float, int]]:
        """[(start, end, i)] - when a step plays inside (a, b)."""
        a0 = a + (self.dur(st.get("at"), a, b, "at") or 0.0)
        length = self.dur(st.get("length"), a, b, "length")
        per = st.get("per")
        out = []
        if per:
            per = str(per).lower().replace(" ", "_").replace("-", "_")
            known = KNOWN_PER | set(self.music["analysis"]["events"])
            if per not in known and per.endswith("s") and per[:-1] in known:
                per = per[:-1]                                   # 'words', 'beats', 'pairs'
            trig = {"line": "lyric", "phrase": "lyric", "last_word": "word", "first_word": "word"}.get(per, per)
            times = self.m.times(trig)
            if not times and trig not in ("cue",):
                self.note(f"per {per!r}: the song has no {trig} events" + (" (lyrics needed)" if trig in ("word", "lyric") else ""))
            keep = range(len(times))
            if per in ("last_word", "first_word"):
                idx, k = [], 0
                for ln in self.m.lines:
                    n = len(ln.get("words", []))
                    if n:
                        idx.append(k + (n - 1 if per == "last_word" else 0))
                    k += n
                keep = idx
            words = [w.lower().strip(".,!?") for w in st.get("words") or []]
            tag = str(st.get("tag") or "").lower() or None
            for i in keep:
                t = times[i]
                if not (a0 - 1e-3 <= t < b):
                    continue
                if tag and trig == "cue" and (self.m.cues[i].get("tag") or "") != tag:
                    continue
                if words and trig == "word":
                    w = str(self.m.words[i].get("text", "")).lower().strip(".,!?\"'")
                    if not any(w == x or w.startswith(x) for x in words):
                        continue
                nxt = next((x for x in times[i + 1:] if x > t + 0.02), b)
                own = self.m.own_end(trig, i)
                end = min(t + length, self.limit) if length else min(own if own and own > t else nxt, b)
                out.append((t, end, len(out)))
            return self.only(st, out)
        every = self.dur(st.get("every"), a, b, "every")
        count = st.get("count")
        if count:
            n = max(1, int(count))
            step = (b - a0) / n
            return self.only(st, [(a0 + i * step, min(b, a0 + i * step + (length or step)), i) for i in range(n)])
        if every and every > 0.02:
            t, i = a0, 0
            while t < b - 0.02:
                out.append((t, min(b, t + (length or every)), i))
                t, i = t + every, i + 1
            return self.only(st, out)
        return [(a0, min(self.limit, a0 + length) if length else b, 0)]   # a length of its own may run on

    def only(self, st: dict, out: list) -> list:
        """"only": which of the times - [1, 3] (the 1st and 3rd), [-1] (the last), "first",
        "last", "odd", "even" (0.24.49) - renumbered from 0."""
        sel = st.get("only")
        if sel is None or not out:
            return out
        n = len(out)
        if isinstance(sel, (int, str)) and not str(sel).lstrip("-").isdigit():
            pick = {"first": [0], "last": [n - 1], "odd": list(range(0, n, 2)), "even": list(range(1, n, 2))}.get(
                str(sel).lower())
            if pick is None:
                self.note(f"only={sel!r}: a list of numbers ([1, -1]) or first, last, odd, even")
                return out
        else:
            sel = sel if isinstance(sel, list) else [sel]
            pick = []
            for k in sel:
                try:
                    k = int(k)
                except (TypeError, ValueError):
                    continue
                j = k - 1 if k > 0 else n + k
                if 0 <= j < n:
                    pick.append(j)
        return [(a, b, i) for i, (a, b, _) in enumerate(out[j] for j in sorted(set(pick)))]

    # -- what ----------------------------------------------------------------------------
    def note(self, text: str) -> None:
        n = f"choreo {self._name}: {text}"
        if n not in self.notes:
            self.notes.append(n)

    def play(self, name: str, target: str, a: float, b: float, depth: int = 0, via: str = "") -> int:
        """Play the definition `name` on `target` inside (a, b). -> parts made."""
        self._name = getattr(self, "_name", name) if depth else name
        if depth > DEPTH:
            self.note(f"motifs inside each other more than {DEPTH} deep ('{name}' uses itself?)")
            return 0
        bundles = self.bundles(name, target, (a + b) / 2)
        if not bundles:
            self.note(f"no definition '{name}' with a machine form applies to {target} there - e.g. define set "
                      f"\"{name}\" --data '{{\"effect\": \"twinkle\"}}'")
            return 0
        made = 0
        for where, data, froms in bundles:
            steps = data.get("steps") if isinstance(data.get("steps"), list) else ([data] if data else [])
            if not steps:
                self.note(f"'{name}' has no machine form (--data) for {where} - only words")
                continue
            for k, st in enumerate(steps):
                if isinstance(st, dict):
                    made += self.step(st, where, a, b, depth, f"{via}{name}" + (f" step {k + 1}" if len(steps) > 1 else ""))
        return made

    def step(self, st: dict, target: str, a: float, b: float, depth: int, label: str) -> int:
        tgt = target
        rel = str(st.get("target") or "")
        if rel.startswith("/"):                    # a submodel of each prop it plays on (0.24.49): "/seqtool-10oclock"
            made = 0
            for leaf in self._leaves(target) or [target]:
                sub = self._id(leaf + rel)
                if sub is None:
                    self.note(f"{label}: {leaf} has no submodel '{rel[1:]}'" + (
                        " - 'submodel angles " + leaf + " --write' makes clock-position ones" if "oclock" in rel else ""))
                    continue
                made += self.step({**st, "target": sub}, sub, a, b, depth, label)
            return made
        if st.get("target"):
            tgt = self._id(st["target"])
            if tgt is None:
                self.note(f"{label}: no prop, group or submodel '{st['target']}'")
                return 0
        if st.get("generator"):
            return self.generated(st, tgt, a, b, depth, label)
        made = 0
        spread = str(st.get("spread") or "").lower()
        leaves = self._leaves(tgt) if spread in ("each", "cycle", "pitch") else [tgt]
        if spread and not leaves:
            leaves = [tgt]
        order = str(st.get("order") or ("left_to_right" if spread == "pitch" else "")).lower()
        if order in ("left_to_right", "right_to_left", "x", "-x"):          # by where they stand in the yard
            leaves = sorted(leaves, key=lambda x_: float(((self.P.by.get(x_.lower()) or {}).get("yard") or {})
                                                         .get("x", 0.5)), reverse=order in ("right_to_left", "-x"))
        insts = [x for x in self.instances(st, a, b) if x[1] - x[0] >= 0.02]
        bins = self.pitch_bins(insts, len(leaves)) if spread == "pitch" else None
        cols = self._colors(st, label)
        for (s, e, i) in insts:
            where = leaves if spread not in ("cycle", "pitch") else \
                [leaves[bins[i] if bins is not None else i % len(leaves)]]
            inherit = self._inherit
            if cols and not st.get("effect"):
                self._inherit = cols[i % len(cols)]                       # the parts inside get its colour
            for w in where:
                if st.get("motif"):
                    made += self.play(str(st["motif"]), w, s, e, depth + 1, f"{label} > ")
                elif isinstance(st.get("steps"), list):
                    for j, sub in enumerate(st["steps"]):
                        if isinstance(sub, dict):
                            made += self.step(sub, w, s, e, depth + 1, f"{label} > {j + 1}")
                elif st.get("react"):                       # 0.24.53: a reaction preset, inside this time
                    made += self.react(st, w, s, e, label)
                elif st.get("effect"):
                    for seg in self.segments(st, w, s, e, i, label):
                        self.out.setdefault(w, []).append(seg)
                        made += 1
                else:
                    self.note(f"{label}: a step needs an effect, a motif or steps - e.g. {{\"effect\": \"twinkle\"}}")
                    self._inherit = inherit
                    return made
            self._inherit = inherit
        return made

    def react(self, st: dict, target: str, s: float, e: float, label: str) -> int:
        """A step {"react": "beat-chase"} (any preset, 'presets' lists them; 'LOOK@EVENT[w1|w2]'
        too): its events inside this time, on the target - a reaction as a part of a choreography."""
        from . import reactive
        presets = reactive.load_presets(self.presets)
        bad = reactive.check(st["react"], presets, self.effects)
        if bad:
            self.note(f"{label}: " + "; ".join(bad))
            return 0
        try:
            rp = reactive.plan(target, st["react"], self.music, self.profile, self.palettes, presets=presets,
                               effects=self.effects, lyrics=self.lyrics,
                               cues=[c for c in self.cues if not c.get("tag")])
        except ValueError as ex:
            self.note(f"{label}: {ex}")
            return 0
        cols = self._colors(st, label) or ([self._inherit] if self._inherit else [])
        n = 0
        for g in rp["segments"]:
            a, b = max(g["start"], s), min(g["end"], e)
            if b - a < 0.02:
                continue
            why = f"choreography '{label}': {g.get('why', '')}".rstrip(": ")
            q = {**g, "start": round(a, 3), "end": round(b, 3), "choreo": label, "pinned": True,
                 "why": why, "reasons": [why]}
            if cols:
                q["palette_colors"] = [cols[n % len(cols)]]
            self.out.setdefault(target, []).append(q)
            n += 1
        return n

    def _colors(self, st: dict, label: str) -> list[str]:
        cols = st.get("colors") or ([st["color"]] if st.get("color") else [])
        if not cols:
            return []
        from .palette_cmd import parse_colors
        try:
            return parse_colors(",".join(cols) if isinstance(cols, list) else str(cols))
        except SystemExit as ex:
            self.note(f"{label}: {ex}")
            return []

    def pitch(self, s: float, e: float) -> float:
        """How high what is heard there is: the melody's note (with stems), else the sound's
        brightness (its spectral centroid) just after s."""
        mel = [x for x in self.music["analysis"]["events"].get("melody") or [] if s - 0.03 <= x["time"] < e]
        if mel and mel[0].get("midi") is not None:
            return float(mel[0]["midi"]) * 1000.0
        f = self.music["analysis"]["frames"]["fields"].get("brightness_hz") or []
        dt = self.music["analysis"]["frame_interval"]
        vals = f[int(s / dt): max(int(s / dt) + 1, int(min(e, s + 0.15) / dt))]
        return float(sorted(vals)[len(vals) // 2]) if vals else 0.0

    def pitch_bins(self, insts: list, n: int) -> list[int]:
        """Each time's prop by pitch: the lowest notes on the first (leftmost) prop ... the highest
        on the last; the same pitch, the same prop (spread = "pitch", 0.24.49)."""
        ps = [self.pitch(s, e) for s, e, _ in insts]
        if not ps:
            return []
        uniq = sorted(set(round(p, -1) for p in ps))
        if len(uniq) <= n:
            rank = {u: k for k, u in enumerate(uniq)}
            off = (n - len(uniq)) // 2
            return [off + rank[round(p, -1)] for p in ps]
        lo, hi = uniq[0], uniq[-1]
        return [min(n - 1, int((round(p, -1) - lo) / ((hi - lo) or 1) * n)) for p in ps]

    def segments(self, st: dict, target: str, s: float, e: float, i: int, label: str) -> list[dict]:
        """The step's effect at one time - one segment, or with "keyframes" the parts its settings
        glide through (0.24.48): a run of glides is one segment with a curve per setting; a jump
        (a held value, a choice changing) starts the next."""
        seg = self.segment(st, target, s, e, i, label)
        if seg is None or not st.get("keyframes"):
            return [seg] if seg else []
        from . import keyframes as kfm
        from .parameters import user_value
        try:
            kfs = {sel: {k.lower(): (user_value(k.lower(), self._specs[k.lower()], v) if k.lower() in self._specs else v)
                         for k, v in (decl or {}).items()} for sel, decl in st["keyframes"].items()}
            bad = sorted({k for d in kfs.values() for k in d if k not in self._specs and k not in kfm.TF_KEYS})
            if bad:
                self.note(f"{label}: {seg['selected']['effect']} has no setting {', '.join(repr(b) for b in bad)}")
                kfs = {sel: {k: v for k, v in d.items() if k not in bad} for sel, d in kfs.items()}
            pieces = kfm.steps_for(kfm.parse(kfs), {}, str(st.get("easing") or "linear"))
        except (ValueError, KeyError) as ex:
            self.note(f"{label}: keyframes: {ex} - e.g. \"keyframes\": {{\"0%\": {{\"rotation\": \"10oclock\"}}, "
                      "\"50%\": {\"rotation\": \"7oclock\"}, \"100%\": {\"rotation\": \"10oclock\"}}")
            return [seg]
        from .parts import glide_runs
        keys = sorted({k for _, _, vals, _ in pieces for k in vals})
        out, dur = [], e - s
        for a0, b0, vals, _ in glide_runs(pieces, keys):
            if (b0 - a0) * dur < 0.02:
                continue
            q = {**seg, "start": round(s + dur * a0, 3), "end": round(s + dur * b0, 3),
                 "parameters": {**seg["parameters"], **vals}, "yours": sorted(set(seg.get("yours", [])) | set(keys))}
            out.append(q)
        return out

    def segment(self, st: dict, target: str, s: float, e: float, i: int, label: str) -> dict | None:
        from . import parts
        from .parameters import parameters
        eff = parts.effect_name(st["effect"], self.effects)    # seqtool's name, or xLights' ('On')
        if eff is None:
            self.note(f"{label}: no effect '{st['effect']}' ('effects' lists them)")
            return None
        spec = self.effects[eff]
        self._specs = parts.setting_specs(spec)
        sec = self.m.section(s)
        feats = {"energy": self.m.field("energy", s)}
        pars = parameters(eff, spec, feats, target, f"choreo:{label}:{sec['id']}:{i}", 0)   # the usual settings
        mine, yours, bad = parts.read_settings(eff, spec, st.get("settings") or st.get("params") or {})
        for x in bad:
            self.note(f"{label}: {x}")
        pars.update(mine)
        why = f"choreography '{label}'"
        seg = parts.segment(s, e, eff, sec, family=spec.get("family", eff), params=pars, why=why,
                            choreo=label, pinned=True, yours=sorted(yours) or None)
        cs = self._colors(st, label)
        if cs:
            seg["palette_colors"] = [cs[i % len(cs)]]
        elif self._inherit:
            seg["palette_colors"] = [self._inherit]
        return seg

    def generated(self, st: dict, tgt: str, a: float, b: float, depth: int, label: str) -> int:
        spec = str(st["generator"])
        file, _, fn = spec.rpartition(":")
        if not file:
            file, fn = spec, "steps"
        from ..common import config
        from ..common.showfiles import show_folder
        cands = [Path(file).expanduser()] + [d / file for d in (show_folder(), config.user_dir()) if d]
        path = next((p for p in cands if p.is_file()), None)
        if path is None:
            self.note(f"{label}: generator file {file} not found (in the show folder or seqtool-prefs)")
            return 0
        try:
            sp = importlib.util.spec_from_file_location(f"seqtool_choreo_{path.stem}", path)
            mod = importlib.util.module_from_spec(sp)
            sp.loader.exec_module(mod)
            got = getattr(mod, fn)(window=(a, b), target=tgt, music=self.m, step=st)
        except Exception as ex:  # noqa: BLE001
            self.note(f"{label}: generator {spec} failed: {type(ex).__name__}: {ex}")
            return 0
        made = 0
        for j, g in enumerate(got or []):
            if not isinstance(g, dict):
                continue
            s, e = float(g.get("start", a)), float(g.get("end", b))
            g = {k: v for k, v in g.items() if k not in ("start", "end", "generator")}
            made += self.step(g, tgt, max(a, s), min(b, e), depth + 1, f"{label} > {fn} {j + 1}")
        return made


def expand(plans: list[dict], models: dict, music: dict, profile: dict, palettes: dict, effects: dict,
           lyrics, cues, notes: list[str], presets: dict | None = None) -> list[dict]:
    """Every pinned choreo segment -> the parts it plays, as plans of their own (pass 'choreo')."""
    jobs = [(p, g) for p in plans for g in p["segments"]
            if g["selected"]["effect"] == "choreo" and not p.get("react")]
    if not jobs:
        return plans
    X = Expander(music, profile, models, palettes, effects, lyrics, cues, notes, presets)
    for p, g in jobs:
        name = str((g.get("parameters") or {}).get("name") or "").strip()
        if not name:
            notes.append(f"choreo on {p['target']}: no name - e.g. 'pin {p['target']} @#3 choreo name=\"left arm wave\"'")
            continue
        X._name, X.limit = name, g["end"]
        n = X.play(name, p["target"], g["start"], g["end"])
        g["why"] = f"choreography '{name}': {n} part(s) on {len(X.out)} prop(s) and group(s), on a layer of their own"
        g["reasons"] = [g["why"]]
    by_id = {m["id"]: m for m in models["models"]}
    for tgt, segs in sorted(X.out.items()):
        top = max((q.get("layer", 0) for q in plans if q["target"] == tgt), default=-1)
        lanes: list[list[dict]] = []                       # overlapping parts: a layer each
        for s in sorted(segs, key=lambda s: (s["start"], s["end"])):
            lane = next((ln for ln in lanes if ln[-1]["end"] <= s["start"] + 1e-3), None)
            if lane is None:
                lanes.append([s])
            else:
                lane.append(s)
        for k, ln in enumerate(lanes):
            plans.append({"target": tgt, "target_kind": (by_id.get(tgt) or {}).get("kind", "model"),
                          "layer": top + 1 + k, "pass": "choreo", "segments": ln})
    return plans
