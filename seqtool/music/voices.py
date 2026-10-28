"""Voices in one lyrics track (0.24.0, the user's design).

A code in curly brackets in the lyrics says who sings from there on:

    {BOB} I saw three ships come sailing in
    {ALICE} on Christmas Day, on Christmas Day
    {ALL} I saw three ships come sailing in

The words after {BOB} are BOB's until the next code; {ALL} words are sung by every voice;
words before the first code count as {ALL}. Codes can be typed anywhere the words are
(an imported .lrc or labels file, 'lyrics word', 'lyrics align' text), or set with
'lyrics voice NAME @LINE[.WORD]'. A prop singing with a face can be given a voice
('face use PROP FACE --voice BOB'): it sings only BOB's and ALL's words, and in xLights
its Faces effect follows its own timing track, seqtool-lyrics-BOB.

Stored form (songs.json): a word that started a voice carries "voice_mark"; every word
carries the "voice" in force ("ALL" before the first code); the line text keeps the codes
(so aligning again keeps them) and 'for_music' hands out the text without them.
"""
from __future__ import annotations

import re

CODE = re.compile(r"\{\s*([^{}\s][^{}]*?)\s*\}")
ALL = "ALL"


def strip(text: str) -> str:
    return re.sub(r"\s{2,}", " ", CODE.sub("", text or "")).strip()


def _key(v: str | None) -> str:
    return (v or ALL).strip().upper()


def normalize(doc: dict | None) -> dict | None:
    """Codes in the words become voice marks; every word gets its voice. Changes doc in place."""
    if not doc or not doc.get("lines"):
        return doc
    pending, any_code = None, False
    for ln in doc["lines"]:
        words = ln.get("words") or []
        if words and CODE.search(ln.get("text", "")):     # codes typed in the line's text: onto its words
            raw = ln["text"]
            plain, codes, pos = "", [], 0                   # the text without codes, and where each code was in it
            for m in CODE.finditer(raw):
                plain += raw[pos:m.start()]
                codes.append((len(plain), m.group(1)))
                pos = m.end()
            plain += raw[pos:]
            low, pos, spans = plain.lower(), 0, []
            for w in words:
                t = CODE.sub("", w.get("text", "")).lower().strip()
                i = low.find(t or "\0", pos)
                spans.append((i, i + len(t)) if i >= 0 else None)
                if i >= 0:
                    pos = i + 1
            for at, name in reversed(codes):            # from the end: a split doesn't shift the ones before
                k = next((k for k, sp in enumerate(spans) if sp and sp[0] < at < sp[1]), None)
                if k is not None:
                    if CODE.search(words[k].get("text", "")):
                        continue                            # the word's own code: done below
                    a, w2 = split_at(words[k], at - spans[k][0], name)      # 0.24.42: inside a word: it stays there
                    words[k:k + 1] = [a, w2]
                    spans[k:k + 1] = [(spans[k][0], at), (at, spans[k][1])]
                    continue
                k = next((k for k, sp in enumerate(spans) if sp and sp[1] == at), None)
                if k is not None and at > 0 and not plain[at - 1].isspace() and \
                        (at >= len(plain) or plain[at].isspace() or plain[at] in ",.;:!?"):   # 0.24.43: on its end: after it
                    if not words[k].get("voice_after") and not CODE.search(words[k].get("text", "")):
                        words[k]["voice_after"] = name
                    continue
                k = next((k for k, sp in enumerate(spans) if sp and sp[0] == at), None)
                if k is not None and CODE.search(words[k].get("text", "")):
                    continue                                # the word's own code: done below
                k = next((k for k, sp in enumerate(spans) if sp and sp[0] >= at), None)
                if k is not None and not words[k].get("voice_mark") and not CODE.search(words[k].get("text", "")):
                    words[k]["voice_mark"] = name
        if words:                                          # a code inside a word's own text: split it there
            out = []
            for w in words:
                t = w.get("text", "")
                m = CODE.search(t)
                if m and strip(t[:m.start()]) and strip(t[m.end():]):
                    a, b = split_at({**w, "text": t[:m.start()] + t[m.end():]}, len(t[:m.start()]), m.group(1))
                    rest = t[m.end():]
                    out += [a, {**b, "text": rest} if CODE.search(rest) else b]
                else:
                    out.append(w)
            words[:] = out
        if words:
            kept = []
            for w in words:
                t = w.get("text", "")
                codes = CODE.findall(t)
                if codes and strip(t):                          # 0.24.45: each code where it is - at the start
                    lead = re.match(r"\s*((?:\{[^{}]*\}\s*)+)", t)         # (from this word), at the end (from the
                    trail = re.search(r"((?:\{[^{}]*\}\s*)+)$", t)          # next one), or both
                    if trail and lead and trail.start() < lead.end():
                        trail = None
                    if lead:
                        w["voice_mark"] = CODE.findall(lead.group(1))[-1]
                    if trail:
                        w["voice_after"] = CODE.findall(trail.group(1))[-1]
                    if not lead and not trail:                  # (inside: split above; left over: from this word)
                        w["voice_mark"] = codes[-1]
                    w["text"] = strip(t)
                    codes = [1] if lead or not trail else []
                elif codes:
                    w["voice_mark"] = codes[-1]
                    w["text"] = strip(w["text"])
                if not w.get("text"):                       # a code on its own: it marks the next word
                    pending = w.get("voice_mark", pending)
                    continue
                if pending and not codes:
                    w["voice_mark"], pending = pending, None
                if w.get("voice_mark") in ("", "-"):
                    w.pop("voice_mark")
                if w.get("voice_after") in ("", "-"):
                    w.pop("voice_after")
                if w.get("voice_mark") or w.get("voice_after"):
                    any_code = True
                kept.append(w)
            ln["words"] = kept
            ln["text"] = _marked_text(ln.get("text", ""), kept)
        else:
            if CODE.search(ln.get("text", "")):
                any_code = True
    # second pass: the voice in force for every word (and line)
    cur = None
    for ln in doc["lines"]:
        words = ln.get("words") or []
        vs = []
        if words:
            for w in words:
                if w.get("voice_mark"):
                    cur = w["voice_mark"]
                if any_code:
                    w["voice"] = cur or ALL
                else:
                    w.pop("voice", None)
                vs.append(w.get("voice"))
                if w.get("voice_after"):                    # the voice changes after this word
                    cur = w["voice_after"]
        else:
            codes = CODE.findall(ln.get("text", ""))
            if codes:
                cur = codes[0]
            vs = [cur or ALL] + codes[1:] if any_code else []
        if any_code:
            ln["voices"] = list(dict.fromkeys(v for v in vs if v))
        else:
            ln.pop("voices", None)
    return doc


