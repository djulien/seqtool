# seqtool-command: face | main | tools | singing faces: face use PROP FACE (sing the lyrics); face build MODEL IMAGE; face list
# seqtool-inspect: faces | inspect_faces | singing faces in the stored layout and the face format learned from it
# seqtool-inspect: face | inspect_face | one face's images (in the GUI: flip through them with < >): inspect face NAME
"""seqtool face build MODEL IMAGE [--name NAME] [--mouth x,y,w,h --eyes x,y,w,h/x,y,w,h | --marks FILE | --no-marks] [--out DIR]
       seqtool face use [PROP [FACE | off] [@#N] [--voice V] [--area x,y,w,h] [--add] [--no-over]]
       seqtool face show NAME [--prop PROP]   (also: inspect face NAME)
       seqtool face write NAME [--prop PROP] [--yes]            (into xlights_rgbeffects.xml, a copy kept first)
       seqtool face remove NAME [--prop PROP] [--xlights] [--yes]
       seqtool face [list] | face format

Mouth shapes for a singing face, from one pixel image of the face. The image is
put on the prop's pixel grid (scaled to fit, pixel art stays sharp); the mouth and
eyes are found (or given in grid pixels); then the 10 mouth shapes (AI, E, etc, FV,
L, MBP, O, U, WQ, rest) are drawn in place of the mouth, each with eyes open and
closed. The result is a folder of images, a contact sheet to check them, and the
face definition for xLights as a one-line XML snippet to paste into the model in
xlights_rgbeffects.xml.

The snippet's format (attribute names, image naming, path style) is learned from
the faces already in your layout - whatever your xLights version writes - so it
keeps working with later versions. 'face format' shows what was learned.

    face use Matrix Showman                   Matrix sings the lyrics with its face 'Showman'
                                                  (xLights Faces, while the words are sung, over its
                                                  other effects, which show behind it - --no-over: they
                                                  rest meanwhile).
                                                  Singing is the reaction preset 'sing' (0.24.0), so:
    face use Matrix Showman @#3               ... only in section 3 and its repeats (this song;
                                                  --only: not the repeats) - or 'react Matrix sing @#3',
                                                  the GUI's react menu; 'react Matrix off @#5' stops it there
    face use Matrix Bob --voice BOB --area 0,0,50,100
    face use Matrix Alice --voice ALICE --area 50,0,50,100 --add
                                                  two faces on one matrix, side by side, each singing its
                                                  own voice's words ({BOB} / {ALICE} / {ALL} in the lyrics;
                                                  'lyrics voice'); area = x,y,w,h in percent from the top left
                                                  (needs the kit's sub-buffer steps: 'xlights-kit --update')
    face use Matrix off                       stop;  'face use' lists the singing props
    face build Matrix pumpkin.png             -> pumpkin-face/ (images, sheet, snippet)
    face build devface bat.png --name Bat --mouth 8,16,8,2
    face show Pumpkin                             its images in the GUI, flipped with < > (base image,
                                                  then every mouth with eyes open and closed); mark the
                                                  mouth and eye pixels there, pick colours, 'save marks'
                                                  (kept inside pumpkin.png itself when it is a PNG)
    face build Matrix pumpkin.png             again: uses those marks by itself - the marked pixels
                                                  are filled from the colours round them, the mouths and
                                                  eyes drawn on that (--no-marks: find them again instead)
    face write Pumpkin                            put the built face into xlights_rgbeffects.xml (0.22.3) on
                                                  the prop it was built for - a copy of the file is kept in
                                                  seqtool-backups/ beside it first; a face of the same name on
                                                  that prop is replaced. Close xLights first.
    face remove Pumpkin                           forget a built face (its folder stays; 'face list' / the
                                                  GUI no longer offer it)
    face remove Pumpkin --xlights                 also take it out of xlights_rgbeffects.xml (copy kept first)
    face list                                     faces per prop in the stored layout, and built ones
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from ..common.log import good, info, warn
from ..common.paths import arg as paths_arg, show


def _layout():
    from ..layout import store
    got = store.current()
    if got is None:
        raise SystemExit("no layout stored yet - e.g. 'layout path/to/xlights_rgbeffects.xml'")
    return got[0]


def _prop(lay: dict, name: str) -> dict:
    from ..common.suggest import suggest
    ps = [p for p in lay["props"] if p["id"].lower() == name.lower()] or \
         [p for p in lay["props"] if p["id"].lower().startswith(name.lower())]
    if len(ps) != 1:
        raise SystemExit(f"no prop '{name}' in the stored layout" + suggest(name, [p["id"] for p in lay["props"]])
                         if not ps else f"'{name}' matches several props: {', '.join(p['id'] for p in ps[:6])}")
    return ps[0]


def _format(lay: dict) -> dict | None:
    return (lay.get("adapter") or {}).get("xlights", {}).get("face_format")


def list_faces(lay: dict) -> list[str]:
    rows = [(p["id"], p.get("render_buffer"), p["faces"]) for p in lay["props"] if p.get("faces")]
    from ..common import config
    built = config.answer("built_faces") or {}
    inlay = {f["name"] for _, _, fs in rows for f in fs}
    extra = [f"{{head}}built, not in xlights_rgbeffects.xml yet{{/}}: " + ", ".join(
        f"{n} ({show(Path(d))})" for n, d in sorted(built.items()) if n not in inlay)] \
        if any(n not in inlay for n in built) else []
    if extra:
        extra.append("  {note}'face write NAME' puts one there, 'face remove NAME' forgets it{/}")
    if not rows:
        return ["no singing faces in the stored layout - 'face build MODEL IMAGE' makes one"] + extra
    L = [f"{{head}}singing faces{{/}} ({sum(len(f) for _, _, f in rows)} on {len(rows)} props):"]
    for pid, rb, fs in rows:
        grid = f"{rb['columns']}x{rb['rows']}" if rb else "?"
        kinds = {"images": "image", "nodes": "node-range"}
        L.append(f"  {pid:<20} {grid:>8}  " + ", ".join(f"{f['name']} ({kinds.get(f['kind'], f['type'])})" for f in fs))
    return L + extra


def show_format(lay: dict) -> list[str]:
    from ..adapters.xlights import faces
    fmt = _format(lay)
    L = []
    if not fmt:
        L.append("{warn}no faces in the stored layout to learn from{/} - the format shipped with seqtool is used")
        fmt = faces.shipped_format() or {}
    else:
        L.append(f"{{head}}face format{{/}} learned from the {fmt['learned_from']} face(s) in your layout:")
    for typ, t in fmt.get("types", {}).items():
        L.append(f"  {typ} ({t['kind']}, {t['count']} face(s)): keys '{t.get('template', '?')}', "
                 f"mouths {', '.join(t.get('mouths', {}))}")
        if t.get("eyes"):
            L.append(f"      eyes: open = '{t['eyes'].get('open')}', closed = '{t['eyes'].get('closed', '-')}'; "
                     f"image names like '{faces.file_name('Name', 'AI', 'open', t)}'; "
                     f"{'absolute' if t['paths']['absolute'] else 'relative'} paths")
    L.append(f"  name key '{fmt.get('name_key')}', type key '{fmt.get('type_key')}'")
    return L


def inspect_faces(args) -> list[str]:
    lay = _layout()
    return list_faces(lay) + [""] + show_format(lay)


def build_face(model: str, image: Path, name: str | None = None, mouth: str | None = None,
               eyes: str | None = None, out: Path | None = None, debug: bool = False,
               marks: Path | None = None, use_marks: bool = True) -> Path | None:
    from ..common import deps
    from ..adapters.xlights import faces
    from . import build as fb
    PIL = deps.need("PIL", pip="pillow", purpose="singing faces (reading and writing images)")
    if PIL is None:
        return None
    from PIL import Image
    if not image.exists() and Path(str(image).replace("\\ ", " ")).exists():   # a bash-style escaped space
        image = Path(str(image).replace("\\ ", " "))
    if not image.exists():
        import os
        raise SystemExit(f"not found: {image.resolve() if not image.is_absolute() else image} (seqtool is in "
                         f"{os.getcwd()}; 'pwd' shows it, 'cd FOLDER' changes it) - e.g. "
                         f"'face build {model} ~/faces/pumpkin.png' or 'face build {model} ~/faces/pump*.png'")
    image = _not_a_made_picture(image)
    lay = _layout()
    prop = _prop(lay, model)
    rb = prop.get("render_buffer")
    if not rb:
        raise SystemExit(f"{prop['id']} has no pixel grid seqtool knows - a matrix face needs a matrix-like prop "
                         "('face list' shows the props that have faces)")
    got = faces.matrix_format(_format(lay))
    if got is None:
        raise SystemExit("no image (matrix) face to learn the format from, and none shipped - make one face in "
                         "xLights, then 'layout' again")
    typ, t = got
    if not t["from_layout"]:
        warn("your layout has no image faces to learn the format from - using the format learned from xLights "
             "2025.13; check the snippet in xLights")
    name = name or image.stem
    cols, rows = rb["columns"], rb["rows"]
    src = Image.open(image)
    grid = fb.to_grid(src, cols, rows)
    if src.size != (cols, rows):
        info(f"  {image.name} is {src.width}x{src.height}; put on {prop['id']}'s {cols}x{rows} grid "
             f"({'scaled' if src.size != grid.size else 'as is'})")
    trace: list | None = [] if debug else None
    from . import marks as fmarks
    md, where = None, None
    if marks is not None:                                   # the pixels marked in the viewer (0.20.7)
        import json as _jm
        try:
            md = fmarks.read(Path(marks)) if fmarks.is_png(Path(marks)) else _jm.loads(Path(marks).read_text())
        except (OSError, ValueError) as e:
            raise SystemExit(f"can't read the marks {marks} ({e}) - 'face show NAME', mark the pixels, 'save marks'")
        if not md:
            raise SystemExit(f"no marks in {marks} - 'face show {name}', mark the pixels, 'save marks'")
        where = Path(marks)
        if md.get("grid") and tuple(md["grid"]) != (cols, rows):
            raise SystemExit(f"the marks were made on a {md['grid'][0]}x{md['grid'][1]} grid, {prop['id']} is "
                             f"{cols}x{rows} - mark the face again in 'face show {name}'")
    elif use_marks and not mouth and not eyes:              # kept in the image itself (0.20.8)
        md = fmarks.read(image)
        if md and md.get("grid") and tuple(md["grid"]) != (cols, rows):
            warn(f"  {image.name} holds marks made on a {md['grid'][0]}x{md['grid'][1]} grid, not {prop['id']}'s "
                 f"{cols}x{rows} - finding the mouth and eyes instead (mark them again in 'face show {name}')")
            md = None
        where = image if md else None
    if md:
        face = fb.face_from_marks(grid, md)
        info(f"  {len(face.mouth_px)} mouth pixels and {sum(len(e) for e in face.eye_px)} eye pixels marked in "
             f"the viewer ({'kept in ' + where.name if where == image else show(where)}); filled from the colours round "
             "them" + ("  {note}(--no-marks finds them again instead){/}" if where == image else ""))
        if trace is not None:
            trace.append(f"marks from {where}: colours picked {sorted((md.get('colors') or {}))}")
    else:
        face = fb.detect_scaled(src, grid, cols, rows, fb.parse_box(mouth) if mouth else None,
                                [fb.parse_box(x) for x in eyes.split("/")] if eyes else None, trace)
    for n in face.notes:
        warn(f"  {n}")
    if face.mouth is None:
        return None
    info(f"  mouth at {face.mouth.text()}" + (f", eyes at {' and '.join(b.text() for b in face.eyes)}" if face.eyes else "")
         + "  {note}(x,y,w,h in grid pixels; --mouth / --eyes to change){/}")
    from ..common.config import load as load_pref
    shapes = load_pref("faces").get("mouth_shapes")
    images = fb.build(grid, face, shapes)
    same = fb.alike(images)
    if same:
        warn("  these mouths look the same at this size: " + ", ".join(f"{a}={b}" for a, b in same)
             + " - a larger mouth (--mouth) gives them room")
    out = out or image.parent / f"{name}-face"
    out.mkdir(parents=True, exist_ok=True)
    paths: dict[str, dict[str, Path]] = {}
    for g, tok in t["mouths"].items():
        if g not in images:
            continue
        for state in t.get("eyes", {"open": None}):
            f = out / faces.file_name(name, tok, state, t)
            images[g][state].save(f)
            paths.setdefault(g, {})[state] = f
    grid.save(out / f"{name}-base.png")                    # the image as put on the grid (for 'face show')
    if face.blank is not None:
        face.blank.save(out / f"{name}-blank.png")             # no eyes or mouth (0.20.7)
    ov = fb.overlay(grid, face)
    ov.save(out / f"{name}-boxes.png")                       # where the mouth and eyes are, with a ruler
    import json as _json
    try:                                                       # colour touch-ups made in the viewer (0.20.5)
        old_fix = _json.loads((out / f"{name}-build.json").read_text()).get("recolor", [])
    except (ValueError, OSError):
        old_fix = []
    (out / f"{name}-boxes.json").write_text(_json.dumps(ov.info["seqtool"]), encoding="utf-8")   # for the viewer
    (out / f"{name}-build.json").write_text(_json.dumps({                       # the viewer's 'face build' line
        "prop": prop["id"], "image": str(image.resolve()), "name": name, "mouth": face.mouth.text(),
        "eyes": "/".join(b.text() for b in face.eyes), **({"recolor": old_fix} if old_fix else {}),
        **({"marks": str(Path(where).resolve())} if md else {}), "grid": [cols, rows]}),
        encoding="utf-8")
    from ..common import config
    built = dict(config.answer("built_faces") or {})
    built[name] = str(out.resolve())
    config.remember("built_faces", built)
    if trace is not None:
        from ..common.debuglog import DebugLog
        dbg = DebugLog(out / f"{name}-debug.txt", f"seqtool face build --debug: {image.name} on {prop['id']}")
        dbg.kv(image=f"{image} ({src.width}x{src.height})", grid=f"{cols}x{rows}",
               given=f"mouth {mouth or '-'}, eyes {eyes or '-'}")
        dbg.head("detection")
        for t_ in trace:
            dbg.line(t_)
        dbg.head("colours (0.19.6: fills from just outside each box; lips/tongue the darkest, teeth the lightest "
                 "in the mouth box)")
        dbg.kv(lips=face.mouth_color, tongue=face.tongue_color, teeth=face.teeth_color,
               around_mouth=fb.ring_colour(grid, face.mouth, fallback=face.skin),
               eyelids=", ".join(str(fb.ring_colour(grid, b, fallback=face.skin)) for b in face.eyes) or "-")
        dbg.head("mouths that came out the same")
        dbg.line(", ".join(f"{a_}={b_}" for a_, b_ in same) or "none")
        dbg.save()
    sheet = out / f"{name}-sheet.png"
    fb.sheet(images).save(sheet)
    for a_, b_ in old_fix:                                  # the viewer's touch-ups, again
        fb.recolor([f for v in paths.values() for f in v.values()] + [sheet]
                   + ([out / f"{name}-blank.png"] if face.blank is not None else []), a_, b_)
    if old_fix:
        info(f"  {len(old_fix)} colour touch-up(s) from the viewer applied again")
    kinds = {f"{name}-base.png": "base", f"{name}-blank.png": "blank", f"{name}-boxes.png": "boxes", sheet.name: "sheet"}
    for f_ in [f for v in paths.values() for f in v.values()] + [out / k for k in kinds]:
        if f_.is_file():                                      # 0.22.3: so a later build can tell it isn't an original
            try:
                fmarks.mark_made(f_, {"kind": kinds.get(f_.name, "mouth"), "face": name, "from": str(image.resolve())})
            except (OSError, ValueError):
                pass
    snip = faces.snippet(name, paths, typ, t)
    xml = out / f"{name}.faceInfo.xml"
    xml.write_text(snip + "\n", encoding="utf-8")
    if any(f["name"] == name for f in prop.get("faces", [])):
        warn(f"  {prop['id']} already has a face named '{name}' - pasting adds a second one ('--name' gives another)")
    good(f"wrote {sum(len(v) for v in paths.values())} images to {show(out)}, the contact sheet {show(sheet)} "
         f"and the face definition {show(xml)}")
    info(f"  where the mouth and eyes were put, with a pixel ruler: {show(out / (name + '-boxes.png'))} "
         "{note}(the first picture in 'face show'; drag a rectangle on it there to mark the mouth or an eye and "
         "copy the command){/}")
    info(f"{{head}}To add the face in xLights:{{/}} close xLights, then {{do}}face write {name}{{/}} puts it in "
         "xlights_rgbeffects.xml (a copy of the file is kept first) - or by hand:")
    info("  {do}1. close xLights and make a copy of xlights_rgbeffects.xml (in your show folder){/}")
    info(f"  {{do}}2. open xlights_rgbeffects.xml in a text editor, find <model name=\"{prop['id']}\" ...> and paste "
         "the face definition below inside it, next to its other <faceInfo .../> lines (if the model's line ends "
         "in '/>', change that to '>' and add '</model>' after the pasted line); save{/}")
    info(f"  {{do}}3. start xLights: the Faces effect on {prop['id']} now offers '{name}'{{/}}")
    info(f"  {{do}}4. back here, type 'layout' so seqtool reads the changed xlights_rgbeffects.xml: then 'face list' "
         f"shows '{name}' and 'face use {prop['id']} {name}' makes {prop['id']} sing with it{{/}}")
    from ..common.prompt import gui_asker
    from ..common.shellcmds import to_clipboard
    tool = None if gui_asker() is not None else to_clipboard(snip)
    info("the face definition" + (f" ({{ok}}already copied to the clipboard{{/}} with {tool})" if tool else
                                   " (the Copy button copies it)" if gui_asker() is not None else "") + ":")
    print("{copy}" + snip + "{/}")
    from ..gui import server
    srv = server.running()
    if srv is not None and srv.hub.clients:
        show_face(name, prop["id"])
    else:
        info(f"  {{note}}'face show {name}' flips through the images in the GUI{{/}}")
    return xml


def _rgbeffects() -> Path:
    from ..layout import store
    src = store.source_info()
    if not src or not Path(src["path"]).is_file():
        raise SystemExit("no xlights_rgbeffects.xml to write to - 'layout path/to/xlights_rgbeffects.xml' first")
    return Path(src["path"])


def _confirm(what: str, yes: bool) -> None:
    from ..common.prompt import ask, interactive
    if yes:
        return
    if not interactive():
        raise SystemExit(f"{what}: add --yes (xLights must be closed - it would write its own copy over this)")
    if ask(f"{what} - is xLights closed? (it would save its own copy over the change) [y/N]", "n",
           show_default=False).lower() not in ("y", "yes"):
        raise SystemExit("nothing changed")


def _reread(path: Path) -> None:
    """The stored layout again from the changed file, so 'face list' / 'face use' see it."""
    from ..layout import store
    try:
        store.ingest(path)
        info("  the stored layout was read again from it")
    except Exception as e:  # noqa: BLE001
        warn(f"  couldn't read the layout again ({e}) - 'layout' does it")


def write_face(name: str, prop_name: str | None = None, yes: bool = False) -> int:
    """face write NAME: the built face into xlights_rgbeffects.xml (0.22.3)."""
    import json as _json
    from ..common import config
    from ..adapters.xlights import faces, write_faces as wf
    built = config.answer("built_faces") or {}
    hit = next((k for k in built if k.lower() == name.lower()), None)
    if hit is None:
        raise SystemExit(f"no built face '{name}' - 'face build MODEL IMAGE' makes one; 'face list' shows them")
    d = Path(built[hit])
    xml, bj = d / f"{hit}.faceInfo.xml", d / f"{hit}-build.json"
    if not xml.is_file():
        raise SystemExit(f"{show(xml)} is missing - 'face build' it again")
    snip = xml.read_text(encoding="utf-8").strip()
    info_ = _json.loads(bj.read_text()) if bj.is_file() else {}
    lay = _layout()
    prop = _prop(lay, prop_name or info_.get("prop") or "")
    got = faces.matrix_format(_format(lay))
    name_key = (got[1].get("name_key") if got else None) or "Name"
    path = _rgbeffects()
    text = wf.load(path)
    try:
        new, replaced = wf.put_face(text, prop["id"], snip, hit, name_key)
    except LookupError as e:
        raise SystemExit(f"{path.name}: {e} - is the stored layout from this file? ('layout' reads it again)")
    _confirm(f"put the face '{hit}' on {prop['id']} in {show(path)}" + (" (replacing the one there)" if replaced else ""), yes)
    try:
        copy = wf.save(path, new)
    except ValueError as e:
        raise SystemExit(str(e))
    good(f"{prop['id']} has the face '{hit}' in {show(path)}" + (" (replaced)" if replaced else "")
         + f"; the old file is kept as {show(copy)}")
    _reread(path)
    info(f"  {{note}}next: 'face use {prop['id']} {hit}' makes it sing; xLights shows the face when it starts again{{/}}")
    return 0


def remove_face(name: str, prop_name: str | None = None, xlights: bool = False, yes: bool = False) -> int:
    """face remove NAME [--xlights]: forget a built face; --xlights: also out of the file (0.22.3)."""
    from ..common import config
    built = dict(config.answer("built_faces") or {})
    hit = next((k for k in built if k.lower() == name.lower()), None)
    done = False
    if hit is not None:
        folder = built.pop(hit)
        config.remember("built_faces", built)
        good(f"forgot the built face '{hit}' - its pictures stay in {show(Path(folder))} (delete the folder if you "
             "don't want them)")
        done = True
    if xlights:
        from ..adapters.xlights import faces, write_faces as wf
        lay = _layout()
        props = [_prop(lay, prop_name)] if prop_name else \
            [p for p in lay["props"] if any(f["name"].lower() == name.lower() for f in p.get("faces", []))]
        if not props:
            raise SystemExit(f"no prop in the stored layout has a face '{name}' - 'face list' shows them")
        got = faces.matrix_format(_format(lay))
        name_key = (got[1].get("name_key") if got else None) or (_format(lay) or {}).get("name_key") or "Name"
        path = _rgbeffects()
        text, n = wf.load(path), 0
        real = next((f["name"] for p in props for f in p.get("faces", []) if f["name"].lower() == name.lower()), name)
        for p in props:
            text, k = wf.drop_face(text, p["id"], real, name_key)
            n += k
        if not n:
            raise SystemExit(f"'{real}' isn't in {show(path)} any more - 'layout' reads the file again")
        _confirm(f"take the face '{real}' off {', '.join(p['id'] for p in props)} in {show(path)}", yes)
        copy = wf.save(path, text)
        good(f"took '{real}' out of {show(path)}; the old file is kept as {show(copy)}")
        targets = config.load("models").get("targets", {})
        for p in props:
            if (targets.get(p["id"]) or {}).get("face") == real:
                warn(f"  {p['id']} was set to sing with it - 'face use {p['id']} off' (or another face)")
        _reread(path)
        done = True
    if not done:
        raise SystemExit(f"no built face '{name}' (to take one out of xlights_rgbeffects.xml: --xlights)")
    return 0


MADE_SAYS = {"boxes": "it has the mouth and eye boxes (and a ruler) drawn on it, which would be drawn in again",
             "mouth": "it already has a mouth and eyes drawn on it", "blank": "its mouth and eyes were filled in",
             "base": "it is the picture already put on the grid", "sheet": "it is the contact sheet"}


def made_picture(image: Path) -> dict | None:
    """What 'face build' made this picture as ({"kind", "face", "from"}), or None for an original.
    The PNG says so itself since 0.22.3; older ones: a picture in a built face's folder."""
    import json as _json
    from . import marks as fmarks
    got = fmarks.made(image)
    if got:
        return got
    d = image.parent
    for bj in sorted(d.glob("*-build.json")):
        try:
            b = _json.loads(bj.read_text())
        except (OSError, ValueError):
            continue
        n = b.get("name") or bj.stem[: -len("-build")]
        if image.name.startswith(n) and image.suffix.lower() == ".png" and \
                Path(b.get("image", "")).resolve() != image.resolve():
            stem = image.stem[len(n):]
            kind = next((k for k in ("boxes", "base", "blank", "sheet") if stem == f"-{k}"), "mouth")
            return {"kind": kind, "face": n, "from": b.get("image")}
    return None


