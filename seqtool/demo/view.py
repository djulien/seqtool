# seqtool-command: gui | main | look | waveform, sections and effects: gui [browser|audacity]
"""Viewing results: Audacity label tracks and a self-contained HTML timeline.

  <stem>.labels-sections.txt / .labels-beats.txt   Audacity label files
  <stem>.timeline.html                             waveform + sections + beats +
                                                   one effect lane per target, with
                                                   audio playback and hover details

Both are generic (no xLights). trackED could take over this role later.
"""
from __future__ import annotations

import html
import json
import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

import numpy as np

from ..common.log import info, warn
from ..music import decode
from ..common.paths import arg as paths_arg

FAMILY_COLORS = {"none": "#3a3a3a", "color": "#4f8cff", "pulse": "#ff5a5a", "motion": "#ffb020",
                 "radial": "#b45cff", "sparkle": "#e8e8e8", "particle": "#38d9a9", "organic": "#ff7a1a",
                 "level": "#9ad04a", "audio": "#d4a5ff", "face": "#ff8fc8", "borrowed": "#c9b38a"}


def write_audacity_labels(out: Path, stem: str, music: dict, profile: dict) -> list[Path]:
    secs = out / f"{stem}.labels-sections.txt"
    with open(secs, "w", encoding="utf-8") as f:
        for s in profile["sections"]:
            rep = f" = {s['repeat_of']}" if s.get("repeat_of") else ""
            f.write(f"{s['start']:.6f}\t{s['end']:.6f}\t#{s['index']} {s.get('type', '?')}{rep}\n")
    beats = out / f"{stem}.labels-beats.txt"
    down = {round(d["time"], 4) for d in music["analysis"]["events"].get("downbeats", [])}
    with open(beats, "w", encoding="utf-8") as f:
        for b in music["analysis"]["events"]["beats"]:
            t = b["time"]
            f.write(f"{t:.6f}\t{t:.6f}\t{'|' if round(t, 4) in down else '.'}\n")
    return [secs, beats]


def peaks(audio: Path, buckets: int = 1600) -> list[float]:
    """Max |amplitude| per bucket, streamed (two passes over chunks is avoided by
    using the probed duration to size buckets)."""
    return peaks_timed(audio, buckets)[1]


def peaks_timed(audio: Path, buckets: int = 1600) -> tuple[float, list[float]]:
    """(seconds per bucket, peaks) - the bucket's real length in decoded samples (0.24.19: a
    file's stated duration can be off, e.g. a VBR MP3's estimate, so time = index x this)."""
    dur = decode.probe(audio)["duration"]
    per = max(1, int(dur * decode.SR / buckets))
    return per / decode.SR, _peaks(audio, per)


def cached_peaks(audio: Path) -> dict:
    """Waveform peaks, decoded once per audio file version and kept on disk
    (decoding a long song takes seconds; the GUI asks for this often)."""
    import hashlib
    import json
    from ..common import config
    if not audio.exists():
        return {"step": 0, "peaks": []}
    st = audio.stat()
    key = hashlib.sha256(f"{audio.resolve()}|{st.st_mtime_ns}|{st.st_size}".encode()).hexdigest()[:20]
    f = config.user_dir() / "cache" / f"peaks2-{key}.json"     # 0.24.19: {step, peaks}
    if f.exists():
        try:
            return json.loads(f.read_text())
        except ValueError:
            pass
    step, p = peaks_timed(audio)
    out = {"step": step, "peaks": p}
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(out))
    return out


def _peaks(audio: Path, per: int) -> list[float]:
    out, carry = [], np.zeros(0, dtype=np.float32)
    for chunk in decode.chunks(audio):
        carry = np.concatenate([carry, np.abs(chunk)])
        m = len(carry) // per
        if m:
            out.extend(carry[: m * per].reshape(m, per).max(axis=1).tolist())
            carry = carry[m * per:]
    if len(carry):
        out.append(float(carry.max()))
    top = max(out) if out else 1.0
    return [round(v / top, 3) for v in out] if top > 0 else [0.0] * len(out)     # a silent file (an empty stem)


