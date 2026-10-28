"""Plain-language direction -> seqtool commands, offline (0.24.33).

No language model: the text is matched against the intents of preferences/intents.json (phrases
that mean each one, the commands that do it, what it means, the commands that check it). The
slots of a command ({where}, {prop}, {words}, ...) are filled from the text and from the song
and layout: section names ("the second chorus") become @#N, prop and group names are matched
to the plan's targets, quoted words become --words. 'direct' (direct_cmd.py) shows what it
understood, asks, runs it as one batch and runs the checks.

    interpret(text, ctx, intents) -> [clause results]

A clause result: {"text", "intent", "score", "commands", "means", "check", "notes", "missing",
"others": [{"intent", "score", "commands"}]} - intent None when nothing matched.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

TOKEN = re.compile(r"@#\d+|#\d+|@vocals(?:[+-][\d.]+)?|@[a-z][a-z-]*(?:#\d+)?|@?\d+:\d+(?:\.\d+)?|@?\d+(?:\.\d+)?s\b|@\d+(?:\.\d+)?|"
                   r"\d+(?:st|nd|rd|th)\b|\d+|[a-z]+(?:-[a-z]+)*")
QUOTED = re.compile(r'"([^"]+)"|(?:(?<=[\s(,])|^)\'([^\']+)\'(?=[\s,.;!?)]|$)')
ORDINALS = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "4th": 4, "fifth": 5,
            "5th": 5, "last": -1, "final": -1}
GENERIC = {"all", "group", "grp", "the", "props", "models", "model", "prop", "left", "right", "new", "old"}
STOP = {"in", "on", "the", "at", "during", "of", "a", "an", "and", "or", "with", "when", "to", "for", "is", "are", "be",
        "it", "its", "that", "this", "make", "please", "more", "less", "too", "very", "so", "but", "only", "every", "each"}
GENERIC_SECTIONS = {"intro", "verse", "chorus", "bridge", "outro", "instrumental", "build", "drop", "prechorus", "pre-chorus",
                    "breakdown", "interlude"}
SLOT = re.compile(r"\{([a-z_]+)(\?|\|[^}]*)?\}")
SEPARATORS = re.compile(r"\s*(?:;|\.\s+|\bthen\b|\balso\b|,\s*and\b|\band\b|,)\s*")


@dataclass
class Ctx:
    """What the text is resolved against: the song's sections, the plan's targets."""
    sections: list = field(default_factory=list)       # profile sections: index, start, end, type, id, repeat_of
    targets: list = field(default_factory=list)        # names 'pin' / 'react' accept
    members: dict = field(default_factory=dict)        # group -> set of its members (props and groups)
    effects: list = field(default_factory=list)        # effect names (color_wash ...)
    vocals: float | None = None                        # where the singing starts (s)
    yard: str | None = None                            # the group holding the most props
    vocals_fn: object = None                           # finds 'vocals' when it is needed (it can be slow)
    lyrics: list = field(default_factory=list)         # the song's sung words (lowercase, as sung)

    def vocal_start(self) -> float | None:
        if self.vocals is None and self.vocals_fn is not None:
            try:
                self.vocals = float(self.vocals_fn())
            except (SystemExit, Exception):  # noqa: BLE001
                pass
            self.vocals_fn = None
        return self.vocals


def tokens(text: str) -> list[str]:
    return TOKEN.findall(text.lower().replace("'", "").replace("’", ""))


def _tok_match(p: str, t: str) -> bool:
    if not p or not t:
        return False
    if p == t or t in (p + "s", p + "es") or (p.endswith("y") and t == p[:-1] + "ies"):
        return True
    if p[0] in "@#0123456789" or t[0] in "@#0123456789":
        return False
    if len(p) >= 4 and t.startswith(p) and len(t) - len(p) <= 4:
        return True
    return len(p) >= 5 and len(t) >= 5 and difflib.SequenceMatcher(None, p, t).ratio() >= 0.86


def phrase_at(ph: list[str], toks: list[str]) -> tuple[int, int] | None:
    """Where a phrase's tokens appear in order (at most 2 other words between): (first, last)."""
    if not ph:
        return None
    for i, t in enumerate(toks):
        if not _tok_match(ph[0], t):
            continue
        j, k = i, 1
        while k < len(ph):
            nxt = next((x for x in range(j + 1, min(len(toks), j + 4)) if _tok_match(ph[k], toks[x])), None)
            if nxt is None:
                break
            j, k = nxt, k + 1
        if k == len(ph):
            return i, j
    return None


