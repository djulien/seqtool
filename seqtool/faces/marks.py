"""The viewer's marks kept inside the face image (0.20.8, the user's idea).

A PNG can carry text chunks; the marks (mouth and eye pixels, picked colours, the grid
they were made on) are written as one tEXt chunk with the keyword 'seqtool-marks'. The
chunk is added to the file as it is - the picture's pixels and its other chunks are not
touched or re-encoded - so `face build PROP IMAGE` finds them again by itself. Other
image types (JPEG, GIF ...) keep their marks in NAME-marks.json beside the face's
pictures instead.
"""
from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

KEY = b"seqtool-marks"
SIG = b"\x89PNG\r\n\x1a\n"


def _chunks(data: bytes):
    i = len(SIG)
    while i + 8 <= len(data):
        n, typ = struct.unpack(">I4s", data[i:i + 8])
        yield typ, data[i:i + 12 + n], data[i + 8:i + 8 + n]
        i += 12 + n


def is_png(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(8) == SIG
    except OSError:
        return False


MADE = b"seqtool-made"        # 0.22.3: on every picture 'face build' writes - what it is


def read(path: Path, key: bytes = KEY) -> dict | None:
    """The marks kept in a PNG (or another seqtool chunk's JSON), or None."""
    if not is_png(path):
        return None
    data = Path(path).read_bytes()
    for typ, _, body in _chunks(data):
        if typ == b"tEXt" and body.startswith(key + b"\0"):
            try:
                return json.loads(body[len(key) + 1:].decode("latin-1"))
            except ValueError:
                return None
    return None


def made(path: Path) -> dict | None:
    """{"kind": "boxes" | "base" | "blank" | "mouth" | "sheet", "face": NAME, "from": original image}
    for a picture 'face build' made (0.22.3), else None."""
    return read(path, MADE)


def mark_made(path: Path, info: dict) -> None:
    write(path, info, MADE)


def write(path: Path, marks: dict | None, key: bytes = KEY) -> None:
    """Put the marks into the PNG (replacing earlier ones; None removes them), before IEND."""
    data = Path(path).read_bytes()
    if not data.startswith(SIG):
        raise ValueError(f"{path} is not a PNG")
    out = [SIG]
    for typ, raw, body in _chunks(data):
        if typ == b"tEXt" and body.startswith(key + b"\0"):
            continue                                   # the old marks
        if typ == b"IEND" and marks is not None:
            body = key + b"\0" + json.dumps(marks, separators=(",", ":")).encode("ascii")
            out.append(struct.pack(">I", len(body)) + b"tEXt" + body
                       + struct.pack(">I", zlib.crc32(b"tEXt" + body) & 0xFFFFFFFF))
        out.append(raw)
    tmp = Path(path).with_name(Path(path).name + ".seqtool-tmp")
    tmp.write_bytes(b"".join(out))
    tmp.replace(path)
