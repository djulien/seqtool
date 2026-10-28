"""Near matches for mistyped words, names and numbers (0.24.34), when the valid values are
known ahead (layout names, the song's sections and sung words, seqtool's own words).

A weighted Damerau-Levenshtein distance: a missing or extra character costs 1, two characters
swapped 0.8, a neighbouring key on the keyboard 0.5, a digit that looks alike (6/8/9/0, 1/7, 3/8,
5/8, 2/5, 4/9) 0.4, any other character 1. Similarity = 1 - distance / the longer length.

    resolve("chrous", ["chorus", "verse"])  -> ("near", "chorus", 0.87)
    kinds: "exact", "near" (>= accept: use it), "unsure" (>= ask: ask the user), "none"
"""
from __future__ import annotations

_ROWS = ("qwertyuiop", "asdfghjkl", "zxcvbnm")
_POS = {c: (x, y) for y, row in enumerate(_ROWS) for x, c in enumerate(row)}
_DIGITS = (set("6890"), set("17"), set("38"), set("58"), set("25"), set("49"))


def _sub(a: str, b: str) -> float:
    if a == b:
        return 0.0
    if a.isdigit() and b.isdigit():
        return 0.4 if any(a in g and b in g for g in _DIGITS) else 1.0
    pa, pb = _POS.get(a), _POS.get(b)
    if pa and pb and abs(pa[0] - pb[0]) + abs(pa[1] - pb[1]) == 1:
        return 0.5
    return 1.0


def distance(a: str, b: str) -> float:
    a, b = a.lower(), b.lower()
    if a == b:
        return 0.0
    n, m = len(a), len(b)
    d = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        d[i][0] = float(i)
    for j in range(m + 1):
        d[0][j] = float(j)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            v = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + _sub(a[i - 1], b[j - 1]))
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                v = min(v, d[i - 2][j - 2] + 0.8)
            d[i][j] = v
    return d[n][m]


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return max(0.0, 1.0 - distance(a, b) / max(len(a), len(b)))


def ranked(word: str, candidates) -> list[tuple[str, float]]:
    out = {}
    for c in candidates:
        if c:
            s = similarity(word, c)
            if s > out.get(c, -1):
                out[c] = s
    return sorted(out.items(), key=lambda x: (-x[1], x[0]))


def thresholds() -> tuple[float, float]:
    try:
        from .config import load
        f = load("general").get("fuzzy", {})
        return float(f.get("accept", 0.8)), float(f.get("ask", 0.6))
    except Exception:  # noqa: BLE001
        return 0.8, 0.6


def resolve(word: str, candidates, accept: float | None = None, ask: float | None = None) -> tuple[str, str | None, float]:
    cands = list(candidates)
    low = word.lower()
    for c in cands:
        if c.lower() == low:
            return "exact", c, 1.0
    acc, ak = thresholds()
    acc = acc if accept is None else accept
    ak = ak if ask is None else ask
    r = ranked(word, cands)
    if not r:
        return "none", None, 0.0
    (c, s) = r[0]
    if len(r) > 1 and r[1][1] == s and r[1][0].lower() != c.lower():
        return ("unsure" if s >= ak else "none"), c, s          # two equally near: not taken by itself
    if s >= acc:
        return "near", c, s
    return ("unsure" if s >= ak else "none"), c, s
