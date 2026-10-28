"""The GUI's step bar (0.21.7, the user's workflow): Layout - Faces - Song - Lyrics -
Effects - Export, each with its state and the commands that do or repeat it, and the
file picker the steps use (seqtool lists the folders itself: a browser page can't see
file paths).

Every action is an ordinary seqtool command, run in the console - so it is in the
history, 'undo' covers it, and you see what a click does.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

KINDS = {                                   # what the file picker shows for each use
    "layout": {".xml"},
    "audio": {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac"},
    "xsq": {".xsq"},
    "image": {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"},
    "lyrics": {".lrc", ".txt"},
    "any": None,
}


def _abc(t: str) -> list:
    return [int(x) if x.isdigit() else x.lower() for x in re.split(r"(\d+)", t)]


def browse(folder: str | None, kind: str = "any") -> dict:
    """A folder's sub-folders and the files of that kind, alphabetically; folders end in '/'.
    It starts in the working folder (the current song's)."""
    d = Path(os.path.expanduser(folder)) if folder else Path.cwd()
    if not d.is_dir():
        d = d.parent if d.parent.is_dir() else Path.cwd()
    d = d.resolve()
    want = KINDS.get(kind)
    dirs, files = [], []
    try:
        for e in d.iterdir():
            if e.name.startswith("."):
                continue
            try:
                if e.is_dir():
                    dirs.append(e.name + "/")
                elif want is None or e.suffix.lower() in want:
                    files.append(e.name)
            except OSError:
                continue
    except OSError as ex:
        return {"dir": str(d) + os.sep, "error": str(ex), "dirs": [], "files": []}
    from ..common import config
    recent = [r for r in (config.answer("recent_folders") or []) if Path(r).is_dir()][:8]
    return {"dir": str(d) + os.sep, "parent": (str(d.parent) + os.sep) if d.parent != d else None,
            "home": str(Path.home()) + os.sep, "dirs": sorted(dirs, key=_abc), "files": sorted(files, key=_abc),
            "recent": [r + os.sep for r in recent], "sep": os.sep}


def upload_dir() -> Path:
    """Where files dropped on the page are kept: beside the current song (seqtool-uploads/)."""
    d = Path.cwd() / "seqtool-uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_upload(name: str, data: bytes) -> Path:
    safe = re.sub(r"[^\w.\- ()]", "_", Path(name).name).strip() or "upload"
    f = upload_dir() / safe
    f.write_bytes(data)
    return f


def kind_of(name: str) -> str | None:
    suf = Path(name).suffix.lower()
    return next((k for k, v in KINDS.items() if v and suf in v), None)


def _q(p) -> str:
    s = str(p)
    return '"' + s.replace('"', '\\"') + '"' if re.search(r"[\s\"'#]", s) else s


def state() -> dict:
    """Each step: ok / todo / stale, a short line, its main command and the others."""
    from ..common import config, current
    from ..common.canonical import read_json
    out = {}
    # 1. layout
    try:
        from ..layout import store
        src = store.source_info()
        why = store.stale_reasons() or []
    except Exception:  # noqa: BLE001
        src, why = None, []
    if src:
        p = Path(src["path"])
        out["layout"] = {"state": "stale" if why else "ok", "line": f"{p.parent.name}/{p.name}"
                         + (f" - {', '.join(why)}" if why else ""),
                         "main": f"layout {_q(p)}", "main_label": "read the layout again",
                         "more": [["groups and props: roles, sequenced, likes, reactions ...", "@panel layout"],
                                  ["another layout ...", "@pick layout layout"], ["groups and roles (list)", "groups --list"],
                                  ["props", "models"], ["forget it", "layout --forget"]]}
    else:
        out["layout"] = {"state": "todo", "line": "no layout yet", "main": "@pick layout layout",
                         "main_label": "choose xlights_rgbeffects.xml (or drop it here)", "more": []}
    # 2. faces
    built = config.answer("built_faces") or {}
    faces = []
    try:
        lay = read_json(store.folder() / "layout.json") if src else {}
        faces = [f["name"] for p in lay.get("props", []) for f in p.get("faces", [])]
        grids = [p["id"] for p in lay.get("props", []) if p.get("render_buffer")]
    except Exception:  # noqa: BLE001
        grids = []
    names = sorted(set(faces) | set(built), key=_abc)
    out["faces"] = {"state": "ok" if names else "todo",
                    "line": (f"{len(names)} face(s): " + ", ".join(names[:4]) + (" ..." if len(names) > 4 else ""))
                    if names else "no singing faces (optional)",
                    "main": "@pick image face", "main_label": "build a face from an image ...",
                    "more": [["add a face (from an image) ...", "@pick image face"]]          # 0.22.2
                    + [[f"show {n}", f"face show {_q(n)}"] for n in names[:8]]
                    + [[f"put {n} into xlights_rgbeffects.xml", f"face write {_q(n)}"] for n in sorted(built, key=_abc)
                       if n not in faces][:6]                                               # 0.22.3
                    + [[f"forget {n} (built)", f"face remove {_q(n)}"] for n in sorted(built, key=_abc)][:6]
                    + [["list", "face list"]],
                    "props": grids, "count": len(names)}
    # 3. song, 4. lyrics, 5. effects, 6. export
    s = None
    try:
        s = current.song()
    except Exception:  # noqa: BLE001
        pass
    if not s:
        out["song"] = {"state": "todo", "line": "no song yet", "main": "@pick audio song",
                       "main_label": "choose a song (or drop it here)",
                       "more": [["open an .xsq as it is ...", "@pick xsq xsq"]]}
        for k, w in (("lyrics", "a song first"), ("effects", "a song first"), ("export", "a song first")):
            out[k] = {"state": "todo", "line": w, "main": None, "more": []}
        return _short(out)
    audio = s["audio"]
    music = read_json(s["music"]) if s.get("music") else None
    rec = {}
    try:
        from ..common import songs
        rec = songs.get((music or {}).get("lineage", {}).get("audio", "")) if music else {}
    except Exception:  # noqa: BLE001
        pass
    xsq = (rec.get("borrowed") or {})
    opened = bool(xsq.get("items")) and xsq.get("only")
    out["song"] = {"state": "ok" if music else "todo", "line": audio.name + (f" (from {Path(xsq['xsq']).name}, as it is)"
                                                                            if opened else ""),
                   "main": f"run --audio {_q(audio)}", "main_label": "analyse and plan it again",
                   "more": [["another song ...", "@pick audio song"], ["open an .xsq as it is ...", "@pick xsq xsq"],
                            ["sections", "sections"], ["colour palette (from the music style) ...", "@panel palette"],
                            ["feel: busy, intensity, warmth, unison ...", "@panel feel"]]}
    lyr = None
    try:
        from ..music.lyrics import for_music
        lyr = for_music(music)
    except Exception:  # noqa: BLE001
        pass
    out["lyrics"] = {"state": "ok" if lyr else "todo",
                     "line": "lyrics kept for this song" if lyr else "no lyrics (optional; transcribing is up to you)",
                     "main": "lyrics", "main_label": "show them",
                     "more": [["transcribe (may take minutes)", "lyrics transcribe"], ["import a file ...", "@pick lyrics lyrics"]]
                     + ([["from the .xsq's lyrics timing track", "lyrics from-xsq"]] if xsq.get("xsq") else [])}
    mu = s.get("matchup")
    out["effects"] = {"state": "ok" if mu else "todo",
                      "line": ("the .xsq's effects, as they are" if opened else "planned") if mu else "not planned yet",
                      "main": "run" if not opened else "open-xsq --fill",
                      "main_label": "plan again (analysis reused)" if not opened else "let seqtool plan the empty rows",
                      "more": ([["back to the .xsq as it is", "open-xsq --as-is"]] if xsq.get("items") and not opened else [])
                      + [["reroll every choice that isn't pinned (pins keep their effect; only their settings change)", "reroll"], ["pins", "pin"], ["reactions", "react"]]}
    xs = None
    if mu:
        folder = Path(mu).parent
        cands = sorted(folder.glob("*.xsq"), key=lambda p: p.stat().st_mtime)
        xs = cands[-1] if cands else None
    fresh = bool(xs and mu and xs.stat().st_mtime >= Path(mu).stat().st_mtime)
    out["export"] = {"state": "ok" if fresh else ("stale" if xs else "todo"),
                     "line": (xs.name + ("" if fresh else " - the plan changed since")) if xs else "not exported yet",
                     "main": "xlights-export" if mu else None, "main_label": "write the .xsq for xLights",
                     "more": ([["the sequence (.xsq) for xLights", "xlights-export"]] if mu else [])
                     + [["verification sequence (checks what xLights does with each effect)", "xlights-export --checks"]]}
    return _short(out)


def _short(out: dict) -> dict:
    """The few words on each step's button (0.21.8: names and paths are in the tooltip and menu)."""
    for k, st in out.items():
        line = st.get("line", "")
        if k == "faces":
            n = st.get("count", 0)
            st["short"] = f"{n} face{'s' if n != 1 else ''}" if st["state"] == "ok" else ""
        elif k == "lyrics":
            st["short"] = "" if st["state"] == "ok" else "none"
        elif k == "effects":
            st["short"] = "as the .xsq" if "as they are" in line else ""
        elif st["state"] == "stale":
            st["short"] = "out of date"
        else:
            st["short"] = ""
    return out


def _direct_members(lst: dict) -> dict:
    """structure.models (the props a group lists whole) for a layout stored before 0.24.15."""
    from ..layout import store
    try:
        import xml.etree.ElementTree as ET
        src = Path((store.source_info() or {}).get("path", ""))
        for g in ET.parse(src).getroot().iter("modelGroup"):
            if g.get("name") in lst:
                ent = [x.strip() for x in g.get("models", "").split(",") if x.strip()]
                lst[g.get("name")] = {**lst[g.get("name")], "models": [x for x in ent if "/" not in x]}
    except Exception:  # noqa: BLE001 - then a part's prop counts as held only in part
        pass
    return lst


def layout_tree() -> dict:
    """The layout panel's data (0.21.8): groups as the layout nests them, the props listed
    in each directly, and per prop whether it is sequenced, what it likes / avoids and how it
    reacts. Everything it changes goes through commands (groups --role, models --disable,
    prefer, react)."""
    from ..common import config
    from ..layout import store
    from ..matchup.engine import group_role_why
    cur = store.current() if store.source_info() else None
    if not cur:
        return {"error": "no layout yet - step 1 (or drop xlights_rgbeffects.xml on the page)"}
    lay, models = cur
    mp = config.load("models")
    from ..matchup import rules as name_rules
    mpx = name_rules.expand(mp, models)
    tg = mpx.get("targets", {})
    by = {m["id"]: m for m in models["models"]}
    groups = [m for m in models["models"] if m["kind"] == "group"]
    child = {c for g in groups if not (g.get("role_guess") or {}).get("duplicate_of")   # 9.ALL-LAST doesn't hide 1.ALL
             for c in g.get("child_groups", [])}

    def under(g, seen=()):
        out = set()
        for c in g.get("child_groups", []):
            if c in by and c not in seen:
                out |= {x for x in by[c].get("members", [])} | under(by[c], seen + (c,))
        return out
    G = []
    lst = {lg["id"]: lg.get("structure") or {} for lg in lay.get("groups", [])}
    if any(v.get("submodels") and "models" not in v for v in lst.values()):
        lst = _direct_members(lst)                  # a layout stored before 0.24.15: read from the source
    for g in groups:
        role, why = group_role_why(g, mpx)
        inner = under(g)
        st = lst.get(g["id"], {})
        subs = [x for x in st.get("submodels", []) if "/" in x]
        via = {x.split("/", 1)[0] for x in subs} - set(st.get("models", []))   # 0.24.15: props it holds only part of
        parts = [{"id": x, "name": x.split("/", 1)[1], "parent": x.split("/", 1)[0],
                  "class": (by.get(x) or {}).get("geometry_class", "?").lower(), "nodes": (by.get(x) or {}).get("node_count", 0)}
                 for x in dict.fromkeys(subs)]
        G.append({"id": g["id"], "kind": g.get("group_kind", "?"), "role": role, "why": why,
                  "set": "role" in (mp.get("targets", {}).get(g["id"]) or {}),
                  "groups": [c for c in g.get("child_groups", []) if c in by],
                  "props": [x for x in dict.fromkeys(g.get("members", [])) if x in by and x not in inner and x not in via],
                  "parts": parts,
                  "top": g["id"] not in child, "count": len(set(g.get("members", []))),
                  "prefs": {k: v for k, v in ((tg.get(g["id"]) or {}).get("effect_preferences") or {}).items() if v != 1},
                  "react": (tg.get(g["id"]) or {}).get("react") if (tg.get(g["id"]) or {}).get("react") not in (None, "off")
                  else None})
    P = []
    lprops = {lp["id"]: lp for lp in lay.get("props", [])}
    in_group = {x for g in G for x in g["props"]}       # 0.24.15: a group holding only a part of it doesn't count
    for m in models["models"]:
        if m["kind"] != "model":
            continue
        t = tg.get(m["id"], {})
        off = (mp.get("targets", {}).get(m["id"]) or {}).get("enabled") is False
        P.append({"id": m["id"], "class": m.get("geometry_class", "?").lower(), "nodes": m.get("node_count", 0),
                  "ok": bool(m.get("supported_for_generation", True)) and not off, "off": off,
                  "why": "disabled by you" if off else m.get("unsupported_reason", ""),
                  "prefs": {k: v for k, v in (t.get("effect_preferences") or {}).items() if v != 1},
                  "react": t.get("react") if t.get("react") not in (None, "off") else None,
                  "grouped": m["id"] in in_group,
                  # 0.24.16: its faces, and the ones it sings with ('face use')
                  "faces": [f["name"] for f in (lprops.get(m["id"]) or {}).get("faces", []) if f.get("name")],
                  "sings": [e["face"] for e in t.get("sing") or [] if e.get("face")]
                  or ([t["face"]] if t.get("face") not in (None, "off", "none") else [])})
    try:
        from ..matchup import reactive
        presets = [{"name": k, "about": reactive.describe(k)} for k in sorted(reactive.load_presets())]
    except Exception:  # noqa: BLE001
        presets = []
    effs = config.load("effects")["effects"]
    from ..demo.view import FAMILY_COLORS
    E = [{"name": k, "family": v.get("family", "none"), "color": FAMILY_COLORS.get(v.get("family", "none"), "#888")}
         for k, v in sorted(effs.items(), key=lambda kv: (kv[1].get("family", ""), kv[0]))
         if v.get("family") not in ("none", "face")]
    return {"groups": sorted(G, key=lambda g: _abc(g["id"])), "props": sorted(P, key=lambda p: _abc(p["id"])),
            "effects": E, "presets": presets}


def prefs_tree(name: str | None = None) -> dict:
    """The preferences window (0.21.9): the files, and for one its settings in order - each
    node with its description, each value with the built-in default, whether it is yours,
    the valid values and what it does. Changes go through 'pref' (in the console)."""
    from ..common import prefcmd as P
    files = P.files()
    if not name:
        return {"files": files}
    if name not in files:
        return {"files": files, "error": f"no preference file '{name}'"}
    merged, user, dflt = P._merged(name), P._user(name), P._default(name)
    rows = []

    def walk(node, path):
        for k, v in node.items():
            if str(k).startswith("_"):
                continue
            p = path + (k,)
            if isinstance(v, dict):
                rows.append({"path": list(p), "kind": "node", "doc": v.get("_doc", ""),
                             "mine": P._get(user, p) is not P.MISSING})
                walk(v, p)
            else:
                d = P._get(dflt, p)
                rows.append({"path": list(p), "kind": "value", "value": v,
                             "default": None if d is P.MISSING else d, "has_default": d is not P.MISSING,
                             "mine": P._get(user, p) is not P.MISSING, "choices": P.choices_for(name, p),
                             "about": " ".join(P.about(name, p, v))})
    walk(merged, ())
    return {"files": files, "name": name, "doc": merged.get("_doc", ""), "rows": rows}
