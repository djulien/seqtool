# seqtool-command: lyrics | main | refine | lyrics of the song: lyrics transcribe | lyrics import FILE | lyrics align [FILE] | lyrics | lyrics clear
"""seqtool lyrics [transcribe | import FILE | align [FILE] | show | clear] [--audio SONG]

Lyrics with timing: transcribed from the singing, or imported from a file:

    lyrics transcribe               Whisper (faster-whisper) on the vocal stem: lines and
                                    word times; --model tiny|base|small|medium|large-v3
                                    (small by default; larger = better and slower),
                                    --language en (detected if not given); a model not
                                    downloaded yet is offered for download
    lyrics models                   the Whisper models, their sizes, which are downloaded
    lyrics transcribe --debug       also write <song>-seqtool/<song>.debug-transcribe.txt: every Whisper
                                    segment with its confidence, and the sung passages left without
                                    words (those are transcribed again on their own unless --no-refill);
                                    --debug works on align and phonemes too
    lyrics align words.txt          your lyrics as plain text (one line per line): timed
                                    from the transcription, which corrects its mistakes;
                                    'lyrics align' alone re-times the lines already stored
    lyrics import song.lrc          LRC: [mm:ss.xx]line text; enhanced LRC <mm:ss.xx>word
                                    timings and [offset:+/-ms] are understood. Each line
                                    starts where the file says, ends where the singing
                                    stops (vocal stem), and its time is shared out over
                                    its words by their sounds - no transcription needed;
                                    'lyrics align song.lrc' does the same, '--times heard'
                                    times the words from the transcription instead
    lyrics import labels.txt        Audacity labels (File > Export > Labels): start, end, text
                                    per line; --as words if each label is one word (they are
                                    grouped into lines at pauses); a plain text file
                                    without times is aligned (as 'lyrics align FILE')
    lyrics phonemes                 the mouth shapes for singing faces: where each word's
                                    sounds came from, the words guessed from their spelling
    lyrics                          show what is stored for the current song (numbered: line.word)
    lyrics word 3.2 "night"         change the text of line 3's second word (0.21.9; the GUI's
                                    magnifier: double-click a word)
    lyrics time 3.2 41.20 41.65     set when a word is sung (seconds or m:ss.x); the line grows to hold it
    lyrics time 3 40.9 44.1         set a line's time - its words are moved and stretched with it
                                    (the magnifier: drag a word's or a line's edges, or the whole of it)
    lyrics starts 3.2 41.2 41.6 42.05
                                    words from line 3's second word on start at these times, one each
                                    (0.22.1); each keeps its length, cut where the next one starts (the
                                    magnifier: tap marks while it plays, then 'snap N words')
    lyrics shift +0.2 from 3.2      move line 3's second word and every word after it 0.2 s later, each
                                    keeping its length (0.24.7; the magnifier: Shift+drag a word)
    lyrics shift -0.3 @1:12         move every line from 1:12 on (the line sung then and all after it)
                                    0.3 s earlier; no @: all of them (0.21.10; the magnifier: Shift+drag
                                    a line or word, or right-click the lyrics)
    lyrics line 3 "new words here"  change line 3's text (0.24.10; the magnifier: right-click > edit text, or
                                    double-click the phrase): as many words as before keep their times,
                                    otherwise the line's time is shared out over the new words by length
    lyrics split 3 @41.5            split line 3 into two at 41.5 s (0.24.8; the words before stay, the
                                    rest start the new line; the magnifier: right-click the line)
    lyrics join 3                   join lines 3 and 4 into one (their words keep their times)
    lyrics split 3.2 @41.5          split word 2 of line 3 at 41.5 s (its text at a space or hyphen, else
                                    shared by the time; or give both: 'lyrics split 3.2 @41.5 Christ mas')
    lyrics join 3.2 [--tight]       join word 2 of line 3 and the next word (--tight: no space between)
    lyrics time 3.2 41.2 41.6 --alone
                                    only this word: a word it touches stays (a gap opens; the magnifier:
                                    Ctrl+drag)
    lyrics tidy                     every word that runs into the next one ends where that one starts
                                    (0.24.4; moving a word does it for the word before; the magnifier:
                                    right-click the lyrics)
    lyrics voice BOB @3.2           who sings from line 3's second word on (0.24.0): BOB until the next
                                    voice; ALL = every voice; '-' takes the mark away. The same as
                                    typing {BOB} before a word anywhere in the lyrics (a file you import,
                                    'lyrics word', aligned text); words before the first one count as
                                    ALL. 'face use PROP FACE --voice BOB' makes a face sing only those
    lyrics from-xsq ["Lyrics"]      the lyrics of a timing track of the .xsq this song was opened from
                                    (or borrows from): its phrases become lines, its words their words
                                    (0.21.10; no name: the track that looks most like lyrics)
    lyrics clear                    forget them

Lyrics are kept per song (seqtool-prefs/songs.json, keyed by the audio, so
re-analysis keeps them; the transcript too, so aligning again doesn't transcribe
again). They are used for:
  * an xLights timing track 'seqtool-lyrics' (phrases, plus a words layer when
    word timing is known) - xlights.timing_tracks / xlights-export --timing;
  * presets: "on": "lyric" (each line) or "word", and conditions such as
    {"lyric": "~(?i)merry"} (~ = regular expression);
  * 'explain music @TIME' shows the line being sung;
  * finding sections: where a repeated block of lines starts and ends, where the
    singing stops, and which sections share their words (chorus) or not (verse).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from ..common import songs
from ..common.log import good, info, warn
from ..common.paths import arg as paths_arg, show

_TS = re.compile(r"\[(\d+):(\d+(?:[.:]\d+)?)\]")
_BARE = re.compile(r"^(\d+):(\d{1,2}(?:[.:]\d+)?)\s+(\S.*)$")     # 0.24.55: '0:12.50 the words' (no brackets)
_WTS = re.compile(r"<(\d+):(\d+(?:[.:]\d+)?)>")


def _secs(m, s) -> float:
    return int(m) * 60 + float(s.replace(":", "."))


def parse_lrc(text: str, duration: float | None = None) -> list[dict]:
    offset = 0.0
    rows: list[tuple[float, str, list]] = []
    for raw in text.splitlines():
        line = raw.strip()
        mo = re.match(r"\[offset:\s*([+-]?\d+)\]", line, re.I)
        if mo:
            offset = int(mo.group(1)) / 1000.0           # positive = lyrics come sooner
            continue
        stamps = _TS.findall(line)
        if not stamps:
            mb = _BARE.match(line)
            if not mb:
                continue
            stamps, line = [(mb.group(1), mb.group(2))], mb.group(3)
        body = _TS.sub("", line).strip()
        words = []
        if _WTS.search(body):
            parts = re.split(r"(<\d+:\d+(?:[.:]\d+)?>)", body)
            cur_t = None
            for p in parts:
                mw = _WTS.fullmatch(p)
                if mw:
                    cur_t = _secs(*mw.groups())
                elif p.strip() and cur_t is not None:
                    for k, w in enumerate(p.split()):
                        words.append([cur_t, w])
            body = _WTS.sub("", body)
            body = " ".join(body.split())
        for m, s in stamps:
            rows.append((_secs(m, s), body, words))
    rows.sort(key=lambda r: r[0])
    lines = []
    for i, (t, body, words) in enumerate(rows):
        end = rows[i + 1][0] if i + 1 < len(rows) else (duration or t + 5.0)
        if not body:
            continue                                     # an empty line ends the previous one
        ln = {"start": round(t - offset, 3), "end": round(end - offset, 3), "text": body}
        if words:
            ws = []
            for k, (wt, w) in enumerate(words):
                we = words[k + 1][0] if k + 1 < len(words) else end
                ws.append({"start": round(wt - offset, 3), "end": round(we - offset, 3), "text": w})
            ln["words"] = ws
        lines.append(ln)
    return lines


def parse_audacity(text: str, as_words: bool | None = None, gap: float = 0.8) -> list[dict]:
    labs = []
    for raw in text.splitlines():
        if not raw.strip() or raw.startswith("\\"):        # '\' lines are frequency ranges
            continue
        parts = raw.split("\t")
        if len(parts) < 2:
            continue
        try:
            a = float(parts[0])
            b = float(parts[1]) if len(parts) > 2 else a
        except ValueError:
            continue
        txt = (parts[2] if len(parts) > 2 else parts[1]).strip()
        labs.append([a, b, txt])
    labs.sort()
    for i, l in enumerate(labs):                           # point labels last until the next one
        if l[1] <= l[0]:
            l[1] = labs[i + 1][0] if i + 1 < len(labs) else l[0] + 3.0
    if as_words is None:                                   # one word per label, short labels -> words
        single = sum(1 for l in labs if len(l[2].split()) <= 1)
        durs = sorted(l[1] - l[0] for l in labs) or [9.9]
        as_words = bool(labs) and single >= 0.8 * len(labs) and durs[len(durs) // 2] < 1.2
    if not as_words:
        return [{"start": round(a, 3), "end": round(b, 3), "text": t} for a, b, t in labs if t]
    lines, cur = [], []
    for a, b, t in labs:
        if cur and a - cur[-1]["end"] > gap:
            lines.append(cur)
            cur = []
        cur.append({"start": round(a, 3), "end": round(b, 3), "text": t})
    if cur:
        lines.append(cur)
    return [{"start": ws[0]["start"], "end": ws[-1]["end"], "text": " ".join(w["text"] for w in ws), "words": ws}
            for ws in lines]


def load_file(path: Path, as_words: bool | None = None, duration: float | None = None,
              shift: float = 0.0) -> dict:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    rows = [ln.strip() for ln in text.splitlines() if ln.strip()]
    bare = sum(1 for ln in rows if _BARE.match(ln))
    is_lrc = path.suffix.lower() == ".lrc" or bool(_TS.search(text[:2000])) or (rows and bare >= len(rows) / 2)
    lines = parse_lrc(text, duration) if is_lrc else parse_audacity(text, as_words)
    if shift:
        for ln in lines:
            ln["start"], ln["end"] = round(ln["start"] + shift, 3), round(ln["end"] + shift, 3)
            for w in ln.get("words", []):
                w["start"], w["end"] = round(w["start"] + shift, 3), round(w["end"] + shift, 3)
    return {"format": "lrc" if is_lrc else "audacity", "source": path.name, "lines": lines}


def for_music(music: dict | None) -> dict | None:
    """The stored lyrics for the song this music analysis is of (None if none) - with the
    {VOICE} codes out of the text (each word says its voice; music/voices.py, 0.24.0)."""
    sha = ((music or {}).get("source") or {}).get("sha256")
    from .voices import for_use
    return for_use(songs.get(sha).get("lyrics")) if sha else None


def _song(audio: Path | None):
    from ..common import current
    from ..common.canonical import file_sha256
    if audio is None:
        s = current.song()
        if not s or not s.get("audio"):
            raise SystemExit("no current song - give --audio SONG (or analyse one first)")
        audio = Path(s["audio"])
    if not audio.exists():
        raise SystemExit(f"{show(audio)} not found")
    return audio, file_sha256(audio)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool lyrics", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", nargs="?", default="show", choices=("show", "import", "clear", "transcribe", "align", "models", "phonemes",
                                                                    "word", "time", "starts", "shift", "from-xsq", "voice", "tidy",
                                                                    "split", "join", "line"))
    ap.add_argument("file", nargs="?")
    ap.add_argument("rest", nargs="*", help="word: the new text; time: START END")
    ap.add_argument("--audio", type=paths_arg, help="the song (default: the current song)")
    ap.add_argument("--alone", action="store_true", help="time L.W: only this word - a word it touches stays where "
                    "it is (a gap opens)")
    ap.add_argument("--tight", action="store_true", help="join L.W: as one word, no space between")
    ap.add_argument("--as", dest="as_", choices=("lines", "words"), help="Audacity labels: one line or one word each")
    ap.add_argument("--offset", type=float, default=0.0, help="shift every time by this many seconds")
    ap.add_argument("--model", default=None, help="transcribe: Whisper model (tiny, base, small, medium, large-v3)")
    ap.add_argument("--language", default=None, help="transcribe: language code, e.g. en (default: detected)")
    ap.add_argument("--times", choices=("file", "heard"), default="file", help="align, with timed lyrics (LRC, "
                    "labels): 'file' (default) - each line starts where the file says and ends where the singing "
                    "stops, its words and sounds shared out by their sounds; 'heard' - the words timed from the "
                    "transcription (Whisper), the file's times only where words aren't recognised")
    ap.add_argument("--report", action="store_true", help="align: list every stretch of your words that wasn't recognised")
    ap.add_argument("--debug", action="store_true", help="write a debug log (path printed): transcribe - every "
                    "Whisper segment and the sung passages without words; align - every one of your words and what "
                    "it was paired with; phonemes - every word's sounds and mouths")
    ap.add_argument("--no-vad", action="store_true", help="transcribe: no voice filter on the first pass either "
                    "(it can cut singing it takes for noise; without it Whisper may invent words in the quiet parts)")
    ap.add_argument("--no-refill", action="store_true", help="transcribe: don't transcribe again the sung passages "
                    "the first pass left without words")
    ap.add_argument("--baseline", nargs="?", metavar="N", help="song N of your baseline instead (no N: each song in turn; 'baseline' lists them)")
    from .phonemes import add_arg, use_arg
    add_arg(ap)
    from ..common.args import dash_words
    a = ap.parse_args(dash_words(ap, argv))           # 'lyrics shift -0.3': a number, not an option
    use_arg(a.dictionary)
    if a.action not in ("word", "time", "starts", "shift", "from-xsq", "voice", "split", "join", "line") and a.file is not None:
        a.file = paths_arg(a.file)
    if a.action == "models":
        from ..common import deps
        from .transcribe import models_table
        fw = deps.need("faster_whisper", purpose="lyrics transcription", pip="faster-whisper", required=True)
        print("Whisper models for 'lyrics transcribe --model NAME' (larger = fewer mistakes, slower):")
        for ln in models_table(fw):
            print(ln)
        print("{note}a model that isn't downloaded yet is offered for download when you use it{/}")
        return 0
    audio, sha = _song(a.audio)
    if a.action == "transcribe":
        return _transcribe(audio, sha, a.model, a.language, a.debug, not a.no_refill, not a.no_vad)
    if a.action == "align":
        timed = _timed_lines(a.file, sha) if a.times == "file" else None
        if timed:
            return _from_phrases(audio, sha, *timed, debug=a.debug)
        return _align(audio, sha, a.file, a.model, a.language, a.report, a.debug)
    if a.action == "import":
        if not a.file:
            raise SystemExit("lyrics import FILE (.lrc, Audacity labels .txt, or plain text to align)")
        doc = load_file(a.file, None if a.as_ is None else a.as_ == "words", None, a.offset)
        if not doc["lines"]:
            from .transcribe import plain_lines
            if plain_lines(a.file.read_text(encoding="utf-8-sig", errors="replace")):
                from ..common import deps
                from ..common.prompt import interactive
                if not deps.installed("faster_whisper") and not interactive():   # else it offers to install it
                    raise SystemExit(
                        f"{show(a.file)}: no times seqtool can read in it, so its lines would have to be timed from the "
                        "singing - that needs the faster-whisper package (pip install faster-whisper). Or give each line "
                        "its time, either way: '[0:12.50] the words' (LRC) or '0:12.50 the words'")
                info(f"{show(a.file)} has no times seqtool can read ('[0:12.50] the words' or '0:12.50 the words'): "
                     "timing its lines from the singing (as 'lyrics align')")
                return _align(audio, sha, a.file, a.model, a.language)
            raise SystemExit(f"no lyrics found in {show(a.file)} - 'lyrics -h' shows the formats (LRC, Audacity labels, plain text)")
        if not any(ln.get("words") for ln in doc["lines"]):     # line times only: words from them (0.19.7)
            return _from_phrases(audio, sha, doc["lines"], doc.get("source") or a.file.name, doc["format"],
                                 debug=a.debug)
        songs.update(sha, audio.name, lyrics=doc)
        nw = sum(len(ln.get("words", [])) for ln in doc["lines"])
        good(f"{audio.name}: {len(doc['lines'])} lyric lines" + (f", {nw} timed words" if nw else "")
             + f" from {show(a.file)} ({doc['format']})")
        prop = "PROP"                                       # an example name from your own plan
        try:
            from ..common import config
            from ..common.canonical import read_json
            lm = config.answer("last_matchup")
            if lm and Path(lm).exists():
                prop = next((p_["target"] for p_ in read_json(Path(lm))["plans"] if p_.get("target_kind") == "model"), prop)
        except Exception:  # noqa: BLE001
            pass
        q = f'"{prop}"' if " " in prop else prop
        print("they are used from the next 'run' on:")
        print("  - the xLights export gets a timing track 'seqtool-lyrics' with the lines"
              + (" (and a layer with the words)" if nw else ""))
        print(f"  - props can react to the singing, e.g. 'react {q} lyric-color' (a new colour for each line)"
              + (f" or 'react {q} word-flash' (a flash on each word)" if nw else ""))
        return 0
    if a.action == "phonemes":
        return _phonemes(audio, sha, a.debug)
    if a.action in ("word", "time"):
        return _edit(audio, sha, a.action, a.file, a.rest, alone=a.alone)
    if a.action == "starts":
        return _starts(audio, sha, a.file, a.rest)
    if a.action == "voice":
        return _voice(audio, sha, a.file, a.rest)
    if a.action == "tidy":
        return _tidy(audio, sha)
    if a.action == "line":
        return _line_text(audio, sha, a.file, a.rest)
    if a.action in ("split", "join"):
        return _split_join(audio, sha, a.action, a.file, a.rest, tight=a.tight)
    if a.action == "shift":
        return _shift(audio, sha, a.file, a.rest)
    if a.action == "from-xsq":
        return _from_xsq(audio, sha, " ".join([x for x in [a.file] + a.rest if x]) or None)
    if a.action == "clear":
        songs.update(sha, audio.name, lyrics=None)
        good(f"{audio.name}: lyrics removed")
        return 0
    doc = songs.get(sha).get("lyrics")
    if not doc:
        print(f"no lyrics for {audio.name} - 'lyrics transcribe' (from the singing), or 'lyrics import FILE' "
              "(.lrc, Audacity labels, or plain text to align)")
        return 0
    print(f"{audio.name}: {len(doc['lines'])} lines from {doc.get('source')} ({doc.get('format')})")
    for i, ln in enumerate(doc["lines"], 1):
        m, s = divmod(ln["start"], 60)
        print(f"  {i:>3}  {int(m)}:{s:05.2f}  {ln['text']}" + (f"   [{len(ln['words'])} words]" if ln.get("words") else "")
              + (f"   {{note}}({', '.join(ln['voices'])}){{/}}" if ln.get("voices") else ""))
    from .voices import names as _vnames
    if _vnames(doc):
        print(f"voices: {', '.join(_vnames(doc))} (and ALL) - 'face use PROP FACE --voice NAME' gives a face one")
    print("{note}'lyrics word L.W TEXT' and 'lyrics time L[.W] START END' fix one, 'lyrics starts L.W T1 T2 ...' several words' starts (the GUI's magnifier does it by mouse, and by tapping along){/}")
    return 0


def _t(text: str) -> float:
    text = str(text).strip().lstrip("@")
    if ":" in text:
        m, s = text.split(":", 1)
        return int(m) * 60 + float(s)
    return float(text)


def _edit(audio: Path, sha: str, action: str, ref: str | None, rest: list[str], alone: bool = False) -> int:
    """lyrics word L.W TEXT | lyrics time L[.W] START END (0.21.9): one word's text, or the time
    of a word or a line, as the magnifier sets them."""
    doc = songs.get(sha).get("lyrics")
    if not doc or not doc.get("lines"):
        raise SystemExit(f"no lyrics for {audio.name} - 'lyrics transcribe' or 'lyrics import FILE' first")
    import copy as _copy
    doc = _copy.deepcopy(doc)
    lines = doc["lines"]
    m = re.fullmatch(r"(\d+)(?:\.(\d+))?", ref or "")
    if not m:
        raise SystemExit(f"lyrics {action} LINE.WORD ... - e.g. 'lyrics {action} 3.2 " + ('"night"' if action == "word"
                         else "41.2 41.65") + "' ('lyrics' numbers them)")
    li = int(m.group(1))
    if not 1 <= li <= len(lines):
        raise SystemExit(f"no line {li} (1-{len(lines)}; 'lyrics' lists them)")
    ln = lines[li - 1]
    wi = int(m.group(2)) if m.group(2) else None
    words = ln.get("words") or []
    if wi is not None and not 1 <= wi <= len(words):
        raise SystemExit(f"line {li} has {len(words)} timed word(s)" + ("" if words else " - its words aren't timed"))
    if action == "word":
        if wi is None or not rest:
            raise SystemExit("lyrics word LINE.WORD TEXT - e.g. 'lyrics word 3.2 night'")
        w = words[wi - 1]
        old = line_text_of(w)
        for k in ("voice_mark", "voice_after"):           # 0.24.44: its codes are the ones in the new text
            w.pop(k, None)
        w["text"] = " ".join(rest)
        from .voices import line_text
        ln["text"] = line_text(words)                     # the other words keep theirs
        msg = f"line {li}, word {wi}: '{old}' -> '{words[wi - 1]['text']}'"
    else:
        if len(rest) != 2:
            raise SystemExit(f"lyrics time {ref} START END - e.g. 'lyrics time {ref} 41.2 41.65'")
        a0, b0 = _t(rest[0]), _t(rest[1])
        if b0 <= a0:
            raise SystemExit("the end comes before the start")
        if wi is not None:
            w = words[wi - 1]
            edge = w is words[0] or w is words[-1]
            seq = sorted((x for l_ in lines for x in (l_.get("words") or [])), key=lambda x: x["start"])
            k = next(i for i, x in enumerate(seq) if x is w)
            pv = seq[k - 1] if k > 0 else None                  # 0.24.8: a neighbour that touched it still does
            nx = seq[k + 1] if k + 1 < len(seq) else None
            line_of = {id(x): j for j, l_ in enumerate(lines) for x in (l_.get("words") or [])}
            same = lambda x: line_of.get(id(x)) == line_of.get(id(w))          # noqa: E731
            # 0.24.21: a touching neighbour follows - but not one across a phrase boundary, nor with
            # --alone (Ctrl+drag): then a gap opens (a neighbour run into is still cut back)
            pv_t = pv is not None and abs(pv["end"] - w["start"]) < 0.015 and not alone and same(pv)
            nx_t = nx is not None and abs(nx["start"] - w["end"]) < 0.015 and not alone and same(nx)
            w["start"], w["end"] = round(a0, 3), round(b0, 3)
            kept = ""
            if pv is not None and not pv_t and pv["end"] > a0 + 1e-6 and a0 - pv["start"] >= 0.05:
                pv_t = True                               # ran into the word before - it ends earlier
            if pv_t and a0 - pv["start"] >= 0.05 and abs(pv["end"] - a0) > 1e-6:
                pv["end"] = round(a0, 3)
                kept += f"; '{pv['text']}' before it now ends there"
            if nx is not None and not nx_t and nx["start"] < b0 - 1e-6 and nx["end"] - b0 >= 0.05:
                nx_t = True                               # 0.24.11: ran into the next word - it starts later
            if nx_t and nx["end"] - b0 >= 0.05 and abs(nx["start"] - b0) > 1e-6:
                nx["start"] = round(b0, 3)
                kept += f"; '{nx['text']}' after it now starts there"
                for l_ in lines:
                    if any(x is nx for x in (l_.get("words") or [])) and l_ is not ln:
                        l_["start"] = round(min(x["start"] for x in l_["words"]), 3)
            words.sort(key=lambda x: x["start"])
            ln["start"], ln["end"] = round(min(ln["start"], a0), 3), round(max(ln["end"], b0), 3)
            if edge or w is words[0] or w is words[-1]:          # 0.24.6: the phrase follows its first / last word
                ln["start"], ln["end"] = round(words[0]["start"], 3), round(max(x["end"] for x in words), 3)
            msg = f"line {li}, '{w['text']}': {a0:.2f}-{b0:.2f} s" + kept + _tidy_before(lines, w) + _phrase_neighbours(lines, li - 1)
        else:
            s0, e0 = ln["start"], ln["end"]
            k = (b0 - a0) / max(1e-6, e0 - s0)
            for w in words:                              # moved and stretched with the line
                w["start"] = round(a0 + (w["start"] - s0) * k, 3)
                w["end"] = round(a0 + (w["end"] - s0) * k, 3)
            ln["start"], ln["end"] = round(a0, 3), round(b0, 3)
            msg = f"line {li}: {a0:.2f}-{b0:.2f} s" + (f" (its {len(words)} words with it)" if words else "")
    doc["edited"] = True
    songs.update(sha, audio.name, lyrics=doc)
    good(f"{audio.name}: {msg} - 'run' again to use it (faces, reactions, the timing track); 'undo' takes it back")
    return 0


def _line_text(audio: Path, sha: str, ref: str | None, rest: list[str]) -> int:
    """lyrics line L TEXT (0.24.10): a phrase's text. The same number of words: each keeps its
    time (and voice mark); another number: the phrase's sung time shared out by word length."""
    from .voices import CODE
    doc = songs.get(sha).get("lyrics")
    if not doc or not doc.get("lines"):
        raise SystemExit(f"no lyrics for {audio.name} - 'lyrics transcribe' or 'lyrics import FILE' first")
    text = " ".join(rest).strip()
    if not ref or not ref.isdigit() or not text:
        raise SystemExit("lyrics line LINE TEXT - e.g. 'lyrics line 3 \"silent night, holy night\"' ('lyrics' numbers them)")
    import copy as _copy
    doc = _copy.deepcopy(doc)
    lines = doc["lines"]
    i = int(ref) - 1
    if not 0 <= i < len(lines):
        raise SystemExit(f"no line {i + 1} (1-{len(lines)})")
    ln = lines[i]
    old = ln.get("text", "")
    toks = [t for t in text.split() if CODE.sub("", t).strip()]
    words = ln.get("words") or []
    how = ""
    if words and len(toks) == len(words):
        for w, t in zip(words, toks):
            w["text"] = CODE.sub("", t).strip()
        how = "each word keeps its time"
    elif words:
        a, b = words[0]["start"], max(w["end"] for w in words)
        sizes = [len(CODE.sub("", t)) + 1 for t in toks]
        tot, pos, new = sum(sizes), a, []
        for t, n in zip(toks, sizes):
            e = pos + (b - a) * n / tot
            new.append({"start": round(pos, 3), "end": round(e, 3), "text": CODE.sub("", t).strip()})
            pos = e
        if words[0].get("voice_mark"):
            new[0]["voice_mark"] = words[0]["voice_mark"]
        ln["words"] = new
        how = f"{len(words)} -> {len(new)} words, the time shared out by length"
    ln["text"] = text
    doc["edited"] = True
    songs.update(sha, audio.name, lyrics=doc)
    good(f"{audio.name}: line {i + 1}: '{old[:40]}' -> '{text[:40]}'" + (f" ({how})" if how else "")
         + " - 'undo' takes it back")
    return 0