def phrase_score(ph: list[str]) -> float:
    return sum(len(t) for t in ph) + 2 * (len(ph) - 1)


def _name_tokens(name: str) -> list[str]:
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    out = [t for t in re.split(r"[^A-Za-z0-9]+", s.lower()) if t]
    out = [re.sub(r"\d+$", "", t) for t in out]
    return [t for t in out if len(t) >= 3 and not re.search(r"\d", t) and t not in GENERIC]


def find_props(toks: list[str], ctx: Ctx, yard_words: list[str]) -> list[str]:
    if any(phrase_at(tokens(w), toks) for w in yard_words) and ctx.yard:
        return [ctx.yard]
    hits = {}
    for t in ctx.targets:
        key = _name_tokens(t)
        if not key:
            continue
        used = set()
        for k in key:
            x = next((i for i, w in enumerate(toks) if i not in used and w not in STOP and _tok_match(k, w)), None)
            if x is not None:
                used.add(x)
            elif not used:
                break                                  # its first word must be there ('angel' for Angel-3D)
        if used:
            hits[t] = (frozenset(used), len(used) == len(key))
    if not hits:
        return []
    keep = [t for t in hits if not any(hits[t][0] < hits[o][0] for o in hits if o != t)]   # the most specific names
    best = max((len(hits[t][0]), hits[t][1]) for t in keep)
    keep = [t for t in keep if (len(hits[t][0]), hits[t][1]) == best]                   # whole names first
    keep = [t for t in keep if not any(t in ctx.members.get(o, ()) and hits[o][0] == hits[t][0]
                                       for o in keep if o != t)]                          # a group over its members
    exact = [t for t in keep if t.lower() in toks]
    keep = [t for t in keep if t in exact or not any(hits[e][0] == hits[t][0] for e in exact)]
    return sorted(keep)


def find_words(text: str) -> list[str]:
    words = [a or b for a, b in QUOTED.findall(text)]
    if not words:
        m = re.search(r"\bthe words? ([a-z]+(?:(?:,\s*|\s+and\s+|\s+or\s+)[a-z]+)*)", text.lower())
        if m:
            words = [w for w in re.split(r",\s*|\s+and\s+|\s+or\s+", m.group(1)) if w not in STOP]
    return [w.strip() for w in words if w.strip()]


def _strip_quoted(text: str) -> str:
    return QUOTED.sub(" ", text)