def _not_a_made_picture(image: Path) -> Path:
    """0.22.3 (the user's case: the boxes came out twice): building from a picture 'face build'
    made draws the boxes / mouth / eyes in again - say so and offer the original."""
    got = made_picture(image)
    if not got:
        return image
    from ..common.prompt import ask
    orig = Path(got["from"]) if got.get("from") else None
    warn(f"{image.name} is a picture 'face build' made for the face '{got.get('face', '?')}' - "
         f"{MADE_SAYS.get(got.get('kind'), 'not the original')}")
    if orig is not None and orig.is_file():
        if ask(f"build from the original picture {show(orig)} instead? [Y/n]", "y",
               show_default=False).lower() not in ("n", "no"):
            info(f"  using {show(orig)}")
            return orig
        warn(f"  going on with {image.name}, as asked")
    else:
        warn(f"  its original ({got.get('from') or 'unknown'}) isn't there any more - going on with {image.name}")
    return image


def _area(text: str | None) -> list[int] | None:
    if not text:
        return None
    try:
        v = [int(round(float(x))) for x in text.replace("%", "").split(",")]
    except ValueError:
        v = []
    if len(v) != 4 or v[2] <= 0 or v[3] <= 0 or v[0] < 0 or v[1] < 0 or v[0] + v[2] > 100 or v[1] + v[3] > 100:
        raise SystemExit(f"--area {text}: x,y,w,h in percent of the prop, from its top left - e.g. "
                         "'--area 0,0,50,100' (the left half) or '--area 50,0,50,100' (the right half)")
    return v