def _split_join(audio: Path, sha: str, action: str, ref: str | None, rest: list[str], tight: bool = False) -> int:
    """lyrics split L @TIME | lyrics join L (0.24.8): one phrase into two at a time, or a phrase and
    the next into one. Words keep their times; each phrase spans its words."""
    doc = songs.get(sha).get("lyrics")
    if not doc or not doc.get("lines"):
        raise SystemExit(f"no lyrics for {audio.name} - 'lyrics transcribe' or 'lyrics import FILE' first")
    import copy as _copy
    doc = _copy.deepcopy(doc)
    lines = doc["lines"]
    wref = None
    if ref and re.fullmatch(r"\d+\.\d+", ref):                 # 0.24.21: L.W - a word
        ref, wref = ref.split(".")
        wref = int(wref)
    if not ref or not ref.isdigit() or not 1 <= int(ref) <= len(lines):
        raise SystemExit(f"lyrics {action} LINE" + (" @TIME" if action == "split" else "")
                         + f" - e.g. 'lyrics {action} 3" + (" @41.5'" if action == "split" else "'") + " ('lyrics' numbers them)")
    i = int(ref) - 1
    ln = lines[i]
    if wref is not None:
        return _split_join_word(audio, sha, doc, action, i, wref, rest, tight)
    if action == "join":
        if i + 1 >= len(lines):
            raise SystemExit(f"line {i + 1} is the last one - nothing after it to join")
        nx = lines.pop(i + 1)
        ln["words"] = (ln.get("words") or []) + (nx.get("words") or [])
        ln["text"] = (ln.get("text", "") + " " + nx.get("text", "")).strip()
        ln["start"], ln["end"] = round(min(ln["start"], nx["start"]), 3), round(max(ln["end"], nx["end"]), 3)
        msg = f"lines {i + 1} and {i + 2} are one now ({ln['start']:.2f}-{ln['end']:.2f} s)"
    else:
        at = next((r for r in rest if r.startswith("@")), None)
        if not at:
            raise SystemExit(f"lyrics split {i + 1} @TIME - e.g. 'lyrics split {i + 1} @{(ln['start'] + ln['end']) / 2:.2f}'")
        t = _t(at[1:])
        words = ln.get("words") or []
        if words:
            first = [w for w in words if (w["start"] + w["end"]) / 2 < t]      # a word cut in two goes where most of it is
            second = words[len(first):]
            if not first or not second:
                raise SystemExit(f"{t:.2f} s is not between two words of line {i + 1} - split between its words")
            a_ = {**ln, "words": first, "text": _join_text(first),
                  "start": ln["start"], "end": round(max(w["end"] for w in first), 3)}
            b_ = {**{k: v for k, v in ln.items() if k not in ("words", "text")}, "words": second,
                  "text": _join_text(second), "start": round(second[0]["start"], 3), "end": ln["end"]}
        else:
            if not ln["start"] < t < ln["end"]:
                raise SystemExit(f"{t:.2f} s is not inside line {i + 1} ({ln['start']:.2f}-{ln['end']:.2f} s)")
            toks = ln.get("text", "").split()
            k = max(1, min(len(toks) - 1, round(len(toks) * (t - ln["start"]) / (ln["end"] - ln["start"]))))
            if len(toks) < 2:
                raise SystemExit(f"line {i + 1} has one word - nothing to split")
            a_ = {**ln, "text": " ".join(toks[:k]), "end": round(t, 3)}
            b_ = {**ln, "text": " ".join(toks[k:]), "start": round(t, 3)}
        lines[i:i + 1] = [a_, b_]
        msg = f"line {i + 1} split at {t:.2f} s: '{a_['text'][:30]}' / '{b_['text'][:30]}'"
    doc["edited"] = True
    songs.update(sha, audio.name, lyrics=doc)
    good(f"{audio.name}: {msg} - the lines after it are numbered on; 'undo' takes it back")
    return 0