def lane_shapes(folder, models: dict | None, max_points: int = 140) -> dict[str, list]:
    """target -> front-view points (x, y in 0..1, node order) for the effect thumbnails."""
    from ..common.canonical import read_json
    lf = Path(folder) / "layout.json"
    if not lf.exists() or not models:
        return {}
    try:
        import numpy as np
        from ..layout.shapes import prop_points
        from ..models.analyze import node_indices
        layout = read_json(lf)
        pts = {}
        for p in layout.get("props", []):
            try:
                P = prop_points(p)
            except Exception:  # noqa: BLE001
                continue
            pts[p["id"]] = P
            for sm in p.get("submodels", []):
                idx = node_indices(sm.get("lines", []), len(P))
                if idx:
                    pts[f"{p['id']}/{sm['name']}"] = P[idx]
        out = {}
        for m in models.get("models", []):
            if m["id"] in pts:
                P = pts[m["id"]]
            elif m["kind"] == "group":
                parts = [pts[x] for x in (m.get("detail_members") or m.get("members", [])) if x in pts and len(pts[x])]
                if not parts:
                    continue
                P = np.vstack(parts)
            else:
                continue
            if not len(P):
                continue
            if len(P) > max_points:
                P = P[np.linspace(0, len(P) - 1, max_points).astype(int)]
            xy = P[:, :2]
            lo, span = xy.min(axis=0), (xy.max(axis=0) - xy.min(axis=0))
            s = float(span.max()) or 1.0
            off = (s - span) / 2                      # keep the aspect ratio, centred
            out[m["id"]] = [[round(float(a), 3), round(float(b), 3)] for a, b in ((xy - lo + off) / s)]
        return out
    except Exception:  # noqa: BLE001
        return {}


def vocal_regions(music: dict, bands=None, min_region: float | None = None) -> list[list]:
    """Vocals / mixed / instrumental passages (see music/vocals.py)."""
    from ..music.vocals import regions
    return regions(music, None, min_region)


def _gui_levels(music: dict):
    from ..music.vocals import gui_levels
    try:
        return gui_levels(music)
    except Exception:  # noqa: BLE001
        return None