def _entry_text(e: dict) -> str:
    return e["face"] + (f", voice {e['voice']}" if e.get("voice") else "") + \
        (f", area {','.join(map(str, e['area']))}%" if e.get("area") else "")


def use(words: list[str], over: bool = True, voice: str | None = None, area: str | None = None,
        add: bool = False, song: bool = False, only: bool = False) -> int:
    """face use [PROP [FACE|off] [@#N]]: which face(s) a prop sings with, and where (0.24.0: singing
    is the reaction preset 'sing' - the whole song, or per song / section like any reaction)."""
    from ..common import config
    targets = config.load("models").get("targets", {})
    times = [w for w in words if w.startswith("@")]
    words = [w for w in words if not w.startswith("@")]
    if not words:
        rows = []
        for k, v in sorted(targets.items()):
            ents = v.get("sing") or ([{"face": v["face"]}] if v.get("face") not in (None, "off", "none") else [])
            if ents:
                rows.append((k, ents, "sing" in str(v.get("react", "")) or "face_mode" in v, v.get("sing_over")))
        if not rows:
            print("no prop has a singing face yet - e.g. 'face use Matrix Showman' ('face list' shows the faces)")
        for k, ents, whole, ov in rows:
            print(f"  {k:<24} " + "; ".join(_entry_text(e) for e in ents)
                  + ("   - sings the whole song" if whole else "   - sings where 'react ... sing @#N' says")
                  + ("   (on top of its other effects)" if ov else ""))
        print("{note}per section: 'react PROP sing @#3' (or the GUI's react menu); 'react PROP off @#5' stops it there{/}")
        return 0
    lay = _layout()
    prop = _prop(lay, words[0])
    pid = prop["id"]
    names = [f["name"] for f in prop.get("faces", [])]
    if len(words) < 2:
        if not names:
            raise SystemExit(f"{pid} has no face yet - 'face build {pid} IMAGE', then 'face write NAME'")
        raise SystemExit(f"face use {pid} FACE - its faces: {', '.join(names)}")
    face = " ".join(words[1:])
    tp = targets.get(pid, {})
    react = [n for n in str(tp.get("react") or "").split(",") if n and n != "off"]
    if face == "off":
        rest = [n for n in react if n != "sing"]
        config.update("models", {"targets": {pid: {"face": "off", "sing": [], "react": ",".join(rest) or "off"}}})
        _replan(f"{pid}: no singing face" + (" (its other reactions stay: " + ",".join(rest) + ")" if rest else ""), pid)
        return 0
    hit = [n for n in names if n.lower() == face.lower()]
    if not hit:
        from ..common.suggest import suggest
        raise SystemExit(f"{pid} has no face '{face}'" + (suggest(face, names) if names else
                         f" (no faces at all - 'face build {pid} IMAGE', then 'face write NAME')")
                         + " - a face added in xLights since: 'layout' again")
    entry = {"face": hit[0], **({"voice": voice} if voice else {}), **({"area": _area(area)} if area else {})}
    old = tp.get("sing") or ([{"face": tp["face"]}] if tp.get("face") not in (None, "off", "none") else [])
    sing = [e for e in old if not (e["face"] == entry["face"] and e.get("voice") == entry.get("voice"))] + [entry] \
        if add else [entry]
    change = {"face": hit[0], "sing": sing}
    whole = not times and not song
    if whole:
        change.update({"react": ",".join(["sing"] + [n for n in react if n != "sing"]), "sing_over": bool(over)})
    config.update("models", {"targets": {pid: change}})
    if "face_mode" in tp:                                  # before 0.24.0
        mp = config.load("models")
        f = config.user_dir() / "models.json"
        try:
            import json as _json
            d = _json.loads(f.read_text())
            d.get("targets", {}).get(pid, {}).pop("face_mode", None)
            f.write_text(_json.dumps(d, indent=2) + "\n")
        except (OSError, ValueError):
            pass
    if not prop.get("controllable", True):
        warn(f"{pid} is not sequenced ({prop.get('skip_reason', 'not usable')}), so it won't sing until that changes")
    if voice:
        try:
            from ..music.lyrics import _song, for_music  # noqa: F401
            from ..music.voices import names as vnames
            from ..common import songs
            from ..common.canonical import file_sha256
            la = config.answer("last_audio")
            doc = songs.get(file_sha256(Path(la))).get("lyrics") if la and Path(la).exists() else None
            if doc and not any(v.upper() == voice.upper() for v in vnames(doc)):
                warn(f"  the current song's lyrics have no voice '{voice}' yet" + (f" (they have: {', '.join(vnames(doc))})"
                     if vnames(doc) else "") + f" - mark it: 'lyrics voice {voice} @LINE.WORD' or {{{voice}}} in the "
                     "words; until then it sings every word")
        except Exception:  # noqa: BLE001
            pass
    good(f"{pid}: " + "; ".join(_entry_text(e) for e in sing)
         + (" - sings the whole song" + (" on top of its other effects" if over else " (its other effects rest "
                                        "while it sings)") if whole else ""))
    if not whole:
        from ..matchup.react_cmd import main as react_main
        return react_main([pid, "sing", *times] + (["--song"] if song and not times else [])
                          + (["--only"] if only else []) + (["--over"] if over else []))
    if len(sing) > 1 and not all(e.get("area") for e in sing):
        info("  {note}several faces on one prop: give each its place, e.g. --area 0,0,50,100 and --area 50,0,50,100{/}")
    info("{note}per section instead: 'face use PROP FACE @#3' or 'react PROP sing @#3'; needs lyrics with word "
         "times and the kit's Faces step ('xlights-kit --update'){/}")
    _replan(f"{pid}: sings with its face {hit[0]}", pid)
    return 0