def _split_join_word(audio: Path, sha: str, doc: dict, action: str, i: int, wi: int, rest: list[str],
                     tight: bool) -> int:
    """lyrics split L.W @TIME [TEXT TEXT] | lyrics join L.W [--tight] (0.24.21): a word into two at a
    time (the text at its space or hyphen, else shared by the time; or as you give it), or a word
    and the next one of its line into one."""
    from .voices import _marked_text
    ln = doc["lines"][i]
    words = ln.get("words") or []
    if not words:
        raise SystemExit(f"line {i + 1}'s words aren't timed - 'lyrics align' first")
    if not 1 <= wi <= len(words):
        raise SystemExit(f"line {i + 1} has {len(words)} word(s) - e.g. 'lyrics {action} {i + 1}.1'")
    w = words[wi - 1]
    if action == "join":
        if wi >= len(words):
            raise SystemExit(f"'{w['text']}' is the last word of line {i + 1} - join phrases with 'lyrics join {i + 1}'")
        nx = words.pop(wi)
        w["text"] = w["text"] + ("" if tight else " ") + nx["text"]
        w["start"], w["end"] = round(min(w["start"], nx["start"]), 3), round(max(w["end"], nx["end"]), 3)
        msg = f"line {i + 1}: '{w['text']}' is one word now ({w['start']:.2f}-{w['end']:.2f} s)"
    else:
        at = next((r for r in rest if r.startswith("@")), None)
        if not at:
            raise SystemExit(f"lyrics split {i + 1}.{wi} @TIME - e.g. 'lyrics split {i + 1}.{wi} "
                             f"@{(w['start'] + w['end']) / 2:.2f}'")
        t = _t(at[1:])
        if not w["start"] + 0.03 <= t <= w["end"] - 0.03:
            raise SystemExit(f"{t:.2f} s is not inside '{w['text']}' ({w['start']:.2f}-{w['end']:.2f} s)")
        given = [r for r in rest if not r.startswith("@")]
        txt = w["text"]
        if len(given) == 2:
            t1, t2 = given
        else:
            frac = (t - w["start"]) / (w["end"] - w["start"])
            cut = [k for k, ch in enumerate(txt) if ch in " -"]
            if cut:
                k = min(cut, key=lambda k: abs(k / max(1, len(txt)) - frac))
                t1, t2 = (txt[:k], txt[k + 1:]) if txt[k] == " " else (txt[:k + 1], txt[k + 1:])
            else:
                if len(txt) < 2:
                    raise SystemExit(f"'{txt}' has one letter - give the two texts: "
                                     f"'lyrics split {i + 1}.{wi} {at} {txt} {txt}'")
                k = max(1, min(len(txt) - 1, round(len(txt) * frac)))
                t1, t2 = txt[:k], txt[k:]
        w2 = {k: v for k, v in w.items() if k != "voice_mark"}
        w.update(text=t1.strip(), end=round(t, 3))
        w2.update(text=t2.strip(), start=round(t, 3))
        words.insert(wi, w2)
        msg = f"line {i + 1}: '{txt}' split at {t:.2f} s into '{w['text']}' / '{w2['text']}'" + \
            ("" if len(given) == 2 or " " in txt or "-" in txt else
             f" - fix the texts with 'lyrics word {i + 1}.{wi} TEXT' (or double-click them in the magnifier)")
    ln["text"] = _marked_text(ln.get("text", ""), words)
    doc["edited"] = True
    songs.update(sha, audio.name, lyrics=doc)
    good(f"{audio.name}: {msg} - the words after it are numbered on; 'undo' takes it back")
    return 0


