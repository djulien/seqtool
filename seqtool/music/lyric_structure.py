"""Song structure from the words: where repeated passages of lyrics begin and end, where
the singing stops, and which sections share their words with others.

Works on the word sequence, so it doesn't matter how lines are split (an imported LRC
and a Whisper transcript split the same chorus differently). Words are compared
without punctuation and fillers (whoo, ha, oh ...); words of ad-lib lines under 3
words ('come on', 'squeek') are left out. A passage counts as repeated when at least
MIN_RUN words come back in the same order.

  evidence(music)          -> [(time, strength, why)] boundary evidence:
                              'lyrics repeat'  a repeated passage begins (a chorus comes back)
                              'lyrics end'     a repeated passage ends (what follows is new)
                              'lyrics stop'    the singing stops for GAP_BARS bars or more
  section_words(music, secs) -> per section: words, words per bar, share of its words
                              that come back in another section, and which sections
                              share them
"""
from __future__ import annotations

import re

MIN_RUN = 12                   # words in the same order that make a passage "repeated" (about 2 lines)
GAP_BARS = 4                   # the singing stops for at least this many bars
FILLERS = {"whoo", "woo", "ha", "oh", "ah", "ooh", "yeah", "hey", "la", "na", "uh", "huh", "mm", "hmm", "ya"}


def _words(music: dict) -> list[tuple[float, float, str]]:
    """(start, end, word) of the song's lyrics, fillers and ad-lib lines left out."""
    try:
        from .lyrics import for_music
        doc = for_music(music) or {}
    except Exception:  # noqa: BLE001
        return []
    out = []
    for ln in doc.get("lines", []):
        def norm(t):
            return re.sub(r"[^a-z0-9]", "", t.lower())
        toks = [norm(t) for t in ln["text"].split()]
        content = [t for t in toks if t and t not in FILLERS]
        if len(content) < 3:
            continue
        if ln.get("words"):
            ws = [(float(w["start"]), float(w["end"]), norm(w["text"])) for w in ln["words"]]
            out += [w for w in ws if w[2] and w[2] not in FILLERS]
            continue
        a, b = float(ln["start"]), float(ln.get("end", ln["start"] + 3.0))
        step = min((b - a) / max(1, len(toks)), 0.5)       # imported lines often 'last' until the next one
        first = True
        for k, t in enumerate(toks):
            if t and t not in FILLERS:
                out.append((a if first else a + k * step, a + (k + 1) * step, t))   # a line starts at its start
                first = False
    return out


def _seq(ws: list[tuple[float, float, str]], bar: float) -> list[str]:
    """The words, with a pause of GAP_BARS bars or more as a word of its own that never matches,
    so a repeated passage can't run across a pause into the next section."""
    W = []
    for k, (a, _, w) in enumerate(ws):
        W.append(w if k == 0 or a - ws[k - 1][1] < GAP_BARS * bar else f"\0{k}")
    return W


def _tandem(W: list[str], i: int, j: int, n: int) -> bool:
    """W[i:i+n] and W[j:j+n] are copies in one back-to-back run of the same passage
    (A A A): the same section going on, not a passage coming back."""
    blk = W[i:i + n]
    starts = {i}
    k = i
    while k + 2 * n <= len(W) and W[k + n:k + 2 * n] == blk:
        k += n
        starts.add(k)
    k = i
    while k - n >= 0 and W[k - n:k] == blk:
        k -= n
        starts.add(k)
    return j in starts


def _runs(W: list[str]) -> list[tuple[int, int, int]]:
    """(i, j, n): W[i:i+n] == W[j:j+n], n >= MIN_RUN, maximal on both sides, i != j."""
    idx: dict[tuple, list[int]] = {}
    for i in range(len(W) - 2):
        idx.setdefault(tuple(W[i:i + 3]), []).append(i)
    out = []
    for i in range(len(W) - 2):
        for j in idx.get(tuple(W[i:i + 3]), []):
            if j == i or (i > 0 and j > 0 and W[i - 1] == W[j - 1]):
                continue                                   # not where the repeat begins
            n = 0
            while i + n < len(W) and j + n < len(W) and W[i + n] == W[j + n]:
                n += 1
            if n >= MIN_RUN:
                out.append((i, j, n))
    return out


def evidence(music: dict) -> list[tuple[float, float, str]]:
    ws = _words(music)
    if len(ws) < 2 * MIN_RUN:
        return []
    bpm = music.get("analysis", {}).get("summary", {}).get("tempo", {}).get("bpm") or 120.0
    bar = 4 * 60.0 / bpm
    W = _seq(ws, bar)
    runs = _runs(W)
    out: dict[int, tuple[float, str]] = {}            # word index -> (strength, why)

    def put(k, st, why):
        if k not in out or st > out[k][0]:
            out[k] = (st, why)
    for i, j, n in runs:
        if abs(i - j) <= n or _tandem(W, i, j, n):
            continue                                   # A A: the passage again straight after itself
        if any(r[0] == i and r[1] < i and r[2] >= i - r[1] for r in runs):
            continue
        st = min(1.0, 0.3 + 0.02 * n)
        put(i, st, "lyrics repeat")
        if i + n < len(W):
            put(i + n, st, "lyrics end")
    ev = []
    for k, (st, why) in out.items():
        t = ws[k][0]
        if why == "lyrics end" and k > 0 and ws[k][0] - ws[k - 1][1] > 2 * bar:
            t = ws[k - 1][1]                           # a pause after it: the next section starts there
        ev.append((t, st, why))
    for k in range(1, len(ws)):                        # the singing stops
        if ws[k][0] - ws[k - 1][1] >= GAP_BARS * bar:
            ev.append((ws[k - 1][1], 0.5, "lyrics stop"))
    if ws and music.get("audio", {}).get("duration", 0) - ws[-1][1] >= GAP_BARS * bar:
        ev.append((ws[-1][1], 0.5, "lyrics stop"))
    return sorted(ev)