def _replan(label: str, pid: str) -> None:
    """0.24.16: the plan follows at once (as after react or pin), when there is one; 0.24.17: this
    song's own reaction settings for the prop give way (the later command wins)."""
    from ..common import config
    if not config.answer("last_run") or not config.answer("last_matchup"):
        good(label + " - 'run' makes a plan with it")
        return
    from ..matchup.react_cmd import replan_every_song
    replan_every_song(pid, label)


def face_images(name: str, prop: str | None = None) -> tuple[str, list[tuple[str, Path]]]:
    """(title, [(label, image file)]) for a face: one just built (its folder), else one in
    the stored layout (its image paths)."""
    from . import build as fb
    from ..common import config
    built = config.answer("built_faces") or {}
    hit = next((k for k in built if k.lower() == name.lower()), None)
    if hit and Path(built[hit]).is_dir():                     # a face just built: its folder (with the base image)
        d = Path(built[hit])
        files = sorted(d.glob("*.png"))
        out = [(lab, d / f"{hit}-{suf}.png") for lab, suf in
               (("base image (as put on the grid) - mark the mouth and eyes here", "base"),
                ("without eyes and mouth (filled from the colours round them)", "blank"),
                ("where the mouth (red) and eyes (cyan) are - x,y,w,h for --mouth / --eyes", "boxes")) if (d / f"{hit}-{suf}.png").exists()]
        for m in fb.MOUTHS:
            for state in ("open", "closed"):
                f = next((x for x in files if re.search(rf"[_\- ]{re.escape(m)}[_\- ](e?{state[0]}|eyes{state})",
                                                        x.stem, re.I)), None)
                if f:
                    out.append((f"{m}, eyes {state}", f))
        return f"{hit} (built in {d.name}/)", out
    lay = _layout()
    cands = [(p, f) for p in lay["props"] for f in p.get("faces", []) if f["name"].lower() == name.lower()
             and (prop is None or p["id"].lower() == prop.lower())]
    if not cands:
        from ..common.suggest import suggest
        names = sorted({f["name"] for p in lay["props"] for f in p.get("faces", [])} | set(built))
        raise SystemExit(f"no face '{name}'" + (f" on {prop}" if prop else "") + suggest(name, names)
                         + " - 'face list' shows them")
    p, f = cands[0]
    if f.get("kind") != "images":
        raise SystemExit(f"'{f['name']}' on {p['id']} is a node-range face - only image (matrix) faces can be "
                         "shown so far")
    out = []
    for m in fb.MOUTHS:
        for state in ("open", "closed"):
            v = f.get("mouths", {}).get(m, {}).get(state)
            if v:
                out.append((f"{m}, eyes {state}", Path(v)))
    others = [x["id"] for x, _ in cands[1:]]
    return f"{f['name']} on {p['id']}" + (f" (also on {', '.join(others)}: --prop)" if others else ""), out


