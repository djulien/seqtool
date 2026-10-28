# seqtool-command: explain | main | look | why a model shows its effect: explain Matrix @37.5; settings: explain Matrix; explain music @37.5
"""seqtool explain MODEL [@TIME] [--out DIR | --matchup FILE]

Without a time: the settings that apply to MODEL all the time (what it is,
how it is planned, allowed effects and preferences, music reactions and
presets, name rules, seed overrides) and a summary of its effects over the song.

With a time: explains why MODEL shows its effect at TIME: the factor scores, their
weights, how the final score adds up, the alternatives and the reasons.
'explain music @TIME' looks at the audio itself instead: section, tempo and
beat position, the measured values, and which effects suit the music there.
TIME is seconds (37.5), m:ss (0:37.5), or a section (#3). MODEL may be a
prop or group; matching ignores case and accepts a unique prefix or
fragment ('tree' finds MegaTree). A prop
that is sequenced through a group is explained via that group.

By default the current song's newest plan is used (see 'status').
"""
from __future__ import annotations

from ..common.suggest import suggest

import argparse
import re
import sys
from pathlib import Path

from ..common.canonical import read_json
from ..common.paths import show
from ..common.vocab import lit
from .cli import explain
from ..common.paths import arg as paths_arg


def find_matchup(out: Path | None) -> Path | None:
    if out is None:
        from ..common import current
        s = current.song()
        if s and s["matchup"]:
            return s["matchup"]
    from ..common import config
    last = config.answer("last_out")
    dirs = [out] if out else [Path(last) if last else None, Path("seqtool-out"), Path("seqtool-demo"), Path(".")]
    files = [f for d in dirs if d and d.is_dir() for f in d.glob("*.matchup*.json")]
    return max(files, key=lambda f: f.stat().st_mtime) if files else None


def vocals_start() -> float:
    """When the singing starts in the current song (0.24.25: '@vocals'): the first lyric word (or
    line), else the first rise of the vocal stem (the mix without stems)."""
    from ..common import current, songs
    from ..common.canonical import file_sha256
    s = current.song()
    if not s or not Path(s["audio"]).exists():
        raise SystemExit("@vocals: no current song - 'run --audio SONG' first")
    audio = Path(s["audio"])
    lyr = songs.get(file_sha256(audio)).get("lyrics") or {}
    starts = [w["start"] for ln in lyr.get("lines", []) for w in (ln.get("words") or [])] or \
        [ln["start"] for ln in lyr.get("lines", []) if ln.get("start") is not None]
    if starts:
        return float(min(starts))
    from ..music.edges import vocal_edges
    rise = vocal_edges(audio).get("rise") or []
    if not rise:
        raise SystemExit("@vocals: no singing found in this song (no lyrics, no vocal rise) - give a time, e.g. @0:23.5")
    return float(rise[0])


def sung_words() -> list[dict]:
    """The current song's sung words (lyrics with word timings): [{"text", "start", "end"}]."""
    from ..common import current, songs
    from ..common.canonical import file_sha256
    s = current.song()
    if not s or not Path(s["audio"]).exists():
        return []
    lyr = songs.get(file_sha256(Path(s["audio"]))).get("lyrics") or {}
    return [w for ln in lyr.get("lines", []) for w in (ln.get("words") or []) if w.get("start") is not None]


def _plain(w: str) -> str:
    return re.sub(r"[^\w'-]", "", w.lower()).strip("'-")


def word_times(word: str) -> tuple[str, list[float]]:
    """(the sung word, every time it starts) - a near spelling is taken when it is close enough
    (general.fuzzy; common/fuzzy)."""
    from ..common import fuzzy
    ws = sung_words()
    if not ws:
        raise SystemExit(f"@{word}: this song has no sung words with times - 'lyrics import' (or a time, e.g. @1:05)")
    vocab = sorted({_plain(w["text"]) for w in ws if _plain(w["text"])})
    kind, best, sim = fuzzy.resolve(_plain(word), vocab)
    if kind in ("unsure", "none"):
        hint = f" - the most likely is '{best}' (@{best})" if best else ""
        raise SystemExit(f"@{word}: no sung word '{word}'{hint}; 'lyrics' lists the words")
    if kind == "near":
        print(f"{{note}}(@{word} read as @{best}, the sung word nearest to it){{/}}")
    return best, [float(w["start"]) for w in ws if _plain(w["text"]) == best]


WORD_TIME = re.compile(r"@?([A-Za-z][\w'-]*)(?:#(\d+))?([+-][\d.]+)?$")