def find_sections(toks: list[str], ctx: Ctx, aliases: dict) -> tuple[list[str], list[str]]:
    """(where refs, notes): '@#3' / '@#3 --only' for each section (repeat group) named."""
    refs, notes = [], []
    valid = [str(x["index"]) for x in ctx.sections]
    for i, t in enumerate(toks):
        m = re.fullmatch(r"@?#(\d+)", t)
        n = m.group(1) if m else (toks[i + 1] if t == "section" and i + 1 < len(toks) and toks[i + 1].isdigit() else None)
        if n is None:
            continue
        if valid and n not in valid:                   # 0.24.34: a mistyped number is not used
            from ..common import fuzzy
            r = fuzzy.ranked(n, valid)
            top = [c for c, x in r if x == r[0][1] and x >= 0.4] if r else []
            notes.append(f"this song has no section #{n} (#1-#{valid[-1]}"
                         + (f"; the most likely: {' or '.join('#' + c for c in top[:2])}" if top else "") + ")")
            continue
        refs.append(f"@#{n}" + (" --only" if "only" in toks else ""))
    if refs or not ctx.sections:
        return refs, notes
    types = {str(s.get("type", "")).lower() for s in ctx.sections}
    for t in toks:
        b = aliases.get(t, t)
        b = b[:-1] if b.endswith("s") and b[:-1] in GENERIC_SECTIONS else b
        if b in GENERIC_SECTIONS and b not in types:
            notes.append(f"this song has no {b} ('sections' lists its parts: {', '.join(sorted(t for t in types if t))})")
    for i, t in enumerate(toks):
        base = aliases.get(t, t)
        typ = next((x for x in types if x and (base == x or base in (x + "s", x + "es"))), None)
        if not typ:
            continue
        secs = [s for s in ctx.sections if str(s.get("type", "")).lower() == typ]
        prev = [toks[k] for k in range(max(0, i - 2), i)]
        ordn = next((ORDINALS[p] for p in prev if p in ORDINALS), None)
        if ordn is not None:
            if abs(ordn) > len(secs):
                notes.append(f"there are {len(secs)} {typ} sections")
                continue
            s = secs[ordn - 1 if ordn > 0 else -1]
            refs.append(f"@#{s['index']} --only")
        else:
            roots = {}
            for s in secs:
                roots.setdefault(_root(ctx, s), s)
            refs += [f"@#{s['index']}" for s in roots.values()]
    return list(dict.fromkeys(refs)), notes


def _root(ctx: Ctx, s: dict) -> str:
    ids = {x["id"]: x for x in ctx.sections}
    r = s
    while r.get("repeat_of") in ids:
        r = ids[r["repeat_of"]]
    return r["id"]


def find_time(toks: list[str], text: str) -> str | None:
    for t in toks:
        if re.fullmatch(r"@?\d+:\d+(?:\.\d+)?|@\d+(?:\.\d+)?|@vocals(?:[+-][\d.]+)?", t):
            return "@" + t.lstrip("@")
        if re.fullmatch(r"@[a-z][a-z-]*(?:#\d+)?", t):              # 0.24.34: '@star' - where 'star' is sung
            return t
        m = re.fullmatch(r"@?(\d+(?:\.\d+)?)s", t)
        if m:
            return "@" + m.group(1)
    if re.search(r"\b(?:when|where|as) the (?:vocals|singing|voice) (?:start|begin|come in)", text.lower()):
        return "@vocals"
    return None


def find_amount(text: str) -> tuple[float, str] | None:
    """'by 2 bars' / 'by 4 beats' / 'by 3 s' (seconds when no unit) -> (2, 'bar')."""
    m = re.search(r"\bby (?:about |around )?(\d+(?:\.\d+)?|a|an|one|two|three|four|half a)\s*"
                  r"(bars?|measures?|beats?|s|secs?|seconds?)?\b", text.lower())
    if not m:                                          # '2 bars longer': a unit is needed then
        m = re.search(r"\b(\d+(?:\.\d+)?|a|an|one|two|three|four|half a)\s*(bars?|measures?|beats?|s|secs?|seconds?)\b"
                      r"(?=\s+(?:longer|shorter|more|less|earlier|later))", text.lower())
    if not m:
        return None
    n = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "half a": 0.5}.get(m.group(1))
    n = float(m.group(1)) if n is None else float(n)
    unit = (m.group(2) or "s").rstrip("s") or "s"
    unit = {"measure": "bar", "sec": "s", "second": "s", "": "s"}.get(unit, unit)
    return n, unit


def _beat_len(sec: dict) -> float:
    br = sec.get("beat_range") or []
    n = (br[1] - br[0]) if len(br) == 2 else 0
    return (sec["end"] - sec["start"]) / n if n > 0 else 0.5