def overlaps(lines: list[dict]) -> list[tuple[dict, dict]]:
    """(word, the next word) pairs where the word runs into the next one."""
    seq = sorted((x for ln in lines for x in (ln.get("words") or [])), key=lambda x: x["start"])
    return [(a, b) for a, b in zip(seq, seq[1:]) if a["end"] > b["start"] + 1e-6]


def _tidy(audio: Path, sha: str) -> int:
    """lyrics tidy (0.24.4): every word that runs into the next ends where that one starts."""
    doc = songs.get(sha).get("lyrics")
    if not doc or not doc.get("lines"):
        raise SystemExit(f"no lyrics for {audio.name} - 'lyrics transcribe' or 'lyrics import FILE' first")
    import copy as _copy
    doc = _copy.deepcopy(doc)
    n, odd = 0, []
    for a, b in overlaps(doc["lines"]):
        if b["start"] - a["start"] >= 0.05:
            a["end"] = round(b["start"], 3)
            n += 1
        else:
            odd.append(f"'{a['text']}' / '{b['text']}' at {a['start']:.2f}")
    if not n:
        good(f"{audio.name}: no words run into the next one" + (f" (but {len(odd)} start together: "
                                                                f"{'; '.join(odd[:3])} - drag one)" if odd else ""))
        return 0
    for ln in doc["lines"]:
        if ln.get("words"):
            ln["end"] = round(max(x["end"] for x in ln["words"]), 3)
    doc["edited"] = True
    songs.update(sha, audio.name, lyrics=doc)
    good(f"{audio.name}: {n} word(s) now end where the next one starts"
         + (f"; {len(odd)} pair(s) start together - drag one apart: {'; '.join(odd[:3])}" if odd else "")
         + " - 'undo' takes it back")
    return 0