def word_start(word: str, nth: int = 1) -> float:
    """Where WORD is sung (its nth time)."""
    best, hits = word_times(word)
    if nth > len(hits):
        raise SystemExit(f"@{best}#{nth}: '{best}' is sung {len(hits)} time(s) - e.g. @{best}#{len(hits)}")
    return hits[nth - 1]


def parse_time(text: str, profile: dict | None) -> float:
    t = text.lstrip("@").strip()
    m = re.fullmatch(r"vocals([+-][\d.]+)?", t, re.I)            # 0.24.25: where the singing starts
    if m:
        return max(0.0, vocals_start() + float(m.group(1) or 0))
    m = re.fullmatch(r"([A-Za-z][\w'-]*)(?:#(\d+))?([+-][\d.]+)?", t)
    if m and m.group(1).lower() != "vocals":                     # 0.24.34: '@star' - where 'star' is sung
        return max(0.0, word_start(m.group(1), int(m.group(2) or 1)) + float(m.group(3) or 0))
    m = re.fullmatch(r"#(\d+)", t)
    if m:
        if not profile:
            raise SystemExit("section numbers need the music-profile file next to the matchup - 'run' rebuilds it")
        sec = next((s for s in profile["sections"] if s["index"] == int(m.group(1))), None)
        if sec is None:
            raise SystemExit(f"no section #{m.group(1)} - 'sections' lists them")
        return (sec["start"] + sec["end"]) / 2
    if ":" in t:
        mins, secs = t.split(":", 1)
        return int(mins) * 60 + float(secs)
    return float(t)


def resolve_target(matchup: dict, name: str) -> tuple[str, str | None]:
    """Return (plan target, note). Accepts case-insensitive unique prefixes and
    props covered by a group."""
    targets = list(dict.fromkeys(p["target"] for p in matchup["plans"]      # a prop may have 2 layers; a row
                                 if p.get("pass") != "base"))               # with only moments is still its group's
    low = name.lower()
    exact = [t for t in targets if t.lower() == low]
    if exact:
        return exact[0], None
    for sk in matchup.get("diagnostics", {}).get("skipped_targets", []):   # an exact prop name wins next
        if sk["id"].lower() == low:
            m = re.match(r"driven via group (.+)", sk["reason"])
            if m:
                return m.group(1), f"{sk['id']} is sequenced as part of group {m.group(1)}"
            raise SystemExit(f"{sk['id']} is not planned: {sk['reason']}")
    cands = [t for t in targets if t.lower().startswith(low)] or [t for t in targets if low in t.lower()]
    if len(cands) == 1:
        return cands[0], None
    if len(cands) > 1:
        raise SystemExit(f"'{name}' matches several targets: {', '.join(cands)} - give more of the name, e.g. '{cands[0]}'")
    raise SystemExit(f"no target named '{name}'" + suggest(name, [p["target"] for p in matchup["plans"]]))