def resize(s: dict, ctx: Ctx, sign: int) -> list[str] | None:
    """'enlarge the chorus by 2 bars': each named section's end moves later (the next section
    starts later; the last section's start moves earlier instead) - 'sections move' commands."""
    if not s.get("amount") or not s.get("where"):
        return None
    n, unit = s["amount"]
    out = []
    by = {x["index"]: x for x in ctx.sections}
    for ref in s["where"]:
        m = re.match(r"@#(\d+)", ref)
        if not m:
            continue
        k = int(m.group(1))
        sec = by.get(k)
        if sec is None:
            continue
        secs = [sec] if "--only" in ref else [x for x in ctx.sections if _root(ctx, x) == _root(ctx, sec)]
        for x in secs:
            d = n * {"bar": 4 * _beat_len(x), "beat": _beat_len(x)}.get(unit, 1.0) * sign
            nxt = by.get(x["index"] + 1)
            if nxt is not None:
                out.append(f"sections move {nxt['index']} @{nxt['start'] + d:.2f}")
            elif x["index"] > 1:
                out.append(f"sections move {x['index']} @{x['start'] - d:.2f}")
    return out or None


def find_effect(toks: list[str], ctx: Ctx, words: dict | None = None) -> str | None:
    """An effect named in the text: by its own name first ('twinkle'), else by a word for it
    ('glow' = color_wash)."""
    best = None
    for e in ctx.effects:
        if e in ("dark", "transparent", "face"):
            continue
        if phrase_at(e.split("_"), toks) and (best is None or len(e) > len(best)):
            best = e
    if best:
        return best
    for w, e in (words or {}).items():
        if e in ctx.effects and phrase_at(tokens(w), toks) and (best is None or len(w) > len(best[0])):
            best = (w, e)
    return best[1] if best else None


def vocal_sections(ctx: Ctx) -> tuple[str | None, list[str]] | None:
    """(the split, the sections before the singing) - None when the singing start isn't known."""
    v = ctx.vocal_start()
    if v is None or not ctx.sections:
        return None
    if any(abs(s["start"] - v) <= 1.0 for s in ctx.sections[1:]) or v <= 1.0:
        n = sum(1 for s in ctx.sections if s["start"] < v - 0.5)
        return None, [f"@#{k} --only" for k in range(1, n + 1)]
    j = next((s["index"] for s in ctx.sections if s["start"] < v < s["end"]), None)
    if j is None:
        return None, []
    # 0.24.37: no split - the section the singing starts in is pinned until it ('until=@vocals')
    return None, [f"@#{k} --only" for k in range(1, j)] + [f"@#{j} --only until=@vocals"]


def _without_props(toks: list[str], ctx: Ctx, props: list[str]) -> list[str]:
    keys = [k for p in props for k in _name_tokens(p)]
    return [t if not any(_tok_match(k, t) for k in keys) else "" for t in toks]


def _degree(toks: list[str], text: str, deg: dict) -> str:
    low = " " + " ".join(toks) + " "
    if any(f" {w} " in low for w in deg.get("mild", [])):
        return "mild"
    if any(f" {w} " in low for w in deg.get("strong", [])):
        return "strong"
    return "normal"


def _q(name: str) -> str:
    return f'"{name}"' if re.search(r"\s", name) else name


