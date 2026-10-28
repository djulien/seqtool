"""Word and sound times from timed phrases (0.19.7, the user's design).

Whisper's word times can't be trusted through a whole song (it stretches words over the
music, splits a phrase round a 15 s gap ...). A lyrics file with line times (LRC,
Audacity labels) gives the phrase starts reliably, so:

1. each phrase starts where the file says;
2. it ends where the singing stops before the next phrase - from the vocal stem
   (the song's analysis), else after a natural length for its sounds;
3. its words are looked up as sounds (ARPAbet, the same dictionaries as
   'lyrics phonemes'), and the phrase's sung time is shared out by sound, weighted
   like singing: a consonant takes about its spoken length (stops ~70 ms, fricatives
   ~100 ms ...), the vowels share the rest - a stressed vowel twice an unstressed
   one, a diphthong a little more - so a held note stretches the vowel, not the 'b';
4. where the stem shows a breath inside the phrase, no sound is placed in it.

Each word gets its start and end, and `sounds`: [[ARPAbet, start, end], ...], which
'lyrics phonemes' and the export use as they are.
"""
from __future__ import annotations

# spoken lengths of consonants (s), roughly as in speech corpora
CONS = {**{c: 0.07 for c in ("P", "B", "T", "D", "K", "G")},
        **{c: 0.10 for c in ("F", "V", "TH", "DH", "S", "Z", "SH", "ZH")},
        **{c: 0.08 for c in ("M", "N", "NG", "L", "R", "W", "Y")},
        "CH": 0.11, "JH": 0.10, "HH": 0.06}
DIPHTHONGS = {"AW", "AY", "EY", "OW", "OY"}
VOWEL_S = 0.16                                     # a stressed vowel's natural length (for phrases with no stem)


def _base(snd: str) -> str:
    return snd.rstrip("012")


def is_vowel(snd: str) -> bool:
    from .phonemes import VOWELS
    return _base(snd) in VOWELS


def weight(snd: str) -> float:
    """A vowel's share of the vowel time: stressed 1, unstressed 0.5, diphthongs x1.2."""
    w = 0.5 if snd.endswith("0") else 1.0
    return w * (1.2 if _base(snd) in DIPHTHONGS else 1.0)


def natural(sounds: list[list[str]]) -> float:
    """How long the words take, said plainly (when nothing else tells)."""
    return sum(CONS.get(_base(s), 0.08) if not is_vowel(s) else VOWEL_S * weight(s) for ws in sounds for s in ws)


def sung_mask(audio) -> tuple[float, list[bool]] | None:
    """(frame interval, singing per frame) from the vocal stem, breaths kept (gaps over 0.3 s)."""
    try:
        from ..common import current
        from ..common.canonical import read_json
        from .vocals import analyse, display_prefs
        cur = current.song(audio)
        if not cur or not cur.get("music"):
            return None
        a = analyse(read_json(cur["music"]), {**display_prefs(), "vocal_gap": 0.3})
        if a is None:
            return None
        return a["fi"], [c in ("v", "m") for c in a["classes"]]
    except Exception:  # noqa: BLE001
        return None


def _runs(mask: tuple[float, list[bool]] | None, a: float, b: float) -> list[tuple[float, float]]:
    """The sung stretches between a and b."""
    if not mask or b <= a:
        return []
    fi, m = mask
    out: list[list[float]] = []
    for i in range(max(0, int(a / fi)), min(len(m), int(b / fi) + 1)):
        if not m[i]:
            continue
        t0, t1 = max(a, i * fi), min(b, (i + 1) * fi)
        if t1 <= t0:
            continue
        if out and t0 - out[-1][1] < 1e-6:
            out[-1][1] = t1
        else:
            out.append([t0, t1])
    return [(x, y) for x, y in out]


def time_phrase(start: float, limit: float, sounds: list[list[str]], mask=None) -> dict:
    """One phrase: start (from the file), limit (the next phrase's start), each word's
    sounds -> {"end", "words": [(start, end, [[snd, s, e], ...])], "how"}."""
    nat = max(0.2, natural(sounds))
    runs = _runs(mask, start, min(limit, start + max(3 * nat, nat + 3.0)))   # not into a long instrumental
    how = "stem"
    if runs:                                       # the phrase ends at the first long pause once it has been sung
        keep, got = [runs[0]], runs[0][1] - runs[0][0]
        for r in runs[1:]:
            if r[0] - keep[-1][1] > 1.5 and got >= 0.5 * nat:
                break
            keep.append(r)
            got += r[1] - r[0]
        runs = keep
        end = runs[-1][1]
        if runs[0][0] > start:                     # the file's start wins: the first sung stretch starts there
            runs[0] = (start, runs[0][1])
        sung = sum(y - x for x, y in runs)
        if sung < 0.3 * min(limit - start, nat):   # hardly any singing found: the stem missed it
            runs, how = [], "plain"
    if not runs:
        end = min(limit, start + nat * 1.3) if limit > start else start + nat * 1.3
        runs = [(start, end)]
        how = "plain" if mask else "no stem"
    T = sum(y - x for x, y in runs)
    cons = [CONS.get(_base(s), 0.08) for ws in sounds for s in ws if not is_vowel(s)]
    vw = sum(weight(s) for ws in sounds for s in ws if is_vowel(s))
    C = sum(cons)
    k = 1.0 if vw and C <= 0.5 * T else (0.5 * T / C if C and vw else T / C if C else 1.0)
    V = T - C * k
    dur = [(CONS.get(_base(s), 0.08) * k if not is_vowel(s) else V * weight(s) / vw) for ws in sounds for s in ws]

    def at(u: float) -> float:                     # sung time u -> song time, skipping the breaths
        for x, y in runs:
            if u <= y - x + 1e-9:
                return x + u
            u -= y - x
        return runs[-1][1]
    out, u, i = [], 0.0, 0
    for ws in sounds:
        snd = []
        w0 = u
        for s in ws:
            snd.append([s, round(at(u), 3), round(at(u + dur[i]), 3)])
            u += dur[i]
            i += 1
        a_, b_ = at(w0), at(u)
        if not ws:                                 # nothing to say (a symbol): a moment at that point
            b_ = a_
        out.append((round(a_, 3), round(b_, 3), snd))
    return {"end": round(end, 3), "words": out, "how": how}


def time_lines(lines: list[dict], dictionary, mask=None, song_end: float | None = None) -> tuple[list[dict], dict]:
    """Timed lines (start from the file) -> the same lines with words and sounds timed.
    Returns (lines, {"stem": n, "plain": n, "no stem": n} - how each phrase's end was found)."""
    from .transcribe import tokens
    lines = sorted((ln for ln in lines if ln.get("text") and ln.get("start") is not None), key=lambda x: x["start"])
    out, how = [], {}
    for i, ln in enumerate(lines):
        t0 = float(ln["start"])
        nxt = float(lines[i + 1]["start"]) if i + 1 < len(lines) else (song_end or t0 + 8.0)
        words = [w for w in ln["text"].split() if tokens(w)]
        sounds = [dictionary.lookup_stressed(w)[0] for w in words]
        got = time_phrase(t0, max(nxt, t0 + 0.2), sounds, mask)
        how[got["how"]] = how.get(got["how"], 0) + 1
        ws = [{"start": a, "end": b, "text": w, "sounds": snd} for w, (a, b, snd) in zip(words, got["words"])]
        out.append({**{k: v for k, v in ln.items() if k != "words"}, "start": round(t0, 3),
                    "end": got["end"], "words": ws})
    return out, how