def section_words(music: dict, secs: list[dict]) -> list[dict] | None:
    """Per section {words, per_bar, shared, with}: how many lyric words, how many per bar,
    the share of them that come back (MIN_RUN words or more in the same order) in another
    section, and the indexes of those sections. None when the song has too few lyrics."""
    ws = _words(music)
    if len(ws) < 3 * MIN_RUN:
        return None
    bpm = music.get("analysis", {}).get("summary", {}).get("tempo", {}).get("bpm") or 120.0
    bar = 4 * 60.0 / bpm
    W = _seq(ws, bar)

    def sec_of(t):
        for k, s in enumerate(secs):
            if s["start"] <= t < s["end"]:
                return k
        return len(secs) - 1
    where = [sec_of(a) for a, _, _ in ws]
    shared = [set() for _ in ws]                       # other sections each word comes back in
    for i, j, n in _runs(W):
        for k in range(n):
            if where[i + k] != where[j + k]:
                shared[i + k].add(where[j + k])
    info = []
    for k, s in enumerate(secs):
        ids = [x for x in range(len(ws)) if where[x] == k]
        bars = max(1e-6, (s["end"] - s["start"]) / bar)
        with_ = {}
        for x in ids:
            for o in shared[x]:
                with_[o] = with_.get(o, 0) + 1
        info.append({"words": len(ids), "per_bar": len(ids) / bars,
                     "shared": (sum(1 for x in ids if shared[x]) / len(ids)) if ids else 0.0,
                     "with": sorted(o for o, c in with_.items() if c >= 0.4 * len(ids))})
    return info


def types(secs: list[dict], info: list[dict], bar: float) -> list[tuple[str, str] | None]:
    """A section type from the words, with the reason, or None to keep the type from the
    sound:
      * chorus: the sections whose words come back elsewhere - the group that comes back
        most (a passage repeated only back to back is one section going on, not a chorus);
      * pre_chorus: short (6 bars or less), right before a chorus, words of its own;
      * bridge: the one stretch with words of its own in the second half of the song;
      * verse: other sections with words of their own (8 bars or more);
      * breakdown: hardly any words (under 0.75 a bar), between the first and last section.
    Short passages with words of their own that don't lead into a chorus keep the type
    from the sound."""
    n = len(secs)
    full = [d["words"] >= MIN_RUN // 2 for d in info]       # a pickup line into the next section isn't 'words'
    groups: list[set] = []
    for k, d in enumerate(info):
        if full[k] and d["shared"] >= 0.5 and d["with"]:
            g = {k, *[o for o in d["with"] if full[o]]}
            for h in [h for h in groups if h & g]:
                g |= h
                groups.remove(h)
            groups.append(g)
    groups = [g for g in groups if max(g) - min(g) + 1 != len(g) or len(g) == 1]   # not only back to back
    chorus = max(groups, key=lambda g: (len(g), sum(info[k]["words"] for k in g)), default=set())
    out: list[tuple[str, str] | None] = [None] * n
    short = [(s["end"] - s["start"]) <= 6 * bar + 1e-6 for s in secs]
    for g in groups:
        for k in g:
            if g is chorus:
                out[k] = ("chorus", f"its words come back in {len(g) - 1} other section(s)")
            elif short[k] and k + 1 in chorus:
                out[k] = ("pre_chorus", "short, its words come back, and a chorus follows")
            else:
                out[k] = ("chorus", "its words come back")
    own = [k for k in range(n) if out[k] is None and full[k] and info[k]["per_bar"] >= 0.75]
    for k in own:
        if short[k] and k + 1 in chorus:
            out[k] = ("pre_chorus", "short, words of its own, and a chorus follows")
    long_own = [k for k in own if out[k] is None and not short[k]]
    stretches: list[list[int]] = []
    for k in long_own:
        if stretches and stretches[-1][-1] == k - 1:
            stretches[-1].append(k)
        else:
            stretches.append([k])
    late = [st for st in stretches if secs[st[0]]["start"] >= 0.5 * secs[-1]["end"]
            and sum(1 for c in chorus if c < st[0]) >= 2]
    for st in stretches:
        for k in st:
            out[k] = ("bridge", "the one passage with words of its own late in the song") \
                if len(late) == 1 and st is late[0] else ("verse", "words of its own")
    for k in range(1, n - 1):
        if out[k] is None and info[k]["per_bar"] < 0.75:
            out[k] = ("breakdown", "hardly any words")
    return out