def _slots(text: str, ctx: Ctx, prefs: dict) -> dict:
    plain = _strip_quoted(text)
    toks = tokens(plain)
    deg = prefs.get("degree", {})
    d = _degree(toks, text, deg)
    aliases = prefs.get("section_words", {})
    where, notes = find_sections(toks, ctx, aliases)
    time = find_time(toks, plain)
    types = {str(x.get("type", "")).lower() for x in ctx.sections} | set(aliases)
    ptoks = [t if not (t in ORDINALS or t[0] in "@#0123456789" or aliases.get(t, t) in types
                       or aliases.get(t, t).rstrip("s") in types) else "" for t in toks]   # not prop names
    sung = {w.lower() for w in find_words(text)}
    ptoks = [t if t not in sung else "" for t in ptoks]
    props = find_props(ptoks, ctx, prefs.get("yard_words", []))
    vs = vocal_sections(ctx) if any(t.startswith(("vocal", "sing", "voice")) for t in toks) else None
    s = {"toks": toks, "notes": notes,
         "ptoks": ptoks,
         "prop": [_q(p) for p in props],
         "words": ",".join(find_words(text)) or None,
         "time": time,
         "where": where or ([time] if time and time != "@vocals" else []),
         "effect": find_effect(_without_props(ptoks, ctx, props), ctx, prefs.get("effect_words")),
         "hi": f"{deg.get('hi', {}).get(d, 0.8):g}", "lo": f"{deg.get('lo', {}).get(d, 0.2):g}",
         "split_vocals": vs[0] if vs else None, "before_vocals": vs[1] if vs else None,
         "yard": _q(ctx.yard) if ctx.yard else None}
    s["at"] = [w.replace(" --only", "") for w in s["where"]]
    s["where_failed"] = not s["where"] and any("this song has no" in n or n.startswith("there are ") for n in notes)
    s["amount"] = find_amount(plain)
    s["grow"], s["shrink"] = resize(s, ctx, +1), resize(s, ctx, -1)
    return s


def _fill(line: str, s: dict) -> tuple[list[str] | None, list[str]]:
    """The commands of one template line (one per prop / section when several), or None with the
    slots it lacks."""
    optional_line = line.startswith("?")
    line = line.lstrip("?")
    missing, lists = [], {}
    for m in SLOT.finditer(line):
        name, mod = m.group(1), m.group(2) or ""
        v = s.get(name)
        if v in (None, [], ""):
            if name in ("where", "at") and s.get("where_failed"):
                missing.append("where")
                continue
            if mod == "?" or (name in ("where", "at") and not mod.startswith("|")):
                v = ""
            elif mod.startswith("|"):
                dflt = mod[1:]
                v = s.get(dflt) if dflt in s else dflt
                if v in (None, "", []):
                    missing.append(name)
                    continue
            else:
                missing.append(name)
                continue
        lists[m.group(0)] = v if isinstance(v, list) else [v]
    if missing:
        return (None if not optional_line else []), missing
    out = [line]
    for k, vals in lists.items():
        out = [o.replace(k, str(v), 1) for o in out for v in vals]
    return [re.sub(r"\s+", " ", o).strip() for o in out if o.strip()], []


def _score(intent: dict, s: dict) -> float:
    """The intent's best phrase in the text (0: not it). '{slot}' as a phrase: that slot is in the
    text ('{effect}' an effect name, '{amount}' 'by 2 bars' ...)."""
    toks = s["toks"]
    for n in intent.get("not", []):
        m = re.fullmatch(r"\{([a-z_]+)\}", n)
        if (m and s.get(m.group(1))) or (not m and phrase_at(tokens(n), toks)):
            return 0.0
    for u in intent.get("unless", []):
        if s.get(u):
            return 0.0
    for nd in intent.get("need", []):
        if not s.get(nd):
            return 0.0
    best = 0.0
    for ph in intent.get("say", []):
        m = re.fullmatch(r"\{([a-z_]+)\}", ph)
        if m:
            v = s.get(m.group(1))
            if v:
                best = max(best, 6.0 + (len(v) * 0.1 if isinstance(v, str) else 0))
            continue
        if phrase_at(tokens(ph), toks):
            best = max(best, phrase_score(tokens(ph)))
    return best