def _shift_words(audio: Path, sha: str, doc: dict, d: float, ref: str) -> int:
    """lyrics shift DELTA @L.W (0.24.7): that word and every word after it moved by DELTA, each
    keeping its length; the word before is cut if they now overlap; phrases follow their words."""
    import copy as _copy
    doc = _copy.deepcopy(doc)
    lines = doc["lines"]
    li, wi = (int(x) for x in ref.split("."))
    if not 1 <= li <= len(lines) or not 1 <= wi <= len(lines[li - 1].get("words") or []):
        raise SystemExit(f"no word {ref} ('lyrics' numbers them)")
    first = lines[li - 1]["words"][wi - 1]
    seq = [(i, w) for i, ln in enumerate(lines) for w in (ln.get("words") or [])]
    k = next(j for j, (_, w) in enumerate(seq) if w is first)
    if d < 0:
        d = max(d, -first["start"])
    moved = seq[k:]
    for _, w in moved:
        w["start"], w["end"] = round(w["start"] + d, 3), round(w["end"] + d, 3)
    touched = sorted({i for i, _ in moved})
    for i in touched:
        ln = lines[i]
        ws = ln["words"]
        if all(any(w is x for _, x in moved) for w in ws):              # the whole phrase moved
            ln["start"], ln["end"] = round(ln["start"] + d, 3), round(ln["end"] + d, 3)
        ln["start"] = round(min(ln["start"], min(x["start"] for x in ws)), 3)
        ln["end"] = round(max(x["end"] for x in ws), 3)
        if i == li - 1 and wi == 1:
            ln["start"] = round(ws[0]["start"], 3)
    note = _tidy_before(lines, first) if d < 0 else ""
    note += _phrase_neighbours(lines, li - 1)
    doc["edited"] = True
    songs.update(sha, audio.name, lyrics=doc)
    good(f"{audio.name}: {len(moved)} word(s) from {ref} ('{first['text']}') on moved {d:+.2f} s" + note
         + " - 'undo' takes it back")
    return 0


def _phrase_neighbours(lines: list[dict], i: int) -> str:
    """0.24.6: a phrase that grew into the one before or after moves that one's boundary (never past
    that phrase's own words)."""
    ln, out = lines[i], []
    if i > 0:
        pv = lines[i - 1]
        floor = max([x["end"] for x in pv.get("words") or []] + [pv["start"]])
        if pv["end"] > ln["start"] and ln["start"] >= floor:
            pv["end"] = ln["start"]
            out.append(f"line {i} ends at {ln['start']:.2f}")
    if i + 1 < len(lines):
        nx = lines[i + 1]
        ceil = min([x["start"] for x in nx.get("words") or []] + [nx["end"]])
        if nx["start"] < ln["end"] and ln["end"] <= ceil:
            nx["start"] = ln["end"]
            out.append(f"line {i + 2} starts at {ln['end']:.2f}")
    return ("; " + ", ".join(out)) if out else ""


def _tidy_before(lines: list[dict], w: dict) -> str:
    """0.24.3: the word sung before `w` ends where `w` now starts, if it ran into it (and it keeps
    at least 0.05 s); its line ends with its last word. Returns a note for the message."""
    seq = [(ln, x) for ln in lines for x in (ln.get("words") or [])]
    seq.sort(key=lambda p: p[1]["start"])
    k = next((i for i, (_, x) in enumerate(seq) if x is w), None)
    if not k:
        return ""
    ln, prev = seq[k - 1]
    if prev["end"] <= w["start"] + 1e-6 or w["start"] - prev["start"] < 0.05:
        return ""
    prev["end"] = round(w["start"], 3)
    if ln.get("words"):
        ln["end"] = round(max(x["end"] for x in ln["words"]), 3)
    return f"; '{prev['text']}' before it now ends there"