def touch_up(images: list[str], src: str, dst: str, scope: str = "all", index: int | None = None) -> dict:
    """The GUI's colour touch-up (0.20.5): src -> dst in this image or in every image of the
    face (not the boxes picture); kept in <name>-build.json so 'face build' again re-applies it."""
    import json as _json
    from . import build as fb
    files = [Path(f) for f in images]
    faces = [f for f in files if not f.stem.endswith(("-boxes", "-base"))]
    if scope == "this" and index is not None and 0 <= index < len(files) and files[index] not in faces:
        return {"changed": 0, "files": 0, "why": "the base and boxes pictures aren't part of the face"}
    pick = [files[index]] if scope == "this" and index is not None and 0 <= index < len(files) else faces
    n = fb.recolor(pick, src, dst)
    if scope != "this" and faces:
        bj = next(iter(sorted(faces[0].parent.glob("*-build.json"))), None)
        if bj is not None:
            d = _json.loads(bj.read_text())
            d.setdefault("recolor", []).append([src.upper(), dst.upper()])
            bj.write_text(_json.dumps(d), encoding="utf-8")
    return {"changed": n, "files": len(pick)}


def _source_image(images: list[str], name: str) -> Path | None:
    """The picture a shown face was built from (its <name>-build.json)."""
    import json as _json
    d = Path(images[0]).parent
    for bj in [d / f"{name}-build.json"] + sorted(d.glob("*-build.json")):
        try:
            img = _json.loads(bj.read_text()).get("image")
        except (OSError, ValueError):
            continue
        if img and Path(img).exists():
            return Path(img)
    return None