def match_clause(text: str, ctx: Ctx, prefs: dict, carry: dict | None = None) -> dict:
    s = _slots(text, ctx, prefs)
    notes = list(s["notes"])
    if carry and not s["prop"] and carry.get("prop"):
        s["prop"], s["carried"] = carry["prop"], True
    cands = []
    for iid, it in (prefs.get("intents") or {}).items():
        sc = _score(it, s)
        if sc <= 0:
            continue
        cmds, missing = [], []
        for line in it.get("do", []):
            c, miss = _fill(line, s)
            if c is None:
                missing += miss
            else:
                cmds += c
        raw = sc
        if missing:
            sc *= 0.5
        cands.append({"intent": iid, "score": round(sc, 2), "raw": raw, "commands": cmds, "missing": sorted(set(missing)),
                      "means": it.get("means", ""), "check": list(it.get("check", [])),
                      "uses_where": any(k in x for x in it.get("do", []) for k in ("{where", "{at", "{before_vocals", "{grow", "{shrink"))})
    cands.sort(key=lambda c: (-c["score"], bool(c["missing"])))
    res = {"text": text.strip(), "intent": None, "score": 0.0, "commands": [], "means": "", "check": [], "notes": notes,
           "missing": [], "others": [], "prop": s["prop"]}
    if not cands or cands[0]["raw"] < float(prefs.get("minimum", 4)):
        res["ranked"] = [[c["intent"], c["score"], c["missing"]] for c in cands]
        return res
    top = cands[0]
    res.update({k: top[k] for k in ("intent", "score", "commands", "means", "check", "missing")})
    res["ranked"] = [[c["intent"], c["score"], c["missing"]] for c in cands]
    res["others"] = [{"intent": c["intent"], "score": c["score"], "commands": c["commands"]}
                     for c in cands[1:4] if not c["missing"] and c["score"] >= float(prefs.get("minimum", 4))]
    if s["where"] and s["where"] != [s["time"]] and not top["uses_where"]:
        res["notes"].append("that one is for the whole song")
    if s.get("carried") and any("{prop" in x for x in (prefs["intents"][top["intent"]].get("do", []))):
        res["notes"].append("the props from before: " + ", ".join(s["prop"]))
    if top["intent"] and "{yard}" not in str(top["commands"]) and ctx.yard and \
            any(_q(ctx.yard) in c for c in top["commands"]) and not find_props(s["ptoks"], ctx, prefs.get("yard_words", [])) \
            and not s.get("carried"):
        res["notes"].append(f"no prop named - the whole yard ({ctx.yard}); name props to narrow it")
    return res


def _chunks(text: str) -> list[str]:
    """Split at ';', 'and', 'then', commas - but not inside quotes."""
    parts, cur, q = [], "", None
    protected = []
    for ch in text:
        if q:
            if ch == q:
                q = None
        elif ch == '"' or (ch == "'" and (not cur or cur[-1] in " ,(")):
            q = ch
        cur += ch
        protected.append(bool(q) or ch in "\"'")
    out, last = [], 0
    for m in SEPARATORS.finditer(cur):
        if any(protected[m.start():m.end()]):
            continue
        out.append(cur[last:m.start()])
        last = m.end()
    out.append(cur[last:])
    return [p.strip() for p in out if p.strip()]


def interpret(text: str, ctx: Ctx, prefs: dict) -> list[dict]:
    chunks = _chunks(text)
    # a piece that means nothing by itself (a prop name, a quoted word) joins its neighbour
    has = [match_clause(c, ctx, prefs)["intent"] is not None for c in chunks]
    merged: list[str] = []
    k = 0
    while k < len(chunks):
        c = chunks[k]
        if not has[k] and k + 1 < len(chunks) and (not merged or has[k + 1]):
            chunks[k + 1] = c + " and " + chunks[k + 1]
            has[k + 1] = match_clause(chunks[k + 1], ctx, prefs)["intent"] is not None
        elif not has[k] and merged:
            merged[-1] = merged[-1] + " and " + c
        else:
            merged.append(c)
        k += 1
    out, carry = [], None
    for c in merged or [text]:
        r = match_clause(c, ctx, prefs, carry)
        if r["prop"]:
            carry = {"prop": r["prop"]}
        out.append(r)
    return out


def normal(cmd: str) -> str:
    """A command for comparing: spaces collapsed, quotes and case of names ignored, a feel value
    as a number ('high' = 0.8)."""
    w = re.sub(r"\s+", " ", cmd.replace('"', "").replace("'", "")).strip().lower().split(" ")
    if len(w) >= 3 and w[0] == "feel":
        from .feel import value
        try:
            w[2] = f"{value(w[2]):g}"
        except ValueError:
            pass
    return " ".join(w)