def _starts(audio: Path, sha: str, ref: str | None, rest: list[str]) -> int:
    """lyrics starts L.W T1 T2 ... (0.22.1): the words from L.W on, in the order they are sung,
    start at T1, T2 ... - the magnifier's 'snap N words' to the marks tapped while it played.
    A word keeps its length, cut where the next one starts; a line grows or shrinks to its words."""
    doc = songs.get(sha).get("lyrics")
    if not doc or not doc.get("lines"):
        raise SystemExit(f"no lyrics for {audio.name} - 'lyrics transcribe' or 'lyrics import FILE' first")
    m = re.fullmatch(r"(\d+)\.(\d+)", ref or "")
    if not m or not rest:
        raise SystemExit("lyrics starts LINE.WORD TIME [TIME ...] - e.g. 'lyrics starts 3.2 41.2 41.6 42.05' "
                         "('lyrics' numbers the words)")
    times = [_t(x) for x in rest]
    if any(b <= a for a, b in zip(times, times[1:])):
        raise SystemExit("lyrics starts: the times must go up, one per word in the order they are sung")
    import copy as _copy
    doc = _copy.deepcopy(doc)
    lines = doc["lines"]
    li, wi = int(m.group(1)), int(m.group(2))
    if not 1 <= li <= len(lines) or not 1 <= wi <= len(lines[li - 1].get("words") or []):
        raise SystemExit(f"no word {ref} ('lyrics' numbers them; words need timing - 'lyrics align')")
    seq = [(i, w) for i, ln in enumerate(lines) for w in (ln.get("words") or [])]
    first = next(k for k, (i, w) in enumerate(seq) if i == li - 1 and w is lines[li - 1]["words"][wi - 1])
    todo = seq[first: first + len(times)]
    for k, ((i, w), t) in enumerate(zip(todo, times)):
        dur = max(0.05, w["end"] - w["start"])
        nxt = times[k + 1] if k + 1 < len(times) and k + 1 < len(todo) else \
            (seq[first + k + 1][1]["start"] if first + k + 1 < len(seq) else None)
        end = t + dur if nxt is None or nxt <= t else min(t + dur, nxt)
        w["start"], w["end"] = round(t, 3), round(max(end, t + 0.05), 3)
    tidy = _tidy_before(lines, todo[0][1])
    for i in {i for i, _ in todo}:
        ws = lines[i]["words"]
        ws.sort(key=lambda x: x["start"])
        lines[i]["start"], lines[i]["end"] = round(min(x["start"] for x in ws), 3), round(max(x["end"] for x in ws), 3)
    doc["edited"] = True
    songs.update(sha, audio.name, lyrics=doc)
    left = len(times) - len(todo)
    good(f"{audio.name}: {len(todo)} word(s) from line {li}.{wi} ('{todo[0][1]['text']}') start at the given times"
         + (f"; {left} time(s) left over - no more words" if left > 0 else "") + tidy
         + " - 'run' again to use them; 'undo' takes it back")
    return 0


def _voice(audio: Path, sha: str, name: str | None, rest: list[str]) -> int:
    """lyrics voice NAME @L[.W] (0.24.0): NAME sings from that word (or line) on."""
    doc = songs.get(sha).get("lyrics")
    if not doc or not doc.get("lines"):
        raise SystemExit(f"no lyrics for {audio.name} - 'lyrics transcribe' or 'lyrics import FILE' first")
    at = next((r for r in rest if r.startswith("@")), None)
    m = re.fullmatch(r"@(\d+)(?:\.(\d+))?", at or "")
    if not name or not m:
        raise SystemExit("lyrics voice NAME @LINE[.WORD] - e.g. 'lyrics voice BOB @3.2' (ALL = everyone; '-' takes "
                         "a mark away; 'lyrics' numbers the lines)")
    import copy as _copy
    doc = _copy.deepcopy(doc)
    li, wi = int(m.group(1)), int(m.group(2) or 1)
    if not 1 <= li <= len(doc["lines"]):
        raise SystemExit(f"no line {li} (1-{len(doc['lines'])})")
    ln = doc["lines"][li - 1]
    words = ln.get("words") or []
    if words:
        if not 1 <= wi <= len(words):
            raise SystemExit(f"line {li} has {len(words)} word(s)")
        words[wi - 1]["voice_mark"] = "" if name == "-" else name
        from .voices import strip as _strip
        ln["text"] = _strip(ln["text"])              # the marks on the words say it; they go back in the text
    else:
        from .voices import strip
        ln["text"] = strip(ln["text"]) if name == "-" else "{" + name + "} " + strip(ln["text"])
    doc["edited"] = True
    songs.update(sha, audio.name, lyrics=doc)
    good(f"{audio.name}: " + (f"no voice mark at {li}.{wi} now" if name == "-" else
                              f"{name} sings from line {li}" + (f", word {wi}" if words else "") + " on")
         + " - 'lyrics' shows the voices; 'undo' takes it back")
    return 0


def _phonemes(audio: Path, sha: str, debug: bool = False) -> int:
    from .phonemes import Dictionary, describe, for_words
    doc = songs.get(sha).get("lyrics")
    words = [w for ln in (doc or {}).get("lines", []) for w in ln.get("words", [])]
    if not words:
        raise SystemExit(f"no timed words for {audio.name} - 'lyrics transcribe' (word times from the singing) "
                         "or 'lyrics align words.txt'")
    d = Dictionary()
    print(f"dictionaries: your add-on {d.addon} ({len(d.words)} words)"
          + "".join(f", then {n}" for n in d.names) + "{note}  ('--dictionary FILE' uses another add-on){/}")
    marks, rep = for_words(words, d)
    for ln in describe(rep, d):
        print(ln)
    if debug:
        from ..common.debuglog import DebugLog
        from .phonemes import mouths as _mouths
        dbg = DebugLog.for_song(audio, "phonemes")
        dbg.kv(add_on_dictionary=f"{d.addon} ({len(d.words)} words)", dictionaries=", ".join(d.names) or "none",
               missing=", ".join(d.missing) or "none")
        dbg.head("every sung word: time, where its sounds came from, the sounds, the mouths and their times")
        for w in words:
            snd, srcname = d.lookup(w["text"])
            ms = [f"{m[2]}@{m[0]:.2f}" for m in marks if w["start"] - 1e-6 <= m[0] < w["end"] - 1e-6]
            dbg.line(f"{w['start']:8.2f}-{w['end']:<8.2f} {w['text']:<16} {srcname:<10} {' '.join(snd):<24} {' '.join(ms)}")
        dbg.save()
    print("{head}the first lines, each word with its mouth shapes:{/}")
    for line in [ln for ln in doc["lines"] if ln.get("words")][:3]:
        parts = []
        for w in line["words"]:
            ms = [m[2] for m in marks if w["start"] - 1e-6 <= m[0] < w["end"] - 1e-6]
            parts.append(f"{w['text']} {{note}}{' '.join(ms) or '-'}{{/}}")
        print("  " + "  ".join(parts))
    print("{note}the xLights export writes them as the third layer of the seqtool-lyrics timing track "
          "(phrases, words, phonemes), which the Faces effect reads{/}")
    return 0


def _used_for(nw: int) -> None:
    print("they are used from the next 'run' on: section detection, the 'seqtool-lyrics' timing track"
          + (" (with words)" if nw else "") + ", and presets such as 'react PROP lyric-color'")


def _sung_passages(audio: Path) -> list[tuple[float, float]] | None:
    """Where the vocal stem has singing (vocals or mixed), from the song's analysis."""
    try:
        from ..common import current
        from ..common.canonical import read_json
        cur = current.song(audio)
        if not cur or not cur.get("music"):
            return None
        from .vocals import regions
        regs = regions(read_json(cur["music"]), None, None)
        out: list[list[float]] = []
        for a, b, kind in regs:
            if kind in ("v", "m"):
                if out and a - out[-1][1] < 0.3:
                    out[-1][1] = b
                else:
                    out.append([a, b])
        return [(a, b) for a, b in out] or None
    except Exception:  # noqa: BLE001
        return None


