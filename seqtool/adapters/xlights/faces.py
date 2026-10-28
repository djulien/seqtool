"""Face definitions in xLights layouts (0.19): learned, not assumed.

xLights keeps singing-face definitions inside each model as <faceInfo .../> elements.
The attribute names (which key holds the 'AI' mouth with eyes open, which one the
face's name, how image paths are written) are read from the faces already in the
user's layout - whatever their xLights version wrote - and the writer copies that
format. Nothing here hard-codes 'Mouth-AI-EyesOpen'; the shipped format learned
from the user's 2025.13 layout (learned/faces-<version>.json) is only the fallback
for a layout without faces of that kind.

    learn_format(raw faces) -> format        (per face type: Matrix, NodeRange, ...)
    to_generic(raw, format) -> generic face  (mouths x eyes -> image paths or node ranges)
    snippet(name, images, format) -> '<faceInfo .../>' for a matrix (image) face
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from xml.sax.saxutils import quoteattr

# the usual Preston Blair / Papagayo mouth set; learned tokens are matched to these
GENERIC_MOUTHS = ["AI", "E", "etc", "FV", "L", "MBP", "O", "U", "WQ", "rest"]
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp")
NODES = re.compile(r"^\s*\d+(\s*-\s*\d+)?(\s*,\s*\d+(\s*-\s*\d+)?)*\s*$")
SHIPPED = Path(__file__).parent / "learned"


def raw_faces(model_el) -> list[dict]:
    return [dict(f.attrib) for f in model_el.findall("faceInfo")]


def _is_image(v: str) -> bool:
    return bool(v) and v.strip().lower().endswith(IMAGE_EXT)


def _generic_mouth(tok: str) -> str:
    return next((g for g in GENERIC_MOUTHS if g.lower() == tok.lower()), tok)


def _template(keys: list[str]) -> dict | None:
    """Keys of the same kind ('Mouth-AI-EyesOpen', ...) -> the template with the varying
    parts named: the part with the most values is the mouth, a second varying part the
    eye state."""
    if not keys:
        return None
    parts = [k.split("-") for k in keys]
    n = Counter(len(p) for p in parts).most_common(1)[0][0]
    parts = [p for p in parts if len(p) == n]
    vals = [list(dict.fromkeys(p[i] for p in parts)) for i in range(n)]
    varying = [i for i in range(n) if len(vals[i]) > 1]
    if not varying:
        return None
    mouth = max(varying, key=lambda i: len(vals[i]))
    eyes = next((i for i in varying if i != mouth), None)
    tpl = ["{mouth}" if i == mouth else "{eyes}" if i == eyes else vals[i][0] for i in range(n)]
    return {"template": "-".join(tpl), "mouths": vals[mouth], "eyes": vals[eyes] if eyes is not None else []}


def learn_format(faces: list[dict], version: str | None = None) -> dict:
    """faces: raw attribute dicts (from every model). Returns
    {"types": {TYPE: {...}}, "type_key", "name_key", "learned_from": n}."""
    if not faces:
        return {"types": {}, "learned_from": 0}
    everywhere = [k for k in faces[0] if all(k in f for f in faces)]
    plain = [k for k in everywhere if not any(_is_image(f[k]) or (f[k] and NODES.match(f[k])) for f in faces)]
    # the type marker has the fewest values, the name the most
    type_key = min(plain, key=lambda k: (len({f[k] for f in faces}), k)) if plain else "Type"
    rest = [k for k in plain if k != type_key]
    name_key = max(rest, key=lambda k: (len({f[k] for f in faces}), -everywhere.index(k))) if rest else "Name"
    out = {"type_key": type_key, "name_key": name_key, "learned_from": len(faces), "types": {}}
    if version:
        out["xlights_version"] = version
    for typ in dict.fromkeys(f.get(type_key, "") for f in faces):
        group = [f for f in faces if f.get(type_key, "") == typ]
        order = list(max(group, key=len))
        for f in group:
            order += [k for k in f if k not in order]
        image_keys = [k for k in order if any(_is_image(f.get(k, "")) for f in group)]
        node_keys = [k for k in order if any(f.get(k) and NODES.match(f[k]) for f in group)]
        kind = "images" if len(image_keys) >= len(node_keys) and image_keys else "nodes" if node_keys else "other"
        slot_keys = image_keys if kind == "images" else node_keys
        t = {"kind": kind, "count": len(group), "attribute_order": order}
        if kind == "images":
            tpl = _template(image_keys)
            if tpl:
                # eye states: the one every mouth has is 'open'; the other 'closed'
                use = Counter(tok for k in image_keys for f in group if _is_image(f.get(k, ""))
                              for tok in [_part(k, tpl)[1]])
                eyes = sorted(tpl["eyes"], key=lambda e: -use.get(e, 0))
                t.update(template=tpl["template"], mouths={_generic_mouth(m): m for m in tpl["mouths"]},
                         eyes={"open": eyes[0], **({"closed": eyes[1]} if len(eyes) > 1 else {})})
            paths = [f[k] for f in group for k in image_keys if _is_image(f.get(k, ""))]
            t["paths"] = _path_style(paths)
            t["file_names"] = _file_names(group, image_keys, t)
        elif kind == "nodes":
            mouth_keys = [k for k in node_keys if k.lower().startswith(("mouth",))]
            tpl = _template(mouth_keys)
            if tpl:
                t.update(template=tpl["template"], mouths={_generic_mouth(m): m for m in tpl["mouths"]})
        # other settings: kept when most faces of this type set them (their usual value)
        extra = {}
        for k in order:
            if k in slot_keys or k in (type_key, name_key):
                continue
            have = [f[k] for f in group if f.get(k)]
            if len(have) * 2 > len(group):
                extra[k] = Counter(have).most_common(1)[0][0]
        t["usual"] = extra
        out["types"][typ] = t
    return out


def _part(key: str, tpl: dict) -> tuple[str | None, str | None]:
    """(mouth token, eye token) of a key that fits the template, else (None, None)."""
    rx = "^" + re.escape(tpl["template"]).replace(r"\{mouth\}", "(?P<m>[^-]+)").replace(r"\{eyes\}", "(?P<e>[^-]+)") + "$"
    m = re.match(rx, key)
    if not m:
        return None, None
    return m.groupdict().get("m"), m.groupdict().get("e")


def _path_style(paths: list[str]) -> dict:
    absolute = sum(1 for p in paths if p.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", p))
    back = sum(1 for p in paths if "\\" in p)
    return {"absolute": absolute * 2 >= len(paths), "separator": "\\" if back * 2 > len(paths) else "/"}


def _file_names(group, image_keys, t) -> dict:
    """How the user's face images are named: '<base>_<mouth>_<eye code>.<ext>' with the
    eye codes they use (eo/ec, EO/EC ...)."""
    codes: dict[str, Counter] = {"open": Counter(), "closed": Counter()}
    seps, exts = Counter(), Counter()
    inv = {v: k for k, v in t.get("eyes", {}).items()}
    for f in group:
        for k in image_keys:
            p = f.get(k, "")
            if not _is_image(p):
                continue
            mouth, eye = _part(k, t) if "template" in t else (None, None)
            stem = Path(p.replace("\\", "/")).stem
            ext = Path(p).suffix.lower()
            exts[ext] += 1
            m = re.search(rf"([_\- .])({re.escape(mouth or '')})([_\- .])([A-Za-z]+)", stem, re.I) if mouth else None
            if m and eye in inv:
                seps[m.group(1)] += 1
                codes[inv[eye]][m.group(4)] += 1
    op = codes["open"].most_common(1)[0][0] if codes["open"] else "eo"
    cl = codes["closed"].most_common(1)[0][0] if codes["closed"] else "ec"
    cl = cl.lower() if op.islower() else cl.upper() if op.isupper() else cl      # one style for both
    return {"separator": seps.most_common(1)[0][0] if seps else "_", "open": op, "closed": cl,
            "ext": exts.most_common(1)[0][0] if exts else ".png"}


def to_generic(raw: dict, fmt: dict) -> dict:
    """One raw faceInfo -> {name, kind, type, mouths: {AI: {open: .., closed: ..}} or {AI: '1-5'}}."""
    typ = raw.get(fmt.get("type_key", "Type"), "")
    t = fmt.get("types", {}).get(typ, {})
    out = {"name": raw.get(fmt.get("name_key", "Name"), ""), "type": typ, "kind": t.get("kind", "other"),
           "mouths": {}}
    if "template" not in t:
        return out
    inv_m = {v: k for k, v in t.get("mouths", {}).items()}
    inv_e = {v: k for k, v in t.get("eyes", {}).items()}
    for k, v in raw.items():
        if not v:
            continue
        mouth, eye = _part(k, t)
        if mouth is None:
            continue
        g = inv_m.get(mouth, _generic_mouth(mouth))
        if t["kind"] == "images":
            out["mouths"].setdefault(g, {})[inv_e.get(eye, eye or "open")] = v
        elif NODES.match(v):
            out["mouths"][g] = v
    return out


def shipped_format() -> dict | None:
    files = sorted(SHIPPED.glob("faces-*.json"))
    return json.loads(files[-1].read_text(encoding="utf-8")) if files else None


def matrix_format(fmt: dict | None) -> tuple[str, dict] | None:
    """(type value, type format) of the image (matrix) kind: from the layout, else shipped."""
    for src in (fmt, shipped_format()):
        for typ, t in ((src or {}).get("types") or {}).items():
            if t.get("kind") == "images" and t.get("template"):
                return typ, {**t, "type_key": src.get("type_key", "Type"), "name_key": src.get("name_key", "Name"),
                             "from_layout": src is fmt}
    return None


def file_name(base: str, mouth: str, eye: str, t: dict) -> str:
    fn = t.get("file_names", {})
    sep = fn.get("separator", "_")
    return f"{base}{sep}{mouth}{sep}{fn.get(eye, 'eo' if eye == 'open' else 'ec')}.png"      # always written as PNG


def snippet(name: str, images: dict[str, dict[str, Path]], typ: str, t: dict) -> str:
    """'<faceInfo .../>' for a matrix face, attributes in the learned order. images:
    {generic mouth: {"open": path, "closed": path}}."""
    sep = t.get("paths", {}).get("separator", "/")
    vals: dict[str, str] = {t["name_key"]: name, t["type_key"]: typ}
    for g, tok in t["mouths"].items():
        for state, etok in t.get("eyes", {}).items():
            p = images.get(g, {}).get(state)
            key = t["template"].replace("{mouth}", tok).replace("{eyes}", etok)
            vals[key] = str(Path(p).resolve()).replace("/", sep) if p else ""
    for k, v in t.get("usual", {}).items():
        vals.setdefault(k, v)
    order = [k for k in t.get("attribute_order", []) if k in vals] + [k for k in vals if k not in t.get("attribute_order", [])]
    return "<faceInfo " + " ".join(f"{k}={quoteattr(vals[k])}" for k in order) + "/>"