# ------------------------------------------------------------------ mistyped words (0.24.34)
def vocabulary(ctx: Ctx, prefs: dict) -> set[str]:
    """Every word 'direct' knows: its phrases, the song's sections and sung words, the plan's
    target names, effect names, and plain words never taken as typos (prefs 'plain_words')."""
    v = set(STOP) | set(GENERIC) | set(ORDINALS) | GENERIC_SECTIONS
    for it in (prefs.get("intents") or {}).values():
        for ph in it.get("say", []) + it.get("not", []):
            v.update(tokens(ph))
    for k in ("yard_words", "plain_words"):
        for w in prefs.get(k, []):
            v.update(tokens(w))
    for grp in ("strong", "mild"):
        for w in (prefs.get("degree") or {}).get(grp, []):
            v.update(tokens(w))
    v.update(prefs.get("section_words", {}))
    v.update(w for e in prefs.get("effect_words", {}) for w in tokens(e))
    v.update(str(x.get("type", "")).lower() for x in ctx.sections)
    v.update(p for e in ctx.effects for p in e.split("_"))
    v.update(k for t in ctx.targets for k in _name_tokens(t))
    v.update(ctx.lyrics)
    return {w for w in v if w and w[0].isalpha()}


ENDINGS = ("s", "es", "ed", "d", "er", "r", "ers", "ing", "y", "ly", "ier", "iest", "est", "ish")


def _known(w: str, vocab: set[str]) -> bool:
    """A word it knows, or one of its forms ('calmer', 'spinners', 'flashing')."""
    if w in vocab:
        return True
    for e in ENDINGS:
        if w.endswith(e) and len(w) > len(e) + 2:
            b = w[:-len(e)]
            if b in vocab or b + "e" in vocab or (b[-1:] == b[-2:-1] and b[:-1] in vocab) or \
                    (e[0] == "i" and b + "y" in vocab):
                return True
    return False


def corrections(text: str, ctx: Ctx, prefs: dict) -> dict:
    """{"text": with the near spellings put right, "near": [(word, as, sim)], "unsure": [(word,
    most likely, sim)]}. Words in quotes are checked against the sung words."""
    from ..common import fuzzy
    vocab = vocabulary(ctx, prefs)
    acc, ask = fuzzy.thresholds()
    near, unsure, out = [], [], text
    spans = [(m.start(), m.end()) for m in QUOTED.finditer(text)]
    for m in reversed(list(re.finditer(r"(?<![@\w])[A-Za-z][A-Za-z'-]*[A-Za-z]", text))):
        if len(m.group(0)) < 3:
            continue
        w = m.group(0).lower().replace("'", "")
        inside = any(a <= m.start() < b for a, b in spans)
        pool = sorted(set(ctx.lyrics)) if inside else sorted(vocab)
        if not pool or (w in pool if inside else _known(w, vocab)):
            continue
        kind, best, sim = fuzzy.resolve(w, pool, acc, ask)
        if kind == "near":
            near.append((m.group(0), best, round(sim, 2)))
            out = out[:m.start()] + best + out[m.end():]
        elif kind == "unsure":
            unsure.append((m.group(0), best, round(sim, 2)))
    for m in reversed(list(re.finditer(r"@([A-Za-z][A-Za-z'-]+)", out))):   # '@star': a sung word
        w = m.group(1).lower()
        if w == "vocals" or not ctx.lyrics or w in ctx.lyrics:
            continue
        kind, best, sim = fuzzy.resolve(w, sorted(set(ctx.lyrics)), acc, ask)
        if kind == "near":
            near.append(("@" + m.group(1), "@" + best, round(sim, 2)))
            out = out[:m.start(1)] + best + out[m.end(1):]
        elif kind == "unsure" or kind == "none":
            unsure.append(("@" + m.group(1), "@" + best if best else None, round(sim, 2)))
    return {"text": out, "near": near[::-1], "unsure": unsure[::-1]}
