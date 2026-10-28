"""Where singing starts and stops, for snapping lyric edges in the magnifier (0.24.8).

From the vocal stem (the whole mix without one): the level every 10 ms, lightly smoothed, with
two thresholds - 'on' well above the stem's quiet level, 'off' a few dB below it. A rising edge
is placed where the rise begins (the last quiet point before the level crossed 'on'); a falling
edge where the fall ends (the first quiet point after it dropped under 'off'), so a phrase or
word snapped to them holds the whole sound.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

HOP_S = 0.01


def envelope_db(path: Path) -> np.ndarray:
    from . import decode
    hop = int(round(decode.SR * HOP_S))
    out, carry = [], np.zeros(0, dtype=np.float32)
    for chunk in decode.chunks(path):
        carry = np.concatenate([carry, chunk])
        m = len(carry) // hop
        if m:
            out.append(np.sqrt((carry[: m * hop].reshape(m, hop) ** 2).mean(axis=1)))
            carry = carry[m * hop:]
    r = np.concatenate(out) if out else np.zeros(0)
    db = 20 * np.log10(r + 1e-9)
    if len(db) >= 5:
        db = np.convolve(db, np.ones(5) / 5, mode="same")             # 50 ms
    return db


def edges(db: np.ndarray, back: float = 0.3) -> dict:
    """{"rise": [s ...], "fall": [s ...]} from a 10 ms level curve in dB."""
    if len(db) == 0 or db.max() - db.min() < 6:
        return {"rise": [], "fall": []}
    floor, peak = np.percentile(db, 10), np.percentile(db, 98)
    on = max(floor + 10.0, peak - 24.0)
    off = on - 6.0
    quiet = min(off, floor + 4.0)
    nb = int(back / HOP_S)
    rise, fall = [], []
    active = False
    for i, v in enumerate(db):
        if not active and v > on:
            j = i
            while j > 0 and i - j < nb and db[j - 1] < db[j] and db[j - 1] > quiet:   # back down the rise
                j -= 1
            rise.append(round(j * HOP_S, 3))
            active = True
        elif active and v < off:
            j = i
            while j + 1 < len(db) and j - i < nb and db[j + 1] < db[j] and db[j + 1] > quiet:   # on down the fall
                j += 1
            fall.append(round((j + 1) * HOP_S, 3))
            active = False
    if active:
        fall.append(round(len(db) * HOP_S, 3))
    return {"rise": rise, "fall": fall}


def vocal_edges(audio: Path) -> dict:
    """Rising / falling edges of the singing - from the vocal stem when there is one, else the
    mix. 0.24.37: kept with the stems (<song>-seqtool/stems/<song>.vocal-edges.json), made again
    when the file it was measured from changes - decoding the song each time took about a second."""
    import json
    from .stems import stem_path, stems_dir
    st = stem_path(Path(audio))
    src, f = ("vocals", st) if st.is_file() else ("mix", Path(audio))
    try:
        stat = f.stat()
        key = {"file": f.name, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "src": src}
    except OSError:
        key = None
    cache = stems_dir(Path(audio)) / f"{Path(audio).stem}.vocal-edges.json"
    if key:
        try:
            doc = json.loads(cache.read_text(encoding="utf-8"))
            if doc.get("key") == key:
                return doc["edges"]
        except (OSError, ValueError, KeyError):
            pass
    res = {**edges(envelope_db(f)), "src": src}
    if key:
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({"key": key, "edges": res}) + "\n", encoding="utf-8")
        except OSError:
            pass
    return res
