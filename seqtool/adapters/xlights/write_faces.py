"""Put a face into, or take one out of, xlights_rgbeffects.xml (0.22.3).

The file is edited as text, not re-written from a parsed tree, so everything else in it
stays exactly as xLights wrote it (attribute order, spacing, entities). Only the one
<model name="..."> element changes: a <faceInfo .../> line is added before its </model>
(a self-closing <model .../> is opened up), or the faceInfo with that name is replaced or
removed. The result must still parse as XML, or nothing is written.

A copy of the file is kept first in <show folder>/seqtool-backups/ (results never go
beside an input; xLights' own Backup folder is left alone).
"""
from __future__ import annotations

import re
import shutil
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import quoteattr


def _model_span(text: str, model: str) -> tuple[int, int, int, bool]:
    """(start of '<model', end of its open tag, end of the element, self-closing?)"""
    m = re.search(r"<model\b[^>]*?\sname=" + re.escape(quoteattr(model)) + r"[^>]*?(/?)>", text)
    if m is None:
        m = re.search(r"<model\b[^>]*?\sname='" + re.escape(model) + r"'[^>]*?(/?)>", text)
    if m is None:
        raise LookupError(f"no <model name=\"{model}\"> in the file")
    if m.group(1) == "/":
        return m.start(), m.end(), m.end(), True
    close = text.find("</model>", m.end())
    if close < 0:
        raise LookupError(f"<model name=\"{model}\"> has no </model>")
    return m.start(), m.end(), close + len("</model>"), False


def _face_re(name_key: str, name: str) -> re.Pattern:
    return re.compile(r"[ \t]*<faceInfo\b[^>]*?\s" + re.escape(name_key) + r"=" + re.escape(quoteattr(name))
                      + r"[^>]*/>[ \t]*\r?\n?")


def faces_in(text: str, model: str, name_key: str = "Name") -> list[str]:
    a, b, c, _ = _model_span(text, model)
    return re.findall(r"<faceInfo\b[^>]*?\s" + re.escape(name_key) + r"=\"([^\"]*)\"", text[a:c])


def put_face(text: str, model: str, snippet: str, name: str, name_key: str = "Name") -> tuple[str, bool]:
    """The model with this face (replacing one of the same name). (new text, replaced?)"""
    a, b, c, selfclosing = _model_span(text, model)
    line_start = text.rfind("\n", 0, a) + 1
    indent = re.match(r"[ \t]*", text[line_start:a]).group(0)
    nl = "\r\n" if "\r\n" in text[:4096] else "\n"
    if selfclosing:
        tag = text[a:b]
        opened = tag[:-2].rstrip() + ">"
        new = opened + nl + indent + "  " + snippet + nl + indent + "</model>"
        return text[:a] + new + text[b:], False
    block = text[a:c]
    block2, n = _face_re(name_key, name).subn("", block)
    close = block2.rfind("</model>")
    before = block2[:close]
    child_indent = indent + "  "
    m = re.search(r"\n([ \t]*)<(faceInfo|stateInfo|subModel|ControllerConnection|dimmingCurve)\b", before)
    if m:
        child_indent = m.group(1)
    before = before.rstrip(" \t")
    if not before.endswith("\n"):
        before += nl
    new_block = before + child_indent + snippet + nl + indent + block2[close:]
    return text[:a] + new_block + text[c:], n > 0


def drop_face(text: str, model: str, name: str, name_key: str = "Name") -> tuple[str, int]:
    a, b, c, selfclosing = _model_span(text, model)
    if selfclosing:
        return text, 0
    block, n = _face_re(name_key, name).subn("", text[a:c])
    return text[:a] + block + text[c:], n


def backup(path: Path) -> Path:
    d = path.parent / "seqtool-backups"
    d.mkdir(exist_ok=True)
    dst = d / f"{path.stem}-{time.strftime('%Y%m%d-%H%M%S')}{path.suffix}"
    shutil.copy2(path, dst)
    return dst


def load(path: Path) -> str:
    with open(path, encoding="utf-8", newline="") as f:          # keep its line endings
        return f.read()


def save(path: Path, text: str) -> Path:
    """Check it still parses, keep a copy of the old file, then write. Returns the copy."""
    try:
        ET.fromstring(text.encode("utf-8"))
    except ET.ParseError as e:
        raise ValueError(f"the changed file would not be valid XML ({e}) - nothing was written") from None
    copy = backup(path)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    return copy


def _child_re(tag: str, name: str, prefix: bool = False) -> re.Pattern:
    nm = re.escape(quoteattr(name)[:-1] if prefix else quoteattr(name))
    return re.compile(r"[ \t]*<" + tag + r"\b[^>]*?\sname=" + nm + (r"[^\"]*\"" if prefix else "")
                      + r"[^>]*/>[ \t]*\r?\n?")


def put_children(text: str, model: str, tag: str, snippets: list[str], drop_prefix: str) -> tuple[str, int]:
    """0.24.49: the model's <TAG name="PREFIX..."/> children replaced by `snippets` (self-closing
    elements, e.g. subModel). -> (new text, how many were there before)."""
    a, b, c, selfclosing = _model_span(text, model)
    nl = "\r\n" if "\r\n" in text[:4096] else "\n"
    line_start = text.rfind("\n", 0, a) + 1
    indent = re.match(r"[ \t]*", text[line_start:a]).group(0)
    if selfclosing:
        tag_ = text[a:b]
        opened = tag_[:-2].rstrip() + ">"
        body = "".join(nl + indent + "  " + sn for sn in snippets)
        return text[:a] + opened + body + nl + indent + "</model>" + text[b:], 0
    block = text[a:c]
    block2, n = _child_re(tag, drop_prefix, prefix=True).subn("", block)
    close = block2.rfind("</model>")
    before = block2[:close]
    child_indent = indent + "  "
    m = re.search(r"\n([ \t]*)<(subModel|faceInfo|stateInfo|ControllerConnection|dimmingCurve)\b", before)
    if m:
        child_indent = m.group(1)
    before = before.rstrip(" \t")
    if not before.endswith("\n"):
        before += nl
    new_block = before + "".join(child_indent + sn + nl for sn in snippets) + indent + block2[close:]
    return text[:a] + new_block + text[c:], n