def _transcribe(audio: Path, sha: str, model: str | None, language: str | None,
                debug: bool = False, refill: bool = True, vad: bool = True) -> int:
    from ..common import config
    from .transcribe import DEFAULT_MODEL, transcribe
    why = "you chose it (--model)" if model else None
    if not model and config.answer("whisper_model"):
        model, why = config.answer("whisper_model"), "the one you used last; --model NAME for another"
    if not model:
        model, why = DEFAULT_MODEL, "the default; --model NAME for another ('lyrics models' lists them)"
    info(f"song: {show(audio)}")
    info(f"Whisper model: {model} ({why})")
    passages = _sung_passages(audio)
    if passages is None:
        info("  {note}no vocal-stem analysis for this song, so passages Whisper skips can't be found and filled "
             "('run --stems' makes it){/}")
    log: list | None = [] if debug else None
    doc = transcribe(audio, model, language, passages, refill, vad, log)
    config.remember("whisper_model", model)
    if log is not None:
        from .transcribe import write_log
        from ..common.paths import seqtool_folder
        d = seqtool_folder(audio)
        d.mkdir(parents=True, exist_ok=True)
        lf = d / f"{audio.stem}.debug-transcribe.txt"
        write_log(lf, log, {"song": audio.name, "model": model, "voice filter (VAD)": "on" if vad else "off",
                            "condition on previous text": "off", "refill": "on" if refill else "off",
                            "sung passages": len(passages or [])})
        info(f"  {{note}}debug log: {show(lf)}{{/}}")
    if not doc["lines"]:
        warn("no singing was recognised - is there a vocal stem ('run --stems')? A larger model may help: "
             "'lyrics transcribe --model medium'")
        return 1
    have = songs.get(sha).get("lyrics")
    keep = bool(have) and have.get("format") != "transcribed"        # never replace lyrics you gave
    songs.update(sha, audio.name, transcript=doc, **({} if keep else {"lyrics": doc}))
    nw = sum(len(ln.get("words", [])) for ln in doc["lines"])
    good(f"{audio.name}: transcribed {len(doc['lines'])} lines, {nw} words ({doc['source']}, language {doc.get('language')})")
    if keep:
        info(f"  your lyrics from {have.get('source')} are kept; 'lyrics align' times their words from the "
             "transcript ('lyrics clear', then 'lyrics transcribe' uses the transcription instead)")
        return 0
    print("check them: 'lyrics' lists the lines; transcription mishears words - for exact lyrics, paste them "
          "into a text file and 'lyrics align FILE'")
    _used_for(nw)
    return 0


def _timed_lines(file: Path | None, sha: str) -> tuple[list[dict], str, str] | None:
    """Lines with the file's start times: from FILE (LRC / labels), or the stored lyrics
    when they came from such a file - else None (plain text: only the singing times it)."""
    if file is not None:
        if file.suffix.lower() not in (".lrc", ".txt", ".labels"):
            return None
        doc = load_file(file)
        lines = [ln for ln in doc.get("lines", []) if ln.get("text")]
        return (lines, file.name, doc.get("format", "lrc")) if lines else None
    doc = songs.get(sha).get("lyrics") or {}
    if doc.get("format") in ("lrc", "audacity") or doc.get("timed_by") == "phrases":
        return [ln for ln in doc["lines"] if ln.get("text")], doc.get("source") or "your lyrics", doc["format"]
    return None


def _from_phrases(audio: Path, sha: str, lines: list[dict], src: str, fmt: str, debug: bool = False) -> int:
    """The user's design (0.19.7): phrase starts from the file, ends from the vocal stem,
    words and sounds shared out by their sounds (music/lyric_timing)."""
    from .lyric_timing import sung_mask, time_lines
    from .phonemes import Dictionary
    if not lines:
        raise SystemExit(f"no lyric lines in {src}")
    mask = sung_mask(audio)
    d = Dictionary()
    end = len(mask[1]) * mask[0] if mask else None
    out, how = time_lines(lines, d, mask, end)
    songs.update(sha, audio.name, lyrics={"format": fmt, "source": src, "timed_by": "phrases", "lines": out})
    nw = sum(len(ln["words"]) for ln in out)
    good(f"{audio.name}: {len(out)} lines from {src}, each starting where the file says; {nw} words timed from "
         "their sounds")
    if how.get("stem"):
        info(f"  {how['stem']} line(s) end where the vocal stem shows the singing stop"
             + (f"; {how['plain']} where it showed hardly any singing, after the words' natural length"
                if how.get("plain") else ""))
    else:
        info("  {warn}no vocal stem for this song{/}: each line ends after its words' natural length (or at the "
             "next line) - 'analyze-music' with stems gives better ends")
    guessed = sorted({w["text"] for ln in out for w in ln["words"] if d.lookup(w["text"])[1] == "spelling"})
    if guessed:
        info(f"  {len(guessed)} word(s) not in the dictionary, their sounds guessed from the spelling: "
             + ", ".join(guessed[:10]) + (" ..." if len(guessed) > 10 else "")
             + "  {note}('lyrics phonemes' lists lines to correct them){/}")
    if debug:
        from ..common.debuglog import DebugLog
        dbg = DebugLog.for_song(audio, "align")
        dbg.kv(lyrics=src, method="phrase times from the file, ends from the vocal stem, words by their sounds",
               vocal_stem="yes" if mask else "no", ends=", ".join(f"{k}: {v}" for k, v in how.items()))
        dbg.head("every line, then each word: its time and its sounds' times")
        for ln in out:
            dbg.line(f"{ln['start']:8.2f}-{ln['end']:<8.2f} {ln['text']}")
            for w in ln["words"]:
                dbg.line(f"      {w['start']:8.2f}-{w['end']:<8.2f} {w['text']:<14} "
                         + " ".join(f"{x[0]}@{x[1]:.2f}" for x in w.get("sounds", [])))
        dbg.save()
    _used_for(nw)
    return 0