def line_text(words: list[dict]) -> str:
    """A line's text made from its words, with their voice codes where they belong."""
    return "".join(("" if x.get("joined") or k == 0 else " ")
                   + ("{" + x["voice_mark"] + "}" + ("" if x.get("joined") else " ") if x.get("voice_mark") else "")
                   + x.get("text", "") + ("{" + x["voice_after"] + "}" if x.get("voice_after") else "")
                   for k, x in enumerate(words))


def join_text(words: list[dict]) -> str:
    """The words as a line's text: a space between them, none before a 'joined' part (0.24.42)."""
    return "".join(("" if k == 0 or w.get("joined") else " ") + w.get("text", "") for k, w in enumerate(words))


def split_at(w: dict, offset: int, name: str) -> tuple[dict, dict]:
    """A word in two where a {VOICE} code is inside it (0.24.42 - the code stays where it was
    typed, it isn't moved to the word's start): the time is shared by letters; the second part
    starts the voice and is 'joined' (no space before it when the line is written out)."""
    text = w.get("text", "")
    n = max(1, len(text))
    a0, b0 = float(w.get("start", 0.0)), float(w.get("end", 0.0))
    t = round(a0 + (b0 - a0) * offset / n, 3)
    first = {**w, "text": text[:offset], "end": t}
    second = {**w, "text": text[offset:], "start": t, "voice_mark": name, "joined": True}
    first.pop("joined", None) if not w.get("joined") else None
    return first, second


def _marked_text(text: str, words: list[dict]) -> str:
    """The line's own text (it may hold more than the timed words), its codes where the words'
    marks are: each mark put before that word's first match after the one before."""
    plain = strip(text)
    if not any(w.get("voice_mark") or w.get("voice_after") for w in words):
        return plain
    out, pos = [], 0
    low = plain.lower()
    for w in words:
        i = low.find(w["text"].lower(), pos)
        if i < 0:                                       # the text doesn't hold the words: rebuilt from them
            return line_text(words)
        if w.get("voice_mark"):
            out.append(plain[pos:i] + "{" + w["voice_mark"] + "}" + ("" if w.get("joined") else " "))
            pos = i
        i_end = i + len(w["text"])
        out.append(plain[pos:i_end] + ("{" + w["voice_after"] + "}" if w.get("voice_after") else ""))
        pos = i_end
    out.append(plain[pos:])
    return re.sub(r"[ \t]{2,}", " ", "".join(out)).strip()


def for_use(doc: dict | None) -> dict | None:
    """A copy with the codes taken out of the text (what everything but the editor uses)."""
    if not doc:
        return doc
    import copy
    out = copy.deepcopy(doc)
    for ln in out.get("lines", []):
        ln["text"] = strip(ln.get("text", ""))
    return out


def names(doc: dict | None) -> list[str]:
    """The voices named in the lyrics (not ALL), in order of appearance."""
    seen: dict[str, str] = {}
    for ln in (doc or {}).get("lines", []):
        for v in ln.get("voices") or []:
            if _key(v) != ALL:
                seen.setdefault(_key(v), v)
    return list(seen.values())


def sings(item_voice: str | None, voice: str | None) -> bool:
    """Does a prop with `voice` (None = every voice) sing a word of `item_voice`?"""
    return voice is None or item_voice is None or _key(item_voice) in (ALL, _key(voice))


def lines_for(doc: dict | None, voice: str | None) -> list[dict]:
    """The lines (with only the words) this voice sings."""
    out = []
    for ln in (doc or {}).get("lines", []):
        words = ln.get("words") or []
        if words:
            mine = [w for w in words if sings(w.get("voice"), voice)]
            if mine:
                out.append({**ln, "start": mine[0]["start"], "end": max(w["end"] for w in mine),
                            "text": join_text(mine).strip(), "words": mine})
        elif any(sings(v, voice) for v in (ln.get("voices") or [None])):
            out.append(ln)
    return out


def sung_spans(doc: dict | None, voice: str | None, lead: float = 0.15, tail: float = 0.25,
               join: float = 1.0, end: float | None = None) -> list[tuple[float, float]]:
    """When this voice sings: its lines from `lead` s before to `tail` s after, gaps under
    `join` s closed - where a singing face shows."""
    spans = sorted((max(0.0, ln["start"] - lead), ln["end"] + tail) for ln in lines_for(doc, voice))
    out: list[list[float]] = []
    for a, b in spans:
        if end is not None:
            b = min(b, end)
        if out and a - out[-1][1] < join:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out if b > a]