def explain_music(m: dict, music: dict, profile: dict, t: float) -> str:
    """The virtual model 'music': what the analysis heard at time t."""
    import numpy as np
    from .cli import load_prefs
    from .scoring import music_fit
    from .windows import build_windows
    an = music["analysis"]
    dt = an["frame_interval"]
    bpm = an["summary"]["tempo"]["bpm"]
    secs = profile["sections"]
    sec = next((s for s in secs if s["start"] <= t < s["end"]), secs[-1])
    ids = {s["id"]: s["index"] for s in secs}
    repeats = [f"#{s['index']}" for s in secs if s.get("repeat_of") == sec["id"]]
    beats = [b["time"] for b in an["events"]["beats"]]
    downs = [d["time"] for d in an["events"].get("downbeats", [])]
    bar_idx = sum(1 for d in downs if d <= t + 0.02)
    bar_start = downs[bar_idx - 1] if bar_idx else 0.0
    beat_in_bar = max(1, sum(1 for b in beats if bar_start - 0.02 <= b <= t + 0.02))
    bar = bar_idx + (1 if downs and downs[0] > 2 * 60 / (bpm or 120) else 0)   # count a pickup bar
    near = min(beats, key=lambda b: abs(b - t)) if beats else None
    i = min(int(round(t / dt)), an["frames"]["count"] - 1)
    f = an["frames"]["fields"]
    def fv(k, fmt="{:.2f}"):
        return fmt.format(f[k][i]) if k in f else "-"
    L = [f"What the music is doing at {t:.1f} s",
         f"  section     #{sec['index']} {sec.get('type', '?')}  ({sec['start']:.1f}-{sec['end']:.1f} s, "
         f"{(sec['end'] - sec['start']) * bpm / 240:.0f} bars, label confidence {sec.get('confidence', 0):.2f}"
         + (", your edit" if sec.get("edited") else "") + ")",
         f"              repeats: " + (f"#{ids[sec['repeat_of']]}" if sec.get("repeat_of") else "-")
         + (f";  repeated by {', '.join(repeats)}" if repeats else "")
         + f";  transition into it {sec.get('transition', {}).get('incoming_strength', 0):.2f} "
           "(higher lets effects change here)",
         f"  tempo       {bpm:.1f} BPM;  bar {bar}, beat {beat_in_bar}"
         + (f";  nearest beat {near:.2f} s" if near is not None else ""),
         f"  this frame  ({dt * 1000:.0f} ms at {i * dt:.2f} s; 0..1 values are relative to this song)",
         f"              energy {fv('energy_norm')}   loudness {fv('rms_dbfs', '{:.1f}')} dBFS   "
         f"beat strength {fv('beat_strength')}   onsets {fv('onset_norm')}",
         f"              brightness {fv('brightness_norm')}   bass {fv('bass_norm')}   mid {fv('mid_norm')}   "
         f"treble {fv('treble_norm')}" + (f"   vocal {fv('vocal')}" if "vocal" in f else "")]
    if "vocal_dbfs" in f:
        from ..music.vocals import analyse, at as vocal_at
        va = analyse(music)
        L.append(f"  singing     {vocal_at(music, t) or '-'} here:  vocal stem {fv('vocal_dbfs', '{:.1f}')} dBFS "
                 f"(singing above {va['gate']:.1f}), {float(f['vocal_dbfs'][i]) - float(f['rms_dbfs'][i]):+.1f} dB "
                 f"against the mix (the voice leads above {va['lead']:+g})  - 'inspect vocals' for the whole song")
    if "drums" in f or "melody_hz" in f:
        from ..music.stem_features import stems_at
        L += stems_at(music, t)
    prefs = load_prefs()
    wins = build_windows(music, profile, prefs["scoring"]["decision"], prefs["scoring"]["continuity"])
    w = next((w for w in wins if w.start <= t < w.end), wins[-1])
    feats = "  ".join(f"{k} {v:.2f}" for k, v in w.features.items() if k in
                      ("energy", "beat", "tempo", "sustained", "brightness", "vocal", "drums", "melody"))
    L += [f"  decision window {w.start:.1f}-{w.end:.1f} s (what effect choice is based on, averaged):",
          f"              {feats}"]
    effs = prefs["effects"]["effects"]
    fits = sorted(((e, music_fit(effs[e], w, prefs["scoring"]["music_feature_weights"])) for e in effs if lit(e)),
                  key=lambda x: -x[1])
    L.append("  best music fit here: " + ", ".join(f"{e} {v:.2f}" for e, v in fits[:4])
             + "\n              (music fit is one factor; prop type, geometry, style, section and continuity also count"
               " - try 'explain PROP @time')")
    styles = sorted(profile["profile"]["styles"].items(), key=lambda kv: -kv[1])[:3]
    L.append("  song style  " + ", ".join(f"{k} {v:.2f}" for k, v in styles) + "  (whole song)")
    from ..music.lyrics import for_music
    lyr = for_music(music)
    if lyr:
        ln = next((x for x in lyr["lines"] if x["start"] <= t < x["end"]), None)
        w = next((x for ln_ in lyr["lines"] for x in ln_.get("words", []) if x["start"] <= t < x["end"]), None)
        L.append("  lyrics      " + (f"\"{ln['text']}\" ({ln['start']:.1f}-{ln['end']:.1f} s)" if ln else "(no line here)")
                 + (f", word \"{w['text']}\"" if w else ""))
    return "\n".join(L)


def find_model(models: dict, name: str) -> dict:
    ms = models.get("models", [])
    low = name.lower()
    for test in (lambda i: i.lower() == low, lambda i: i.lower().startswith(low), lambda i: low in i.lower()):
        c = [m for m in ms if test(m["id"])]
        if len(c) == 1 or (c and test is not None and c[0]["id"].lower() == low):
            return c[0]
        if len(c) > 1:
            raise SystemExit(f"'{name}' matches several: {', '.join(m['id'] for m in c[:10])}")
    raise SystemExit(f"no model or group named '{name}'" + suggest(name, [m["id"] for m in models["models"]]))