def vocal_curve(music: dict, points: int = 800) -> list[float]:
    """The vocal level (0-1) as at most `points` evenly spaced values, or [] without a stem."""
    v = music.get("analysis", {}).get("frames", {}).get("fields", {}).get("vocal")
    if not v:
        return []
    step = max(1, -(-len(v) // points))
    return [round(sum(v[i:i + step]) / len(v[i:i + step]), 3) for i in range(0, len(v), step)]


def effect_menus(matchup: dict, ctx: dict) -> dict:
    """Per target, the effects to offer for a Ctrl+click override (0.19.2): those that suit
    its prop type most (model fit >= 0.6, best first), then the rest. Only effects the output
    can draw (the xLights kit) and that a pin can force ('face' is set with 'face use')."""
    effs = ctx.get("prefs", {}).get("effects", {}).get("effects", {})
    avail = matchup.get("source", {}).get("available_effects")
    by = {m["id"]: m for m in (ctx.get("models") or {}).get("models", [])}
    out = {}
    for p in matchup.get("plans", []):
        tid = p["target"]
        if tid in out:
            continue
        cls = by.get(tid, {}).get("geometry_class", "default")
        cand = [e for e in effs if e != "face" and (avail is None or e in avail or e in ("dark", "transparent"))]
        fit = {e: effs[e].get("model_fit", {}).get(cls, effs[e].get("model_fit", {}).get("default", 0.5)) for e in cand}
        nat = sorted([e for e in cand if fit[e] >= 0.6 and e not in ("dark", "transparent")], key=lambda e: (-fit[e], e))
        rest = sorted(e for e in cand if e not in nat and e not in ("dark", "transparent")) + \
            [e for e in ("dark", "transparent") if e in cand]
        out[tid] = {"natural": nat, "rest": rest, "class": cls}
    return out


def stem_lanes(music: dict) -> list[dict]:
    """The stems' events as rows for the GUI (0.22.0): drum hits (kick low, snare middle, hat
    high in the row), bass notes and melody notes (placed by how high the note is).
    Each mark is [start, end, label, height 0..1]. [] without stems."""
    ev = music.get("analysis", {}).get("events", {})
    out = []
    drums = sorted([[e["time"], round(e["time"] + 0.06, 3), k, h] for k, h in (("kick", 0.1), ("snare", 0.5),
                                                                             ("hat", 0.9)) for e in ev.get(k) or []])
    if drums:
        out.append({"name": "drums", "icon": "\U0001F941", "marks": drums,
                    "about": "drum hits from the drum stem: kick (low in the row), snare (middle), hi-hat or "
                             "cymbal (high) - presets kick, snare and hat-sparkle react to them"})

    def notes(lst, name, icon, about):
        if not lst:
            return
        mids = [e["midi"] for e in lst if e.get("midi") is not None]
        lo, hi = (min(mids), max(mids)) if mids else (0, 1)
        marks = []
        for i, e in enumerate(lst):
            end = e.get("end") or (lst[i + 1]["time"] if i + 1 < len(lst) else e["time"] + 0.2)
            h = e.get("height")
            if h is None:
                h = (e["midi"] - lo) / max(hi - lo, 1) if e.get("midi") is not None else 0.5
            marks.append([e["time"], round(min(end, e["time"] + 2.0), 3), e.get("note") or "", round(h, 3)])
        out.append({"name": name, "icon": icon, "marks": marks, "about": about})
    notes(ev.get("bass"), "bass", "\U0001F3B8", "bass notes from the bass stem (higher in the row = higher note) - "
                                                 "preset bass-pulse reacts to them")
    notes(ev.get("melody"), "melody", "\U0001F3B5", "the tune: the voice where it sings, otherwise the leading "
                                                     "instrument (higher in the row = higher note) - presets "
                                                     "melody-fill and melody-color follow it")
    return out


def timing_tracks(music: dict) -> list[dict]:
    """The timing tracks of the .xsq this song borrows from or was opened from (0.21.8): their
    marks, for the GUI's timing rows (a mark can split or move a section there)."""
    try:
        from ..common import songs
        from ..adapters.xlights import xsq as xsq_mod
        rec = songs.get((music.get("lineage") or {}).get("audio", "")).get("borrowed") or {}
        f = Path(rec.get("xsq", ""))
        if not rec.get("xsq") or not f.is_file():
            return []
        seq = xsq_mod.read(f)
    except Exception:  # noqa: BLE001
        return []
    per: dict[tuple, list] = {}
    for e in seq.effects:
        if e.element_type == "timing":
            per.setdefault((e.element, e.layer), []).append([round(e.start, 3), round(e.end, 3), e.label or ""])
    return [{"name": n + (f" ({['phrases', 'words', 'phonemes'][l] if l < 3 else 'layer ' + str(l + 1)})"
                          if any(k[0] == n and k[1] > 0 for k in per) else ""),
             "track": n, "layer": l, "xsq": f.name, "marks": sorted(m)} for (n, l), m in sorted(per.items())]


def timeline_data(stem: str, music: dict, profile: dict, matchup: dict | None,
                  matches: dict[int, str], with_peaks_from: Path | None = None, folder: Path | None = None) -> dict:
    from ..common.color import mark_commands
    from ..matchup.cli import explain, load_prefs
    matchup = matchup or {"plans": [], "settings": {}}
    ctx = {"prefs": load_prefs(), "music": music, "profile": profile}
    mf = matchup.get("source", {}).get("models", {}).get("filename")
    if folder is not None and mf and (Path(folder) / mf).exists():
        from ..common.canonical import read_json
        ctx["models"] = read_json(Path(folder) / mf)
    shapes = lane_shapes(folder, ctx.get("models")) if folder is not None else {}
    pal_colors = {k: v.get("colors", []) for k, v in matchup.get("palettes", {}).items()}
    about: dict[str, str] = {}
    if ctx.get("models"):
        from ..matchup.explain import overview
        for p in matchup["plans"]:
            if p["target"] not in about:
                try:
                    about[p["target"]] = mark_commands(f"$ seqtool explain {p['target']}\n"
                                                       + overview(matchup, p["target"], ctx))
                except (Exception, SystemExit):  # noqa: BLE001
                    pass
    menus = effect_menus(matchup, ctx)
    mods = {m["id"]: m for m in (ctx.get("models") or {}).get("models", [])}

    def info_of(t):                                    # for the GUI's tree, sort and mini-map (0.20.4)
        m = mods.get(t) or {}
        return {"members": [x for x in m.get("members", []) if x in mods] if m.get("kind") == "group" else [],
                "lights": m.get("node_count", 0), "x": (m.get("yard") or {}).get("x")}
    try:                                               # for the effect menu's 'react' part (0.21.4)
        from ..matchup import reactive as _rx
        react_presets = [{"name": k, "about": _rx.describe(k)} for k in sorted(_rx.load_presets())]
    except Exception:  # noqa: BLE001
        react_presets = []
    fam_effects: dict[str, list] = {}                  # the legend's tooltips (0.21.4): effects per colour
    try:
        from ..common.config import load as _load
        xl = {}
        try:
            from ..adapters.xlights.encoding import find as _find
            enc = _find()
            xl = {g: e.get("stored_name") for g, e in (enc.effects.items() if enc else [])}
        except Exception:  # noqa: BLE001
            pass
        for k, e in sorted(_load("effects")["effects"].items()):
            fam_effects.setdefault(e.get("family", "none"), []).append({"name": k, "xlights": xl.get(k)})
    except Exception:  # noqa: BLE001
        pass
    timing = timing_tracks(music)
    try:                                               # the lyrics, for the magnifier (0.21.9)
        from ..music.lyrics import for_music as _lyr
        lyr = [{"start": ln["start"], "end": ln["end"], "text": ln.get("text", ""),
                "words": [{"start": w["start"], "end": w["end"], "text": w.get("text", ""),
                           **{k2: w[k] for k, k2 in (("voice", "voice"), ("voice_mark", "mark"), ("voice_after", "after"),
                                                      ("joined", "joined")) if w.get(k)}}   # 0.24.43: voice changes
                          for w in ln.get("words") or []]}
               for ln in ((_lyr(music) or {}).get("lines") or [])]
    except Exception:  # noqa: BLE001
        lyr = []
    return {
        "lyrics": lyr,
        "timing": timing,
        "stems": stem_lanes(music),
        "family_effects": fam_effects,
        "react_presets": react_presets,
        "effect_menu": menus,
        "title": stem,
        "duration": music["audio"]["duration"],
        "tempo": round(music["analysis"]["summary"]["tempo"]["bpm"], 1),
        "peaks": cached_peaks(with_peaks_from)["peaks"] if with_peaks_from else [],   # 0.24.27: decoded once
        "vocal": vocal_curve(music),
        "vocal_regions": vocal_regions(music),
        "vocal_levels": _gui_levels(music),
        "beats": [round(b["time"], 3) for b in music["analysis"]["events"]["beats"]],
        "downbeats": [round(d["time"], 3) for d in music["analysis"]["events"].get("downbeats", [])],
        "sections": [{"i": s["index"], "type": s.get("type", "?"), "start": s["start"], "end": s["end"],
                      "match": matches.get(s["index"], ""), "repeat": s.get("repeat_index", 0),
                      "strength": (s.get("transition") or {}).get("incoming_strength"),
                      "energy": s.get("energy"), "confidence": s.get("confidence"), "id": s.get("id")}
                     for s in profile["sections"]],
        "lanes": [{"target": p["target"] + (f" (face {p['face']})" if p.get("pass") == "face" else " (react)" if p.get("react") else
                                            f" ({ {'base': 'moments', 'place': 'placed'}.get(p['pass'], p['pass'])})" if p.get("pass", "main") != "main" else ""),
                   "id": p["target"], "about": about.get(p["target"], ""), "shape": shapes.get(p["target"], []),
                   "kind": p.get("target_kind", "model"), "pass": "react" if p.get("react") else p.get("pass", "main"),
                   **({"react": p.get("react"), "react_parts": p.get("react_parts") or []} if p.get("react") else {}),
                   **info_of(p["target"]),
                   "segments": [
            {"start": g["start"], "end": g["end"], "effect": g["selected"]["effect"],
             "family": g["selected"].get("family", "none"), "score": round(g.get("score_breakdown", {}).get("final", 0.0), 3),
             "params": g.get("parameters", {}), "reasons": g.get("reasons", []), "pinned": bool(g.get("pinned")),
             "borrowed": bool(g.get("borrowed")),
             "colors": g.get("palette_colors") or pal_colors.get(g.get("palette", "base"), []),
             "explain": mark_commands(f"$ seqtool explain {p['target']} @{(g['start'] + g['end']) / 2:.1f}\n"
                                      + explain(matchup, p["target"], (g["start"] + g["end"]) / 2, profile, ctx,
                                                first_pass=p.get("pass", "main")))}
            for g in p["segments"]]} for p in sorted(matchup["plans"], key=lambda p: p["target"])
            if p.get("pass") != "base" or any(g["selected"]["effect"] not in ("transparent", "off")
                                              for g in p["segments"])],      # 0.24.18: no empty moments rows
        "moments": matchup.get("moments", []),
        "cues": ((matchup or {}).get("settings") or {}).get("cues", []),      # 0.24.18: your trigger marks
        "colors": FAMILY_COLORS,
    }


def write_timeline_html(out: Path, stem: str, audio: Path, music: dict, profile: dict,
                        matchup: dict | None, matches: dict[int, str]) -> Path:
    data = timeline_data(stem, music, profile, matchup, matches, audio, out)
    try:
        src = os.path.relpath(audio.resolve(), out.resolve())
    except ValueError:
        src = audio.resolve().as_uri()
    path = out / f"{stem}.timeline.html"
    from ..gui.icons import head_links
    path.write_text(TEMPLATE.replace("/*__THUMBS__*/", THUMBS_JS).replace("<!--__ICONS__-->", head_links())
                    .replace("__DATA__", json.dumps(data))
                    .replace("__AUDIO__", html.escape(Path(src).as_posix()))
                    .replace("__TITLE__", html.escape(stem)), encoding="utf-8")
    return path


def current_results(out: Path | None = None):
    """The current song's newest results: (folder, stem, audio, music, profile, matchup or None).
    Raises SystemExit with a helpful message when something is still missing."""
    from ..common import current
    from ..common.canonical import read_json
    from ..common.paths import show
    s = current.song()
    if s is None:
        raise SystemExit("no song yet - run 'seqtool run --audio SONG' (or 'analyze-music SONG')")
    if s["music"] is None:
        raise SystemExit(f"{s['audio'].name}: not analysed yet - run 'analyze-music' or 'run'")
    if s["profile"] is None:
        raise SystemExit(f"{s['audio'].name}: analysed, not classified yet - run 'classify-music' (or 'run')")
    music, profile = read_json(s["music"]), read_json(s["profile"])
    matchup = read_json(s["matchup"]) if s["matchup"] else None
    stem = s["music"].name[: -len(".music.json")]
    return s["folder"], stem, s["audio"], music, profile, matchup


def audacity_command() -> list[str] | None:
    exe = shutil.which("audacity")
    if exe:
        return [exe]
    if shutil.which("flatpak"):
        try:
            r = subprocess.run(["flatpak", "info", "org.audacityteam.Audacity"], capture_output=True)
            if r.returncode == 0:
                return ["flatpak", "run", "org.audacityteam.Audacity"]
        except OSError:
            pass
    if sys.platform == "darwin" and Path("/Applications/Audacity.app").exists():
        return ["open", "-a", "Audacity"]
    return None


def open_audacity(audio: Path, labels: list[Path]) -> bool:
    cmd = audacity_command()
    if cmd is None:
        warn("Audacity not found on this system - install it, or use 'gui browser'")
        return False
    subprocess.Popen(cmd + [str(audio.resolve())], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    info("Audacity is opening the song. To see the analysis, use File > Import > Labels... and pick:")
    from ..common.paths import show
    for l in labels:
        info(f"   {show(l)}")
    return True


def offer(mode: str, audio: Path, labels: list[Path], timeline: Path) -> None:
    """mode: ask | audacity | browser | none"""
    if mode == "ask":
        from ..common.prompt import ask, interactive
        if not interactive():
            info(f"view the result: open {timeline} in a browser, or load the song in Audacity "
                 f"with the label files (--view audacity|browser)")
            return
        have_aud = audacity_command() is not None
        prompt = "\nShow the waveform with sections and effects? " \
                 + ("[a]udacity, " if have_aud else "") + "[b]rowser timeline, [n]o"
        ans = ask(prompt, "n", remember_as="view_choice").lower()[:1]
        mode = {"a": "audacity", "b": "browser"}.get(ans, "none")
    if mode == "audacity":
        if not open_audacity(audio, labels):
            mode = "browser"
    if mode == "browser":
        webbrowser.open(timeline.resolve().as_uri())
        from ..common.paths import show
        info(f"opened {show(timeline)} in your browser")


THUMBS_JS = (Path(__file__).resolve().parents[1] / "gui" / "thumbs.js").read_text(encoding="utf-8")

TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>seqtool timeline - __TITLE__</title>
<!--__ICONS__-->
<style>
:root{--bg:#14161a;--fg:#e6e6e6;--dim:#8a8f98;--grid:#2a2e35;--accent:#ffd34d;--beat:#c3cbd6;--bar:#ff9f1a;--song:#7cc4ff;--wv-voc:#1f8a4c;--wv-mix:#5ff2e2;--wv-ins:#2a4fc0}
@media (prefers-color-scheme: light){:root{--bg:#fafafa;--fg:#1d1f23;--dim:#666;--grid:#ddd;--accent:#c48a00;--beat:#4e5662;--bar:#c25400;--song:#0b5cad;--wv-voc:#13703c;--wv-mix:#20c8b8;--wv-ins:#1c3a9c}}
body{margin:0;background:var(--bg);color:var(--fg);font:13px/1.4 system-ui,sans-serif}
header{padding:10px 14px;display:flex;gap:16px;align-items:center;flex-wrap:wrap}
h1{font-size:16px;margin:0} .dim{color:var(--dim)}
#wrap{overflow-x:auto;padding:0 14px 14px}
canvas{display:block} #tip{position:fixed;pointer-events:none;background:#000c;color:#fff;padding:6px 8px;
border-radius:6px;font-size:12px;max-width:340px;display:none;white-space:pre-line}
.legend span{display:inline-block;padding:1px 6px;border-radius:4px;margin-right:4px;color:#000}
#panel{position:fixed;right:12px;bottom:12px;max-width:min(640px,95vw);max-height:60vh;overflow:auto;
background:var(--bg);border:1px solid var(--grid);border-radius:8px;padding:10px 12px;display:none;box-shadow:0 4px 20px #0006}
#panel pre{margin:0;font:12px/1.35 ui-monospace,Menlo,Consolas,monospace;white-space:pre-wrap}
#panel button{float:right;background:none;border:1px solid var(--grid);color:var(--fg);border-radius:4px;cursor:pointer}
.c-red{color:#ff6b6b}.c-yellow{color:#ffd166}.c-green{color:#4cc38a}.c-pink{color:#ff7ad9}.c-blue{color:#7aa7ff}.c-teal{color:#4fd1c5}.c-bold{font-weight:700}
@media (prefers-color-scheme: light){.c-red{color:#c62828}.c-yellow{color:#9a6b00}.c-green{color:#1d7a4a}.c-pink{color:#b0207f}.c-blue{color:#2156c9}.c-teal{color:#0d7f78}}
</style></head><body>
<header><h1>__TITLE__</h1><span class="dim" id="meta"></span>
<audio id="au" controls src="__AUDIO__"></audio>
<label class="dim">zoom <input id="zoom" type="range" min="1" max="12" value="1"></label>
<span class="legend" id="legend"></span><span class="dim">click an effect for its explanation, a name for its settings; click above the lanes to seek</span></header>
<div id="wrap"><canvas id="cv"></canvas></div><div id="tip"></div>
<div id="panel"><button id="close" title="close (Esc)">x</button><canvas id="panelthumb" width="300" height="180" title="the effect, drawn on the prop's own shape (a sketch, not an xLights render)" style="display:none;border-radius:6px;margin:0 0 8px"></canvas><pre id="exp"></pre></div>
<canvas id="hoverthumb" width="300" height="180" style="display:none;position:fixed;z-index:8;pointer-events:none;border-radius:8px;box-shadow:0 4px 20px #0008"></canvas>
<script>
const D=__DATA__;
const cv=document.getElementById('cv'),ctx=cv.getContext('2d'),au=document.getElementById('au');
const LABEL=176,WAVE=90,SEC=34,LANE=22,dpr=window.devicePixelRatio||1;
document.getElementById('meta').textContent=`${D.duration.toFixed(1)} s · ${D.tempo} BPM · ${D.sections.length} sections · ${D.lanes.length} targets`;
document.getElementById('legend').innerHTML=Object.entries(D.colors).map(([k,c])=>`<span style="background:${c}">${k}</span>`).join('')+'<span style="color:var(--bar)">&#9475; bar #</span><span style="color:var(--beat)">| beat</span>'+vocalLegend();
let zoom=1,hits=[];
function css(v){return getComputedStyle(document.documentElement).getPropertyValue(v)}
/*__THUMBS__*/
function drawTicks(ctx,x,W){
  // beats: short ticks along the bottom of the waveform; bars (downbeats): taller ticks, numbered when there is room
  const B=css('--beat'),R=css('--bar'),down=new Set((D.downbeats||[]).map(t=>t.toFixed(2)));
  const pxBeat=D.beats.length>1?(W-LABEL)/D.beats.length:99;
  if(pxBeat>=2){ctx.strokeStyle=B;ctx.lineWidth=1;D.beats.forEach(t=>{if(down.has(t.toFixed(2)))return;
    ctx.beginPath();ctx.moveTo(x(t),WAVE-6);ctx.lineTo(x(t),WAVE);ctx.stroke();});}
  const db=D.downbeats||[],pxBar=db.length>1?(W-LABEL)/db.length:99,every=pxBar>=22?1:pxBar>=11?2:pxBar>=5?4:8;
  ctx.strokeStyle=R;ctx.fillStyle=R;ctx.font='9px system-ui';
  ctx.lineWidth=2;db.forEach((t,i)=>{ctx.beginPath();ctx.moveTo(x(t),WAVE-13);ctx.lineTo(x(t),WAVE);ctx.stroke();
    if(i%every===0)ctx.fillText(String(i+1),x(t)+3,WAVE-4);});ctx.lineWidth=1;
  ctx.font='11px system-ui';ctx.fillText('bars / beats',8,WAVE-2);ctx.font='12px system-ui';
}
function draw(){
  const W=Math.max(document.getElementById('wrap').clientWidth-28,600)*zoom, H=WAVE+SEC+16+D.lanes.length*LANE+20;
  cv.width=W*dpr;cv.height=H*dpr;cv.style.width=W+'px';cv.style.height=H+'px';ctx.setTransform(dpr,0,0,dpr,0,0);
  const fg=css('--fg'),dim=css('--dim'),grid=css('--grid'),acc=css('--accent');
  const x=t=>LABEL+(W-LABEL-8)*t/D.duration; hits=[];
  ctx.clearRect(0,0,W,H);ctx.font='12px system-ui';
  // sections (background bands)
  D.sections.forEach((s,k)=>{ctx.fillStyle=k%2?'#ffffff08':'#ffffff00';ctx.fillRect(x(s.start),0,x(s.end)-x(s.start),H);
    ctx.strokeStyle=grid;ctx.beginPath();ctx.moveTo(x(s.start),0);ctx.lineTo(x(s.start),H);ctx.stroke();});
  // waveform
  const mid=WAVE/2,n=D.peaks.length;
  for(let i=0;i<n;i++){const px=x(i/n*D.duration),h=D.peaks[i]*(WAVE/2-4);ctx.fillStyle=waveColor(i,n,dim);ctx.fillRect(px,mid-h,Math.max(1,(W-LABEL)/n),2*h);}
  ctx.fillStyle=fg;ctx.fillText('waveform',8,mid+4);
  // beats
  drawTicks(ctx,x,W);
  // section headers with repeat markers
  D.sections.forEach(s=>{const y=WAVE+4;ctx.fillStyle=fg;ctx.fillText(`#${s.i} ${s.type}`,x(s.start)+4,y+12);
    if(s.match){ctx.fillStyle=acc;ctx.fillText(s.match,x(s.start)+4,y+27);}});
  ctx.fillStyle=fg;ctx.fillText('sections',8,WAVE+16);
  // lanes
  D.lanes.forEach((ln,j)=>{const y=WAVE+SEC+16+j*LANE;ctx.fillStyle=fg;ctx.fillText(ln.target.slice(0,20),8,y+15);hits.push({x0:LABEL-THUMB_W-6,x1:LABEL-6,y0:y,y1:y+LANE,thumb:ln});hits.push({x0:0,x1:LABEL-6,y0:y,y1:y+LANE,label:ln});if(ln.shape&&ln.shape.length)drawThumb(ctx,LABEL-THUMB_W-6,y+(LANE-THUMB_H)/2,ln,au.currentTime||0,60/D.tempo);
    ln.segments.forEach(g=>{const x0=x(g.start),x1=x(g.end);
      if(g.effect==='off'||g.effect==='transparent'){ctx.strokeStyle=grid;ctx.setLineDash([3,3]);ctx.strokeRect(x0+1.5,y+2.5,Math.max(1,x1-x0-3),LANE-5);
        ctx.setLineDash([]);if(x1-x0>70){ctx.fillStyle=dim;ctx.fillText('transparent',x0+5,y+15);}}
      else if(g.effect==='dark'){ctx.fillStyle='#000';ctx.fillRect(x0+1,y+2,Math.max(1,x1-x0-2),LANE-4);ctx.strokeStyle=dim;ctx.strokeRect(x0+1.5,y+2.5,Math.max(1,x1-x0-3),LANE-5);
        if(x1-x0>34){ctx.fillStyle=dim;ctx.fillText('dark',x0+5,y+15);}}
      else{ctx.fillStyle=D.colors[g.family]||'#888';ctx.fillRect(x0+1,y+2,Math.max(1,x1-x0-2),LANE-4);
        if(x1-x0>46){ctx.fillStyle='#000';ctx.fillText(g.effect,x0+5,y+15);}}
      if(g.pinned&&x1-x0>16)drawPinIcon(ctx,x1-13,y+3,true);
      hits.push({x0,x1,y0:y,y1:y+LANE,g,t:ln.target,lane:ln});});
    hits.push({x0:LABEL,x1:W,y0:y,y1:y+LANE,gap:ln});});
  // playhead
  const px=x(au.currentTime||0);ctx.strokeStyle=acc;ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(px,0);ctx.lineTo(px,H);ctx.stroke();ctx.lineWidth=1;followHead(px);
}
cv.addEventListener('mousemove',e=>{const r=cv.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top,tip=document.getElementById('tip');
  const h=hits.find(h=>mx>=h.x0&&mx<=h.x1&&my>=h.y0&&my<=h.y1);
  hoverLane=h&&h.thumb&&h.thumb.shape&&h.thumb.shape.length?h.thumb:null;
  if(hoverLane){tip.style.display='none';const hv=document.getElementById('hoverthumb');
    hv.style.left=Math.min(e.clientX+64,window.innerWidth-BIG_W-8)+'px';hv.style.top=Math.max(8,Math.min(e.clientY-BIG_H/2,window.innerHeight-BIG_H-8))+'px';
    cv.style.cursor='pointer';previewTick();return;}
  if(!h){tip.style.display='none';cv.style.cursor='';return;}
  cv.style.cursor='pointer';
  if(h.label){tip.textContent=`${h.label.id}\n(click for its settings: reactions, presets, preferences, rules; point at the preview to enlarge it)`;
    tip.style.display='block';tip.style.left=Math.min(e.clientX+60,window.innerWidth-350)+'px';tip.style.top=(e.clientY+12)+'px';return;}
  const g=h.g;tip.textContent=plainText(`${h.t}  ${g.start.toFixed(2)}-${g.end.toFixed(2)} s\n${g.effect}${g.pinned?'  (pinned)':''}  score ${g.score}\n`+
    Object.entries(g.params).map(([k,v])=>`${k}: ${typeof v==='object'?JSON.stringify(v):v}`).join(', ')+'\n'+g.reasons.join('; ')+'\n(click for the full explanation)');
  tip.style.display='block';tip.style.left=Math.min(e.clientX+60,window.innerWidth-350)+'px';tip.style.top=(e.clientY+12)+'px';});
cv.addEventListener('mouseleave',()=>{document.getElementById('tip').style.display='none';hoverLane=null;previewTick();});
cv.addEventListener('click',e=>{const r=cv.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top;
  const h=hits.find(h=>mx>=h.x0&&mx<=h.x1&&my>=h.y0&&my<=h.y1);
  if(h&&(h.label||h.thumb)){const ln=h.label||h.thumb;showPanel(ln.about||('explain '+ln.id),ln,null);return;}
  if(h&&h.gap){showPanel(`${h.gap.id}: nothing planned at this moment on this lane (it rests: another layer, a whole-group section, or a pass that only adds accents).\n\n`+(h.gap.about||''),h.gap,null);return;}
  if(h){showPanel(h.g.explain,h.lane,h.g);return;}
  const W=cv.width/dpr,t=(mx-LABEL)/(W-LABEL-8)*D.duration;
  if(t>=0&&t<=D.duration){au.currentTime=t;draw();}});
document.getElementById('close').onclick=()=>document.getElementById('panel').style.display='none';
document.addEventListener('keydown',e=>{if(e.key==='Escape')document.getElementById('panel').style.display='none';});
document.getElementById('zoom').addEventListener('input',e=>{zoom=+e.target.value;draw();});
function followHead(px){if(!(chase||!au.paused))return;chase=false;const w=document.getElementById('wrap'),sl=w.scrollLeft,cw=w.clientWidth;if(px<sl+LABEL||px>sl+cw-40)w.scrollLeft=Math.max(0,px-(cw+LABEL)/2);}
let chase=false;au.addEventListener('seeked',()=>{chase=true;draw();});
au.addEventListener('timeupdate',draw);window.addEventListener('resize',draw);draw();
let _lastT=0;(function anim(ts){if(ts-_lastT>66&&D.lanes.some(l=>l.shape&&l.shape.length)){_lastT=ts;draw();previewTick();}requestAnimationFrame(anim);})(0);
</script></body></html>
"""


def main(argv=None) -> int:
    """seqtool gui [browser|audacity] [--out DIR]

    browser (default): the live browser GUI - waveform, sections, effect lanes,
    song and cache status, and a seqtool console. It refreshes by itself when
    results change. audacity: the song with section and beat label files.
    Works at any point after the music analysis."""
    import argparse
    from ..common.paths import show
    ap = argparse.ArgumentParser(prog="seqtool gui", description=main.__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("viewer", nargs="?", default="browser", choices=("browser", "audacity"))
    ap.add_argument("--out", type=paths_arg, default=None, help="results folder (default: the last one used)")
    a = ap.parse_args(argv)
    if a.viewer == "browser":
        from ..gui import server
        url = server.ensure_running()
        webbrowser.open(url)
        info(f"browser GUI: {url}")
        return 0
    out, stem, audio, music, profile, matchup = current_results(a.out)
    if not audio.exists():
        raise SystemExit(f"audio file not found: {show(audio)}")
    labels = write_audacity_labels(out, stem, music, profile)
    open_audacity(audio, labels)
    return 0