def save_marks(images: list[str], name: str, marks: dict) -> dict:
    """The viewer's marked pixels and picked colours (0.20.7): kept inside the face's own
    picture when it is a PNG (0.20.8, the user's idea - 'face build PROP IMAGE' then finds
    them by itself), else as <name>-marks.json in the face's folder (--marks FILE)."""
    import json as _json
    import re as _re
    if not images:
        return {"error": "no face shown - 'face show NAME' first"}
    safe = _re.sub(r"[^\w.\- ]", "_", name or "face").strip() or "face"
    pts = lambda v: [[int(p[0]), int(p[1])] for p in v if isinstance(p, (list, tuple)) and len(p) == 2]  # noqa: E731
    eyes = [pts(e) for e in (marks.get("eyes") or [])[:2]]
    cols = {k: v for k, v in (marks.get("colors") or {}).items()
            if k in ("lips", "tongue", "teeth", "eyelid", "eyeball", "pupil")
            and isinstance(v, str) and _re.fullmatch(r"#[0-9a-fA-F]{6}", v)}
    doc = {"mouth": pts(marks.get("mouth") or []), "eyes": eyes, "colors": cols}
    if marks.get("grid"):
        doc["grid"] = [int(x) for x in marks["grid"][:2]]
    if not doc["mouth"]:
        return {"error": "mark the mouth's pixels first (the 'mouth' tool)"}
    from . import marks as fmarks
    src = _source_image(images, safe)
    res = {"mouth": len(doc["mouth"]), "eyes": [len(e) for e in eyes]}
    if src is not None and fmarks.is_png(src):
        try:
            fmarks.write(src, doc)
            return {**res, "path": str(src.resolve()), "in_image": True}
        except OSError as e:
            res["note"] = f"couldn't write into {src.name} ({e}); kept beside it instead"
    f = Path(images[0]).parent / f"{safe}-marks.json"
    f.write_text(_json.dumps(doc), encoding="utf-8")
    return {**res, "path": str(f.resolve())}