def overview(m: dict, name: str, ctx: dict) -> str:
    """Settings that apply to a model or group at any time, and its effects over the song."""
    from collections import Counter
    from . import reactive, rules as name_rules
    from .cli import CLASS_WORDS
    from .engine import _target_prefs, group_role, group_role_why
    from ..common.canonical import content_sha256
    models, prefs = ctx.get("models"), ctx.get("prefs")
    if not models or not prefs:
        raise SystemExit("explain needs the models file next to the matchup - 'run' rebuilds it")
    mod = find_model(models, name)
    tid = mod["id"]
    mp = name_rules.expand(prefs["models"], models)
    tp = _target_prefs(tid, mp)
    cls = mod.get("geometry_class", "?")
    kind = mod.get("kind", "model")
    head = f"{tid}  ({kind}"
    if kind == "group":
        head += f", {mod.get('group_kind', 'leaf')} group of {len(mod.get('members', []))}, role {' ('.join(group_role_why(mod, mp))})"
    head += f", {cls} = {CLASS_WORDS.get(cls, cls.lower())}"
    if mod.get("node_count"):
        head += f", {mod['node_count']} lights"
    L = ["{head}" + head + "){/}"]
    plans = [p for p in m["plans"] if p["target"] == tid]
    skipped = next((s for s in m.get("diagnostics", {}).get("skipped_targets", []) if s["id"] == tid), None)
    if plans:
        words = {"main": "effects chosen per section", "top": "top pass (takes over whole sections)",
                 "detail": "detail pass (accents on its parts, above the parents)",
                 "enhance": "enhance pass (accents on layer 2)",
                 "pin": "pinned (a row of its own, above its group, only where pinned)",
                 "face": "singing face (xLights Faces, while the words are sung)",
                 "base": "whole-yard moments (base pass: unison hits, sweeps, call and response)",
                 "borrowed": "borrowed from an existing .xsq (as it is there)",
                 "choreo": "a choreography's parts (a layer of their own)"}
        L.append("  planned: " + " + ".join(
            ("music-reactive" + (f" (layer {p['layer'] + 1})" if p.get("layer") else "")) if p.get("react")
            else words.get(p.get("pass", "main"), p.get("pass", "")) for p in sorted(plans, key=lambda p: p.get("layer", 0))))
        for p in plans:
            if p.get("rests"):
                L.append(f"  rests while the top group {p['rests']['for']} takes over: "
                         + ", ".join(f"{a:.1f}-{b:.1f} s" for a, b in p["rests"]["spans"]))
    elif skipped:
        L.append(f"  not planned on its own: {skipped['reason']}")
    else:
        L.append("  not in this plan")
    L.append("  {head}settings (current preferences):{/}")
    hits = tp.get("_rules") or []
    by_rule = f"   (name rule {', '.join('/' + r + '/' for r in hits)})" if hits else ""
    L.append(f"    enabled          {'yes' if tp.get('enabled', True) else 'no'}")
    allowed = tp.get("allowed_effects")
    L.append(f"    allowed effects  {', '.join(allowed) if allowed else 'any'}")
    ep = {e: v for e, v in (tp.get("effect_preferences") or {}).items() if v != 1}
    L.append("    preferences      " + (", ".join(f"{e} x{v:g}" + (" (never)" if v <= 0 else "") for e, v in ep.items())
                                      or "none (all x1)") + (by_rule if ep else ""))
    react = tp.get("react")
    if react and react != "off":
        L.append(f"    react            {react}" + (" on the layer above its normal effects" if tp.get("react_over")
                                                   else " instead of its normal effects")
                 + (by_rule if hits and not prefs["models"].get("targets", {}).get(tid, {}).get("react") else ""))
        pr = reactive.load_presets(prefs.get("presets"))
        for n in reactive.names_of(react):
            p = pr.get(n)
            if p is None:
                L.append(f"      {n}: unknown preset")
                continue
            L.append(f"      {n}: on {p.get('on')}, {p.get('effect')} - {p.get('help', '')}"
                     + (f" (only when {reactive.fmt_when(p['when'])})" if p.get("when") else ""))
    else:
        L.append("    react            no")
    if hits:
        L.append("    name rules       " + ", ".join(f"/{r}/" for r in hits))
    ovr = {k: v for k, v in m.get("settings", {}).get("seed_overrides", {}).items()
           if k.split("@")[0] in (tid, "") or k.startswith("@")}
    if ovr:
        L.append("    seed overrides   " + ", ".join(f"{k}={v}" for k, v in sorted(ovr.items())))
    if m.get("source", {}).get("preferences_sha256") not in (None, content_sha256(prefs)):
        L.append("    {warn}(preferences changed since this plan was made - run again to apply them){/}")
    for p in plans:
        segs = p["segments"]
        cnt = Counter(g["selected"]["effect"] for g in segs)
        what = ", ".join(f"{e} {n}" for e, n in cnt.most_common())
        if p.get("react"):
            pc = Counter(g.get("preset", p["react"]) for g in segs)
            L.append(f"  over the song (reactive): {len(segs)} effects: {what}"
                     + ("  [" + ", ".join(f"{k} {v}" for k, v in pc.items()) + "]" if len(pc) > 1 else ""))
        else:
            tag = "" if p.get("pass", "main") == "main" else f" ({p['pass']} pass)"
            L.append(f"  over the song{tag}: {len(segs)} segments: {what}")
            secs = []
            for g in segs:
                if not secs or secs[-1][1] != g["selected"]["effect"]:
                    secs.append([g["start"], g["selected"]["effect"]])
            L.append("    " + "  ".join(f"{a:.0f}s {e}" for a, e in secs[:16]) + (" ..." if len(secs) > 16 else ""))
    if mod.get("detail_members"):
        dm = mod["detail_members"]
        L.append(f"  parts (submodels): {', '.join(dm[:8])}" + (f" ... ({len(dm)})" if len(dm) > 8 else ""))
    if kind == "submodel":
        L.append(f"  part of {mod.get('parent')}; plan it with 'rules add' or 'pref' (enabled: true) or react on it")
    if kind == "group" and mod.get("members"):
        mem = mod["members"]
        L.append(f"  members: {', '.join(mem[:12])}" + (f" ... ({len(mem)})" if len(mem) > 12 else ""))
    L.append(f"  {{note}}({{do}}explain {tid} @TIME{{/}} for why it shows its effect at a moment){{/}}")
    return "\n".join(L)