def _align(audio: Path, sha: str, file: Path | None, model: str | None, language: str | None,
           full_report: bool = False, debug: bool = False, file_times: bool = False) -> int:
    from .transcribe import align, all_words, describe_report, plain_lines
    rec = songs.get(sha)
    starts = None
    if file is not None:
        doc = load_file(file) if file.suffix.lower() in (".lrc", ".txt", ".labels") else {"lines": []}
        timed = [ln for ln in doc.get("lines", []) if ln.get("text")]
        if timed:                                    # LRC or Audacity labels: their text, and their times as anchors
            texts = [ln["text"] for ln in timed]
            starts = [ln.get("start") for ln in timed]
            info(f"  {file.name} is {doc.get('format', 'timed').upper()}: the words are timed from the transcription "
                 "where they are recognised, from the file's line times elsewhere {note}(without --times heard, the "
                 "file's line times are kept and the words shared out by their sounds){/}")
        else:
            texts = plain_lines(file.read_text(encoding="utf-8-sig", errors="replace"))
        src = file.name
    elif rec.get("lyrics"):
        texts = [ln["text"] for ln in rec["lyrics"]["lines"]]
        src = rec["lyrics"].get("source") or "your lyrics"
    else:
        raise SystemExit("nothing to align - give the lyrics as a text file: 'lyrics align words.txt'")
    if not texts:
        raise SystemExit(f"no lyric lines in {show(file)}")
    if not rec.get("transcript"):
        info("no transcript of this song yet - transcribing first (once; it is kept)")
        if _transcribe(audio, sha, model, language):
            return 1
        rec = songs.get(sha)
    words = all_words(rec["transcript"])
    report: list = []
    pairs: list | None = [] if debug else None
    about: dict = {}
    lines, share = align(texts, words, report, starts, pairs, file_times, about)
    if about.get("offset"):
        info(f"  the file's times are {abs(about['offset']):.1f} s {'early' if about['offset'] > 0 else 'late'} "
             "all through (another edit of the song?) - shifted to the singing")
    if not lines:
        raise SystemExit("none of your words were found in the transcript - is it the right song? "
                         "'lyrics transcribe --model medium' tries a better transcription")
    songs.update(sha, audio.name, lyrics={"format": "aligned", "source": src, "lines": lines})
    good(f"{audio.name}: {len(lines)} lines from {src}, timed from the singing ({share:.0%} of the words recognised)")
    if share < 0.5:
        warn("under half of the words were recognised, so many times are guesses - check with 'lyrics' or in the "
             "GUI; 'lyrics transcribe --model medium' and then 'lyrics align' again may do better")
    if debug:
        from ..common.debuglog import DebugLog
        dbg = DebugLog.for_song(audio, "align")
        dbg.kv(lyrics=src, transcript=rec["transcript"].get("source"), recognised=f"{share:.0%}",
               timed_lyrics=("yes - " + ("line starts from the file (--times file)" if file_times else
                                         "line times used where words weren't recognised")
                             + (f"; shifted {about['offset']:+.2f} s" if about.get("offset") else "")) if starts else "no")
        dbg.head("every one of your words: status, its time, the heard word it was paired with")
        dbg.line(f"{'time':>8}  {'status':<9} {'yours':<18} heard")
        for r in pairs:
            dbg.line(f"{r['time']:>8}  {r['status']:<9} {r['yours']:<18} {r['heard']}")
        dbg.head("stretches not recognised")
        for ln in describe_report(report, None):
            dbg.line(ln)
        dbg.save()
    if report and (share < 0.9 or full_report):
        gaps = [r for r in report if r["why"].startswith("nothing")]
        info(f"{{head}}your words not recognised{{/}} ({len(report)} stretch(es); times are where they were "
             "placed between recognised words):")
        for ln in describe_report(report, None if full_report else 12):
            print(ln)
        if gaps:
            info(f"  {{note}}{len(gaps)} of them fall where the transcript has no words at all - the transcription "
                 "dropped those parts ('lyrics transcribe --debug' shows why){/}")
    _used_for(len(lines))
    return 0


def line_text_of(w: dict) -> str:
    """A word as typed: its text with its voice codes."""
    return ("{" + w["voice_mark"] + "}" if w.get("voice_mark") else "") + w.get("text", "") + \
        ("{" + w["voice_after"] + "}" if w.get("voice_after") else "")


def _join_text(words: list[dict]) -> str:
    from .voices import join_text
    return join_text(words)


if __name__ == "__main__":
    sys.exit(main())


def _shift(audio: Path, sha: str, delta: str | None, rest: list[str]) -> int:
    """lyrics shift DELTA [@FROM] (0.21.10): every line from FROM on (the one being sung then
    included) moved by DELTA seconds, its words with it."""
    doc = songs.get(sha).get("lyrics")
    if not doc or not doc.get("lines"):
        raise SystemExit(f"no lyrics for {audio.name} - 'lyrics transcribe' or 'lyrics import FILE' first")
    try:
        d = float(str(delta))
    except (TypeError, ValueError):
        raise SystemExit("lyrics shift SECONDS [@FROM] - e.g. 'lyrics shift -0.3 @1:12' (no @: every line)") from None
    if len(rest) == 2 and rest[0] == "from" and re.fullmatch(r"\d+\.\d+", rest[1]):   # one word and the rest
        return _shift_words(audio, sha, doc, d, rest[1])
    t0 = _t(rest[0]) if rest else None
    import copy as _copy
    doc = _copy.deepcopy(doc)
    lines = doc["lines"]
    first = 0 if t0 is None else next((i for i, ln in enumerate(lines) if ln["end"] > t0 + 1e-6), len(lines))
    moved = lines[first:]
    if not moved:
        raise SystemExit(f"no lyric line after {rest[0]}")
    for ln in moved:
        ln["start"], ln["end"] = round(max(0.0, ln["start"] + d), 3), round(max(0.05, ln["end"] + d), 3)
        for w in ln.get("words") or []:
            w["start"], w["end"] = round(max(0.0, w["start"] + d), 3), round(max(0.05, w["end"] + d), 3)
    if first and lines[first - 1]["end"] > lines[first]["start"]:     # the line before ends where this starts
        lines[first - 1]["end"] = lines[first]["start"]
        for w in lines[first - 1].get("words") or []:
            w["end"] = min(w["end"], lines[first]["start"])
    doc["edited"] = True
    songs.update(sha, audio.name, lyrics=doc)
    good(f"{audio.name}: {len(moved)} line(s) from line {first + 1} ('{moved[0]['text'][:30]}') moved {d:+.2f} s"
         " - 'run' again to use them; 'undo' takes it back")
    return 0


def _from_xsq(audio: Path, sha: str, track: str | None) -> int:
    """lyrics from-xsq [TRACK] (0.21.10, phase E): the lyrics of a timing track of the song's .xsq
    - xLights' lyric tracks have phrases, words and phonemes layers; phrases -> lines, words ->
    their words (by time)."""
    rec = songs.get(sha).get("borrowed") or {}
    f = Path(rec.get("xsq", ""))
    if not rec.get("xsq") or not f.is_file():
        raise SystemExit("no .xsq for this song - 'open-xsq Song.xsq' (or 'xsq-borrow Song.xsq') first")
    from ..adapters.xlights import xsq as xsq_mod
    seq = xsq_mod.read(f)
    marks: dict[str, dict[int, list]] = {}
    for e in seq.effects:
        if e.element_type == "timing":
            marks.setdefault(e.element, {}).setdefault(e.layer, []).append((e.start, e.end, (e.label or "").strip()))
    if not marks:
        raise SystemExit(f"{f.name} has no timing tracks")

    def wordy(tr):                                   # how much a track looks like lyrics: labels with letters
        lab = [x for lay in marks[tr].values() for _, _, x in lay if re.search(r"[A-Za-z]{2}", x)]
        return (("lyric" in tr.lower()) * 1000 + len(lab), len(marks[tr]))
    if track:
        tr = next((t for t in marks if t.lower() == track.lower()), None)
        if tr is None:
            raise SystemExit(f"no timing track '{track}' in {f.name} - it has: {', '.join(sorted(marks))}")
    else:
        tr = max(marks, key=wordy)
        if wordy(tr)[0] == 0:
            raise SystemExit(f"no timing track of {f.name} has words in it ({', '.join(sorted(marks))}) - "
                             "name one: 'lyrics from-xsq \"TRACK\"'")
    lay = marks[tr]
    phr = sorted(x for x in lay.get(0, []) if x[2])
    wds = sorted(x for x in lay.get(1, []) if x[2])
    if not phr and wds:                               # only words: lines at the pauses
        phr, cur = [], []
        for w in wds:
            if cur and w[0] - cur[-1][1] > 0.8:
                phr.append((cur[0][0], cur[-1][1], " ".join(x[2] for x in cur)))
                cur = []
            cur.append(w)
        if cur:
            phr.append((cur[0][0], cur[-1][1], " ".join(x[2] for x in cur)))
    if not phr:
        raise SystemExit(f"the track '{tr}' has no labelled marks")
    lines = []
    for a, b, text in phr:
        ln = {"start": round(a, 3), "end": round(b, 3), "text": text}
        inside = [{"start": round(x[0], 3), "end": round(x[1], 3), "text": x[2]} for x in wds
                  if x[0] >= a - 0.02 and x[1] <= b + 0.02]
        if inside:
            ln["words"] = inside
        lines.append(ln)
    old = songs.get(sha).get("lyrics")
    doc = {"lines": lines, "source": f"{f.name} / {tr}", "format": "xsq timing track"}
    songs.update(sha, audio.name, lyrics=doc)
    nw = sum(len(ln.get("words", [])) for ln in lines)
    good(f"{audio.name}: {len(lines)} lyric lines" + (f", {nw} timed words" if nw else "") + f" from the timing "
         f"track '{tr}' of {f.name}" + (" (replacing the lyrics you had - 'undo' brings them back)" if old else ""))
    if not nw:
        info("  the track has no words layer: 'lyrics align' times the words from the singing")
    return 0