def show_face(name: str, prop: str | None = None) -> list[str]:
    title, imgs = face_images(name, prop)
    have = [(lab, f) for lab, f in imgs if f.exists()]
    lost = [f for _, f in imgs if not f.exists()]
    L = []
    if lost:
        L.append(f"{{warn}}{len(lost)} image(s) not found here{{/}}, e.g. {lost[0]}")
    if not have:
        return L + [f"{title}: no images to show"]
    from ..gui import server
    srv = server.running()
    if srv is not None and srv.hub.clients:
        import time
        srv.images = [str(f) for _, f in have]
        def meta(f):                                 # where a picture's pixels are on the prop's grid
            import json as _json
            j = f.with_name(f.stem + ".json")
            if f.stem.endswith("-boxes") and j.exists():
                return _json.loads(j.read_text())
            try:
                from PIL import Image
                with Image.open(f) as im:
                    return {"cols": im.width, "rows": im.height, "k": 1, "m": 0, "boxes": []}
            except Exception:  # noqa: BLE001
                return None
        cmd = None
        bj = have[0][1].parent / (have[0][1].stem.rsplit("-", 1)[0] + "-build.json")
        if bj.exists():
            try:
                import json as _json
                cmd = _json.loads(bj.read_text())
            except ValueError:
                cmd = None
        marks = None
        mname = (cmd or {}).get("name") or name
        from . import marks as fmarks
        src = Path(cmd["image"]) if cmd and cmd.get("image") else None
        if src is not None and src.exists() and fmarks.read(src):                  # kept in the picture (0.20.8)
            marks = {**fmarks.read(src), "path": str(src), "in_image": True}
        else:
            mf = (Path(cmd["marks"]) if cmd and cmd.get("marks") else have[0][1].parent / f"{mname}-marks.json")
            if mf.exists() and mf.suffix == ".json":
                try:
                    import json as _json
                    marks = _json.loads(mf.read_text())
                    marks["path"] = str(mf)
                except ValueError:
                    marks = None
        srv.hub.send("faceview", {"title": title, "v": int(time.time()), "cmd": cmd, "marks": marks, "name": mname,
                                  "images": [{"label": lab, "i": i, "grid": meta(f)} for i, (lab, f) in enumerate(have)]})
        L.append(f"{title}: {len(have)} images in the GUI - flip with < > or the arrow keys, Esc closes")
    else:
        L.append(f"{title}: {len(have)} images" + "  {note}('gui' opens a viewer to flip through them){/}")
        L += [f"  {lab:<22} {show(f)}" for lab, f in have]
    return L