def run(name: str, when: str | None, matchup_path: Path) -> str:
    m = read_json(matchup_path)
    if not when and name.lower() != "music":
        from .cli import explain_context
        return overview(m, name, explain_context(matchup_path))
    prof_name = m["source"]["music_profile"].get("filename")
    prof_path = matchup_path.with_name(prof_name) if prof_name else None
    profile = read_json(prof_path) if prof_path and prof_path.exists() else None
    if name.lower() == "music":
        mus_path = matchup_path.with_name(m["source"]["music"]["filename"])
        if profile is None or not mus_path.exists():
            raise SystemExit("explain music needs the music and profile files next to the matchup - 'run' rebuilds them")
        if not when:
            raise SystemExit("explain music @TIME  (e.g. 'explain music @1:05' or 'explain music @#3')")
        return explain_music(m, read_json(mus_path), profile, parse_time(when, profile))
    target, note = resolve_target(m, name)
    at = parse_time(when, profile)
    mine = [p for p in m["plans"] if p["target"].lower() == name.lower() and p.get("pass") == "base"
            and any(g["start"] <= at < g["end"] for g in p["segments"])]
    if mine:                                     # in a moment the prop flashes on its own row (0.20)
        target, note = mine[0]["target"], None
    own = [p for p in m["plans"] if p["target"] == target]
    if when and own and all(p.get("pass") in ("pin", "face", "base") for p in own) and \
            not any(g["start"] <= at < g["end"] for p in own for g in p["segments"]):
        sk = next((s for s in m.get("diagnostics", {}).get("skipped_targets", [])
                   if s["id"] == target and s["reason"].startswith("driven via group ")), None)
        if sk:                                   # outside its pins a prop plays its group's effect
            group = sk["reason"][len("driven via group "):]
            note = f"{target} is sequenced as part of group {group} (its own row plays only where you pinned it)"
            target = group
    from .cli import explain_context
    text = explain(m, target, at, profile, explain_context(matchup_path))
    return (note + "\n" if note else "") + text


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool explain", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("model")
    ap.add_argument("time", nargs="?", help="@37.5, @0:37.5 or @#3 (middle of section 3); "
                                            "leave out for the settings that apply all the time")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--out", type=paths_arg, help="output folder to look in")
    g.add_argument("--matchup", type=paths_arg, help="a specific matchup file")
    a = ap.parse_args(argv)
    path = a.matchup or find_matchup(a.out)
    if path is None or not path.exists():
        raise SystemExit("no matchup file found - run 'seqtool run' or 'seqtool -demo' first, or give --matchup")
    print(run(a.model, a.time, path))
    print(f"(from {show(path)})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