def inspect_face(args) -> list[str]:
    if not args:
        raise SystemExit("inspect face NAME - 'face list' shows the faces")
    return show_face(" ".join(args))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool face", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("words", nargs="*", help="build MODEL IMAGE | use PROP FACE | show NAME | write NAME | remove NAME | list | format")
    ap.add_argument("--name", help="the face's name in xLights (default: the image's name)")
    ap.add_argument("--mouth", help="the mouth as x,y,w,h in grid pixels (default: found in the image)")
    ap.add_argument("--eyes", help="the eyes as x,y,w,h/x,y,w,h in grid pixels (default: found)")
    ap.add_argument("--marks", type=paths_arg, help="build: the mouth and eye pixels (and colours) marked in "
                    "the GUI's face viewer, from another file (a PNG holding them, or a <name>-marks.json) - "
                    "marks kept in IMAGE itself are used without it")
    ap.add_argument("--no-marks", action="store_true", help="build: ignore marks kept in IMAGE; find the mouth "
                    "and eyes (or --mouth / --eyes)")
    ap.add_argument("--out", type=paths_arg, help="folder for the images (default: <image name>-face next to the image)")
    ap.add_argument("--debug", action="store_true", help="build: write <name>-face/<name>-debug.txt - every "
                    "feature found, the eye pairs tried, the mouth candidates and why")
    ap.add_argument("--prop", help="show: the prop whose face to show (when several have one of that name)")
    ap.add_argument("--over", action=argparse.BooleanOptionalAction, default=True,
                    help="use: the face on top of the prop's other effects, which show behind it (the default, "
                    "0.24.47); --no-over: they rest while it sings")
    ap.add_argument("--voice", help="use: sing only this voice's words (and ALL's) - {VOICE} codes in the lyrics")
    ap.add_argument("--area", help="use: where on the prop, x,y,w,h in percent from its top left (several faces on one "
                    "matrix) - e.g. 0,0,50,100")
    ap.add_argument("--add", action="store_true", help="use: another face on the same prop (the others stay)")
    ap.add_argument("--song", action="store_true", help="use: this song only (with @#N: that section)")
    ap.add_argument("--only", action="store_true", help="use with @#N: that section, not its repeats")
    ap.add_argument("--xlights", action="store_true", help="remove: also take it out of xlights_rgbeffects.xml (a copy is kept first)")
    ap.add_argument("--yes", action="store_true", help="write / remove --xlights: don't ask whether xLights is closed")
    a = ap.parse_args(argv)
    w = a.words or ["list"]
    if w[0] == "use":
        return use(w[1:], a.over, a.voice, a.area, a.add, a.song, a.only)
    if w[0] == "show":
        if len(w) < 2:
            raise SystemExit("face show NAME [--prop PROP] - 'face list' shows the faces")
        print("\n".join(show_face(" ".join(w[1:]), a.prop)))
        return 0
    if w[0] in ("write", "remove"):
        if len(w) < 2:
            raise SystemExit(f"face {w[0]} NAME - 'face list' shows the faces")
        nm = " ".join(w[1:])
        return write_face(nm, a.prop, a.yes) if w[0] == "write" else remove_face(nm, a.prop, a.xlights, a.yes)
    if w[0] == "list":
        print("\n".join(list_faces(_layout())))
        return 0
    if w[0] == "format":
        print("\n".join(show_format(_layout())))
        return 0
    if w[0] == "build":
        if len(w) != 3:
            raise SystemExit("face build MODEL IMAGE - e.g. 'face build Matrix pumpkin.png'")
        from ..common.paths import expand
        try:
            image = expand(w[2], "file")                     # globs and ~, like every other path (0.19.1)
        except ValueError as e:
            raise SystemExit(f"face build: {e} - give more of the name")
        return 0 if build_face(w[1], image, a.name, a.mouth, a.eyes, a.out, a.debug, a.marks,
                               not a.no_marks) else 1
    raise SystemExit(f"face: unknown '{w[0]}' - 'face build MODEL IMAGE', 'face write NAME', 'face remove NAME', "
                     "'face list' or 'face format'")


if __name__ == "__main__":
    sys.exit(main())
