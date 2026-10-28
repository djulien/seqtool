"""Lyrics from the singing: transcription with Whisper (faster-whisper, MIT licence) and
alignment of lyrics you have as plain text to the transcribed words.

  transcribe(audio)       -> {"lines": [{start, end, text, words: [{start, end, text}]}], ...}
                             run on the Demucs vocal stem when there is one (far fewer
                             mistakes than on the whole mix), else on the song
  align(texts, words)     -> lines of your text, timed from the transcribed words: the two
                             word sequences are matched (difflib); words the transcription
                             missed get times spread between their matched neighbours

The transcript is kept per song (songs.json "transcript"), so aligning again or
importing corrected text doesn't transcribe again. faster-whisper downloads its model
(e.g. 'small', about 480 MB) the first time.
"""
from __future__ import annotations

import difflib
import re
from pathlib import Path

from ..common.log import info, warn

MODELS = ("tiny", "base", "small", "medium", "large-v3")
DEFAULT_MODEL = "small"
SIZES = {"tiny": "75 MB", "base": "145 MB", "small": "480 MB", "medium": "1.5 GB", "large-v1": "3 GB",
         "large-v2": "3 GB", "large-v3": "3 GB", "large": "3 GB", "distil-large-v3": "1.5 GB",
         "large-v3-turbo": "1.6 GB", "turbo": "1.6 GB"}


def _names(fw) -> list[str]:
    try:
        return list(fw.available_models())
    except Exception:  # noqa: BLE001
        return list(MODELS)


def _cached(model: str) -> str | None:
    """The local folder of a downloaded model, or None."""
    try:
        from faster_whisper.utils import download_model
        return download_model(model, local_files_only=True)
    except Exception:  # noqa: BLE001
        return None


def models_table(fw) -> list[str]:
    """Every model name, with its size and whether it is downloaded."""
    out = []
    for m in _names(fw):
        if m.endswith(".en") and m[:-3] in SIZES:
            continue                                   # English-only twins: listed with their base name
        got = _cached(m)
        out.append(f"  {m:<16} {SIZES.get(m, ''):>7}  " + ("{ok}downloaded{/}" if got else "{dim}not downloaded{/}")
                   + ("  (the default)" if m == DEFAULT_MODEL else ""))
    return out


def model_path(fw, model: str) -> str:
    """The downloaded model, after offering to download it."""
    names = _names(fw)
    if model not in names:
        have = [m for m in names if _cached(m)]
        raise SystemExit(f"there is no Whisper model '{model}' - choose one of: {', '.join(m for m in names if not m.endswith('.en'))}"
                         + (f" (downloaded: {', '.join(have)})" if have else "")
                         + "; e.g. 'lyrics transcribe --model small'; 'lyrics models' lists them")
    got = _cached(model)
    if got:
        return got
    from ..common import deps
    size = SIZES.get(model, "")
    if not deps.confirm_download(f"Whisper model '{model}'{f' (about {size})' if size else ''} isn't downloaded "
                                 "yet. Download it now (once; it is kept)?"):
        have = [m for m in names if _cached(m)]
        raise SystemExit(f"not transcribed: model '{model}' isn't downloaded"
                         + (f" - downloaded already: {', '.join(have)} (e.g. 'lyrics transcribe --model {have[0]}')"
                            if have else " - 'lyrics transcribe' asks again"))
    from faster_whisper.utils import download_model
    info(f"downloading Whisper '{model}' ...")
    return download_model(model)


def norm_word(w: str) -> str:
    """For comparing words: lower case, no punctuation, no apostrophes of any kind (a lyric
    site's ' who’s ' and Whisper's ' who's ' are the same word; 0.19.4)."""
    return re.sub(r"[^a-z0-9]", "", w.lower())


def source_for(audio: Path) -> tuple[Path, str]:
    """(file to transcribe, what it is): the vocal stem when it was made."""
    from .stems import stem_path
    st = stem_path(audio)
    if st.is_file():
        return st, "the vocal stem"
    return audio, "the whole mix (no vocal stem: 'run --stems' makes one, and transcription is better on it)"


# memory a model needs while it transcribes on the CPU (int8), in GB, model and audio included
MEMORY_GB = {"tiny": 0.6, "base": 0.8, "small": 1.3, "medium": 2.3, "large-v1": 3.8, "large-v2": 3.8,
             "large-v3": 3.8, "large": 3.8, "distil-large-v3": 2.3, "large-v3-turbo": 2.4, "turbo": 2.4}


def _gpu() -> bool:
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:  # noqa: BLE001
        return False


def check_memory(model: str, names: list[str]) -> None:
    """Ask before a model that needs more memory than is free (a smaller one is named)."""
    from ..common import deps
    from ..common.shellcmds import fmt_bytes, system_memory
    need = MEMORY_GB.get(model.removesuffix(".en"))
    total, free = system_memory()
    if free is not None:
        info(f"memory: {fmt_bytes(free)} free" + (f" of {fmt_bytes(total)}" if total else "")
             + (f"; '{model}' needs about {need:g} GB" if need else ""))
    if need is None or free is None or free >= need * 1024 ** 3:
        return
    fits = [m for m in names if MEMORY_GB.get(m, 99) * 1024 ** 3 <= free and not m.endswith(".en")]
    best = max(fits, key=lambda m: MEMORY_GB[m]) if fits else None
    q = (f"Whisper '{model}' needs about {need:g} GB of memory, but only {fmt_bytes(free)} is free"
         + (f" (of {fmt_bytes(total)})" if total else "") + " - it may be very slow or fail"
         + (f"; '{best}' fits ('lyrics transcribe --model {best}')" if best else "; close other programs first")
         + ". Use it anyway?")
    if not deps.ask_yes_no(q, default=False):
        raise SystemExit("not transcribed" + (f" - try 'lyrics transcribe --model {best}'" if best else
                                              " - close other programs, then try again"))


def _progress(total: float, label: str = "Whisper"):
    """A function(seconds done) that shows how far transcription has got: on a terminal
    one line rewritten in place, elsewhere (the GUI, a log) a line every 10%."""
    import sys
    import time
    t0, shown = time.monotonic(), [-10]
    from ..common.log import rewrites
    tty = rewrites(sys.stderr)

    def dur(sec):
        return f"{sec:.0f} s" if sec < 90 else f"{sec / 60:.1f} min"

    def show(done: float, end: bool = False):
        p = 100 if end else int(100 * min(1.0, done / total)) if total else 0
        if not end and not tty and p < shown[0] + 10:
            return
        shown[0] = p
        el = time.monotonic() - t0
        eta = f", about {dur(el * (100 - p) / p)} to go" if 3 <= p < 100 and el > 5 else ""
        txt = f"  {label}: {p:3d}%  ({dur(el)} so far{eta})"
        from ..common.log import progress, progress_end
        if end:
            progress_end()
            info(txt)
        else:
            progress(txt, level="info")
    return show


def _seg_row(s, offset: float = 0.0, tag: str = "") -> dict:
    g = lambda k: getattr(s, k, None)                 # noqa: E731
    return {"start": round(float(s.start) + offset, 2), "end": round(float(s.end) + offset, 2), "tag": tag,
            "avg_logprob": g("avg_logprob"), "no_speech_prob": g("no_speech_prob"),
            "compression_ratio": g("compression_ratio"), "temperature": g("temperature"),
            "text": " ".join(str(g("text") or "").split())}


def _lines_of(segs, offset: float, show=None, log: list | None = None, tag: str = "") -> list[dict]:
    lines = []
    for s in segs:                                   # the work happens while the segments are read
        if show:
            show(float(s.end) + offset)
        if log is not None:
            log.append(_seg_row(s, offset, tag))
        words = [{"start": round(float(w.start) + offset, 3), "end": round(float(w.end) + offset, 3),
                  "text": w.word.strip()} for w in (s.words or []) if w.word.strip()]
        text = " ".join(s.text.split())
        if not text:
            continue
        if tag and (getattr(s, "no_speech_prob", 0) or 0) > 0.8 and (getattr(s, "avg_logprob", 0) or 0) < -1.0:
            continue                                 # a refill pass hearing nothing: Whisper's usual filler
        lines.append({"start": round(float(s.start) + offset, 3), "end": round(float(s.end) + offset, 3),
                      "text": text, **({"words": words} if words else {}), **({"refilled": True} if tag else {})})
    return lines


# words a sung phrase doesn't end on: left at the end of a piece, they belong to the next one
DANGLING = {"i", "the", "a", "an", "to", "and", "of", "my", "your", "our", "in", "on", "at", "for", "with",
            "we", "you", "he", "she", "they", "is", "are", "gonna", "do", "let's", "lets"}


def split_lines(lines: list[dict], gap: float = 1.2) -> list[dict]:
    """A Whisper segment can run over a long pause (0:17.8-0:39.3 holding two sung lines
    20 s apart, with a refilled passage in between): split lines where their words pause
    for more than `gap` seconds, so lines don't overlap and the phrase layer stays in
    order (0.19.5)."""
    out = []
    for ln in lines:
        ws = ln.get("words") or []
        if len(ws) < 2:
            out.append(ln)
            continue
        parts, part = [], [ws[0]]
        for w in ws[1:]:
            if float(w["start"]) - float(part[-1]["end"]) > gap:
                parts.append(part)
                part = []
            part.append(w)
        parts.append(part)
        for i in range(len(parts) - 1):              # 'all night I' + 'hear some more': a phrase doesn't end
            while parts[i] and norm_word(parts[i][-1]["text"]) in DANGLING:   # on 'I' / 'the' / 'to' (0.19.7)
                w = parts[i].pop()
                nxt = float(parts[i + 1][0]["start"])
                parts[i + 1].insert(0, {**w, "start": round(max(float(w["start"]), nxt - 0.3), 3), "end": round(nxt, 3)})
        parts = [x for x in parts if x]
        if len(parts) == 1:
            out.append({**ln, "words": parts[0]})
            continue
        for part in parts:
            out.append({**ln, "start": part[0]["start"], "end": part[-1]["end"],
                        "text": " ".join(x["text"] for x in part), "words": part})
    out.sort(key=lambda x: x["start"])
    return out


def unstretch(lines: list[dict]) -> int:
    """Whisper sometimes stretches one word over a long stretch of music: the first word
    of 'That melody ...' starting at 1:48 when it is sung at 2:19, or a word in the
    middle running over the 13 s before the next phrase. Such a word is shortened to a
    usual word's length - at its start if it opens the line (Whisper starts it too early)
    or begins a phrase (a capital), else at its end - and the line follows its words
    (0.19.6). Returns how many words were shortened."""
    durs = sorted(float(w["end"]) - float(w["start"]) for ln in lines for w in (ln.get("words") or [])
                  if float(w["end"]) > float(w["start"]))
    if not durs:
        return 0
    med = durs[len(durs) // 2]
    limit, usual = max(3.0, 6 * med), min(0.8, max(0.25, med))   # a held note can last 2-3 s
    n = 0
    for ln in lines:
        ws = ln.get("words") or []
        for i, w in enumerate(ws):
            if float(w["end"]) - float(w["start"]) <= limit:
                continue
            n += 1
            last = i == len(ws) - 1
            if not last and (i == 0 or w["text"][:1].isupper()):
                w["start"] = round(float(w["end"]) - usual, 3)
            else:
                w["end"] = round(float(w["start"]) + usual, 3)
        if ws:
            ln["start"], ln["end"] = ws[0]["start"], ws[-1]["end"]
    return n


def untangle(lines: list[dict]) -> list[dict]:
    """Lines in time order that never overlap (0.19.6): the words of every line - the
    first pass's and the refilled ones - are put in time order, and a line holds a run of
    its own words; where a refilled line sits inside a first-pass one, that one is cut in
    two round it. The same word heard by both passes at the same moment is kept once."""
    flat, plain = [], []
    for k, ln in enumerate(lines):
        ws = ln.get("words") or []
        if not ws:
            plain.append(ln)
        flat += [(float(w["start"]), k, w) for w in ws]
    flat.sort(key=lambda x: (x[0], x[1]))
    kept = []
    for t, k, w in flat:
        if kept and kept[-1][1] != k and abs(kept[-1][0] - t) < 0.6 and _key(kept[-1][2]["text"]) == _key(w["text"]):
            continue                                 # both passes heard it
        kept.append((t, k, w))
    out, run, rk = [], [], None

    def close():
        if run:
            ln = lines[rk]
            whole = len(run) == len(ln.get("words") or [])
            out.append({**ln, "start": run[0]["start"], "end": run[-1]["end"],
                        "text": ln["text"] if whole else " ".join(x["text"] for x in run), "words": list(run)})
    for i, (t, k, w) in enumerate(kept):
        if k != rk:
            close()
            run, rk = [], k
        if i + 1 < len(kept) and float(w["end"]) > kept[i + 1][0]:
            w = {**w, "end": round(max(float(w["start"]), kept[i + 1][0]), 3)}
        run.append(w)
    close()
    out += plain
    out.sort(key=lambda x: float(x["start"]))
    return out


def unheard(lines: list[dict], passages: list[tuple[float, float]], min_len: float = 1.5) -> list[tuple[float, float]]:
    """Sung passages (from the vocal stem) with no transcribed word in them."""
    starts = [float(w["start"]) for ln in lines for w in (ln.get("words") or [{"start": ln["start"]}])]
    return [(a, b) for a, b in passages if b - a >= min_len and not any(a <= t < b for t in starts)]


def transcribe(audio: Path, model: str = DEFAULT_MODEL, language: str | None = None,
               passages: list[tuple[float, float]] | None = None, refill: bool = True, vad: bool = True,
               log: list | None = None) -> dict:
    """passages: where the vocal stem has singing; sung passages the first pass leaves
    without words are transcribed again on their own, without the voice filter (0.19.4).
    log: gets one row per Whisper segment (start, end, avg_logprob, no_speech_prob,
    compression_ratio, temperature, text) and the passages left without words."""
    from ..common import deps
    fw = deps.need("faster_whisper", purpose="lyrics transcription", pip="faster-whisper", required=True)
    gpu = _gpu()
    if not gpu:
        check_memory(model, _names(fw))
    else:
        info("device: GPU (CUDA)")
    path = model_path(fw, model)
    src, what = source_for(audio)
    info(f"transcribing {what} with Whisper '{model}' on the {'GPU' if gpu else 'CPU'} (loading the model ...)")
    wm = fw.WhisperModel(path, device="cuda" if gpu else "cpu", compute_type="float16" if gpu else "int8")
    info("  finding the singing and the language ..." if language is None else "  finding the singing ...")
    segs, meta = wm.transcribe(str(src), word_timestamps=True, language=language,
                               condition_on_previous_text=False, vad_filter=vad)
    if language is None and getattr(meta, "language", None):
        pr = getattr(meta, "language_probability", None)
        info(f"  language: {meta.language}" + (f" ({pr:.0%} sure" if pr else " (") + "; --language to set it)")
    lang = getattr(meta, "language", None) or language
    show = _progress(float(getattr(meta, "duration", 0) or 0))
    show(0.0)
    lines = _lines_of(segs, 0.0, show, log)
    show(0.0, end=True)
    fixed = unstretch(lines)                         # before looking for passages without words: a stretched
    lines = split_lines(lines)                       # word hides the passage it runs over
    if log is not None and fixed:
        log.append({"note": f"{fixed} word(s) Whisper stretched over long stretches of music were shortened"})
    gaps = unheard(lines, passages or [])
    if log is not None:
        log.append({"gaps_after_first_pass": [[round(a, 2), round(b, 2)] for a, b in gaps]})
    if gaps:
        tot = sum(b - a for a, b in gaps)
        info(f"  {len(gaps)} sung passage(s) got no words ({tot:.0f} s): "
             + ", ".join(f"{_clock(a)}-{_clock(b)}" for a, b in gaps[:8]) + (" ..." if len(gaps) > 8 else ""))
    if gaps and refill:
        dec = getattr(fw, "decode_audio", None)
        if dec is None:
            try:
                from faster_whisper.audio import decode_audio as dec
            except ImportError:
                dec = None
        if dec is None:
            warn("  this faster-whisper can't cut the audio, so those passages stay empty")
        else:
            info("  transcribing those passages again, each on its own and without the voice filter ...")
            pcm = dec(str(src), sampling_rate=16000)
            added, done = 0, 0.0
            show2 = _progress(sum(b - a + 1.0 for a, b in gaps), "Whisper, again")
            show2(0.0)
            for a, b in gaps:
                a0, b0 = max(0.0, a - 0.5), b + 0.5
                piece = pcm[int(a0 * 16000):int(b0 * 16000)]
                segs2, _ = wm.transcribe(piece, word_timestamps=True, language=lang,
                                         condition_on_previous_text=False, vad_filter=False)
                got = _lines_of(segs2, a0, lambda t, d=done, a0=a0: show2(d + min(t - a0, b0 - a0)), log, "refill")
                done += b0 - a0
                show2(done)
                unstretch(got)
                added += sum(len(ln.get("words", [])) for ln in got)
                lines += got
            show2(done, end=True)
            lines = untangle(lines)
            left = unheard(lines, gaps)
            info(f"  {{ok}}+{added} words{{/}} from them" + (f"; {len(left)} passage(s) still without words" if left else ""))
            if log is not None:
                log.append({"gaps_after_refill": [[round(a, 2), round(b, 2)] for a, b in left]})
    lines = split_lines(untangle(lines))
    if log is not None:
        log.append({"final": lines})
    return {"format": "transcribed", "source": f"whisper {model} on {src.name}", "model": model,
            "language": lang, "lines": lines}


def _clock(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:04.1f}"


def write_log(path: Path, log: list, header: dict) -> None:
    out = ["Whisper log (seqtool lyrics transcribe --debug)"] + [f"{k}: {v}" for k, v in header.items()]
    out += ["", "Low avg_logprob (< -1) means unsure; high no_speech_prob (> 0.6) means Whisper took it for no "
            "speech - with the voice filter (VAD) on, singing it doesn't take for a voice is cut before Whisper "
            "even hears it, which shows as a sung passage with no segment at all.", "",
            f"{'start':>8} {'end':>8}  {'logprob':>7} {'nospeech':>8} {'compr':>5} {'temp':>4}  text"]
    for r in log:
        if "final" in r:                             # the lines as kept, with each word's time
            out += ["", "lines as kept (after shortening stretched words, splitting at pauses and putting the "
                        "refilled lines in place; word times in brackets):", ""]
            for ln in r["final"]:
                ws = ln.get("words") or []
                out.append(f"{_clock(float(ln['start'])):>8} {_clock(float(ln['end'])):>8}  "
                           + ("[refill] " if ln.get("refilled") else "")
                           + (" ".join(f"{w['text']}({float(w['start']):.1f})" for w in ws) if ws else ln["text"]))
            continue
        if "note" in r:
            out += ["", r["note"]]
            continue
        if "gaps_after_first_pass" in r or "gaps_after_refill" in r:
            k = next(iter(r))
            out.append("")
            out.append(k.replace("_", " ") + ": " + (", ".join(f"{_clock(a)}-{_clock(b)}" for a, b in r[k]) or "none"))
            out.append("")
            continue
        f = lambda v, d: "-" if v is None else f"{v:.{d}f}"   # noqa: E731
        out.append(f"{_clock(r['start']):>8} {_clock(r['end']):>8}  {f(r['avg_logprob'], 2):>7} "
                   f"{f(r['no_speech_prob'], 2):>8} {f(r['compression_ratio'], 2):>5} {f(r['temperature'], 1):>4}  "
                   + (f"[{r['tag']}] " if r["tag"] else "") + r["text"])
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def all_words(doc: dict) -> list[dict]:
    """Every word with its time; lines without word times get them spread evenly."""
    out = []
    for ln in doc.get("lines", []):
        if ln.get("words"):
            out += [dict(w) for w in ln["words"]]
            continue
        toks = ln["text"].split()
        if not toks:
            continue
        a, b = float(ln["start"]), float(ln.get("end", ln["start"] + 2.0))
        step = (b - a) / len(toks)
        out += [{"start": round(a + k * step, 3), "end": round(a + (k + 1) * step, 3), "text": t}
                for k, t in enumerate(toks)]
    return out


SAME_WORD = {"allright": "alright", "ya": "yeah", "yea": "yeah", "yah": "yeah", "okay": "ok", "til": "until", "cause": "because",
             "cuz": "because", "em": "them", "n": "and", "an": "and"}


def tokens(text: str) -> list[str]:
    """Words of a lyric line; hyphenated words count as separate words, as Whisper writes them,
    and 'all right' is one word (as 'alright')."""
    out = [t for t in re.split(r"[\s\u2010-\u2015-]+", text) if norm_word(t)]
    i = 0
    while i < len(out) - 1:
        if norm_word(out[i]) == "all" and norm_word(out[i + 1]) == "right":
            out[i:i + 2] = [out[i] + " " + out[i + 1]]
        i += 1
    return out


def _key(w: str) -> str:
    n = norm_word(w)
    return SAME_WORD.get(n, n)


def _same(x: str, y: str) -> int:
    """2 = the same word, 1 = nearly (flappin / flapping), 0 = different."""
    if x == y:
        return 2
    if min(len(x), len(y)) >= 4 and difflib.SequenceMatcher(a=x, b=y).ratio() >= 0.8:
        return 1
    return 0


def _global_align(a: list[str], b: list[str], ta: list[float | None] | None = None,
                  tb: list[float] | None = None, tol: float = 8.0) -> list[tuple[int | None, int | None, int]]:
    """Needleman-Wunsch over words: [(i in a | None, j in b | None, 2/1 match, 0 misheard)].
    Unlike a greedy longest-match, repeated choruses can't pull the alignment out of order.
    ta / tb: when your lyrics are timed (LRC), a word only matches a heard word within tol
    seconds of where the file puts it - so 'sing it all night long' sung six times pairs up
    with the right one (0.19.5)."""
    n, m = len(a), len(b)
    def same(x, y, i, j):                                 # the time-aware version
        if ta is not None and ta[i] is not None and abs(ta[i] - tb[j]) > tol:
            return 0
        return _same(x, y)
    GAP, SUB = -1, -1
    score = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        score[i][0] = i * GAP
    for j in range(1, m + 1):
        score[0][j] = j * GAP
    for i in range(1, n + 1):
        ai, row, prev = a[i - 1], score[i], score[i - 1]
        for j in range(1, m + 1):
            s = same(ai, b[j - 1], i - 1, j - 1)
            row[j] = max(prev[j - 1] + (s if s else SUB), prev[j] + GAP, row[j - 1] + GAP)
    out = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0:
            s = same(a[i - 1], b[j - 1], i - 1, j - 1)
            if score[i][j] == score[i - 1][j - 1] + (s if s else SUB):
                out.append((i - 1, j - 1, s))
                i, j = i - 1, j - 1
                continue
        if i > 0 and score[i][j] == score[i - 1][j] + GAP:
            out.append((i - 1, None, 0))
            i -= 1
        else:
            out.append((None, j - 1, 0))
            j -= 1
    return out[::-1]


def align(texts: list[str], words: list[dict], report: list | None = None,
          line_starts: list[float | None] | None = None, pairs: list | None = None,
          file_times: bool = False, about: dict | None = None) -> tuple[list[dict], float]:
    """Your lyric lines timed from transcribed words. Returns (lines, share of your
    words the transcription matched). report (a list) gets the stretches of your words
    that were not matched, with what was heard there (0.19.4).
    line_starts (timed lyrics, LRC): where the file puts each line - a word only pairs
    with a heard word near there, and an unrecognised first word starts there; with
    file_times every line starts exactly where the file says and only the words heard
    inside the line keep their heard times (0.19.6). about (a dict) gets 'offset': how
    far the file's times are from the singing, if they are consistently off."""
    ref = []                                         # (line index, word)
    for i, t in enumerate(texts):
        ref += [(i, w) for w in tokens(t)]
    words = [w for w in words if norm_word(w["text"])]
    merged = []                                      # Whisper's 'All right' as one word, as on your side
    for w in words:
        if merged and norm_word(merged[-1]["text"]) == "all" and norm_word(w["text"]) == "right":
            merged[-1] = {**merged[-1], "end": w["end"], "text": merged[-1]["text"] + " " + w["text"]}
        else:
            merged.append(w)
    words = merged
    a = [_key(w) for _, w in ref]
    b = [_key(w["text"]) for w in words]
    ta = tb = None
    if line_starts:                                  # where the file puts each of your words (LRC)
        ta = []
        for k, (li, _) in enumerate(ref):
            t0 = line_starts[li] if li < len(line_starts) else None
            nxt = next((line_starts[x] for x in range(li + 1, len(line_starts)) if line_starts[x] is not None), None)
            n_in = sum(1 for x in ref if x[0] == li)
            pos = sum(1 for x in ref[:k] if x[0] == li)
            ta.append(None if t0 is None else t0 + ((nxt - t0) if nxt else 2.0) * pos / max(1, n_in))
        tb = [float(w["start"]) for w in words]
    times: list[list[float] | None] = [None] * len(ref)
    status = ["missing"] * len(ref)                  # matched / misheard / missing
    heard: list[int | None] = [None] * len(ref)
    def n_ok(pth):
        return sum(1 for x in pth if x[0] is not None and x[1] is not None and x[2])
    if ta is not None:
        plain = _global_align(a, b)
        d = sorted(tb[j] - ta[i] for i, j, ok in plain if i is not None and j is not None and ok and ta[i] is not None)
        off = d[len(d) // 2] if d else 0.0           # the file a little early or late all through (another
        if abs(off) >= 1.0:                          # edit of the song, an intro cut): shift it first (0.19.6)
            ta = [None if t is None else t + off for t in ta]
            line_starts = [None if t is None else t + off for t in line_starts]
            if about is not None:
                about["offset"] = round(off, 2)
        path = _global_align(a, b, ta, tb)
        if n_ok(plain) > 1.15 * n_ok(path):          # the time-aware pairing missing much: Whisper's times are off
            path = plain
    else:
        path = _global_align(a, b)
    for ia, jb, s in path:
        if ia is None or jb is None:
            continue
        w = words[jb]
        times[ia] = [float(w["start"]), float(w["end"])]
        status[ia] = "matched" if s else "misheard"
        heard[ia] = jb
    matched = sum(1 for k in range(len(a)) if status[k] == "matched")
    if line_starts:                                  # timed lyrics (LRC): an unmatched first word of a line
        firsts = {}                                  # starts where the file says the line starts (0.19.5)
        for k, (li, _) in enumerate(ref):
            firsts.setdefault(li, k)
        for li, k in firsts.items():
            t = line_starts[li] if li < len(line_starts) else None
            if t is not None and status[k] != "matched":
                times[k] = [float(t), float(t) + 0.3]
                status[k] = "anchored"
    known = [k for k, st in enumerate(status) if st in ("matched", "anchored")]
    if not matched:
        return [], 0.0
    if file_times and line_starts:                   # the file's line times, exactly: heard times only inside the line
        last_end = max(float(w["end"]) for w in words) if words else 0.0
        for li in range(len(texts)):
            ks = [k for k, (x, _) in enumerate(ref) if x == li]
            t0 = line_starts[li] if li < len(line_starts) else None
            if not ks or t0 is None:
                continue
            t1 = next((line_starts[x] for x in range(li + 1, len(line_starts)) if line_starts[x] is not None), None)
            if t1 is None:
                t1 = max(t0 + 0.4 * len(ks), last_end)
            inside = [k for k in ks if status[k] == "matched" and t0 <= times[k][0] < t1]
            for k in ks:
                if k not in inside:
                    times[k] = None
                    if status[k] == "matched":
                        status[k] = "misheard"
            anchors = [(ks[0] - 1, t0)] + [(k, times[k][0]) for k in inside] + [(ks[-1] + 1, t1)]
            if not inside or inside[0] != ks[0]:
                times[ks[0]] = [t0, t0 + 0.25]
                anchors = [(ks[0], t0)] + anchors[1:]
            for (ka, ta_), (kb, tb_) in zip(anchors, anchors[1:]):
                step = (tb_ - ta_) / max(1, kb - ka)
                for k in range(ka + 1, kb):
                    if times[k] is None:
                        times[k] = [ta_ + step * (k - ka), ta_ + step * (k - ka + 1)]
        known = list(range(len(ref)))
        matched = sum(1 for k in range(len(a)) if status[k] == "matched")
    for k in range(len(times)):                      # spread the unmatched between matched neighbours
        if times[k]:
            continue
        lo = max((j for j in known if j < k), default=None)
        hi = min((j for j in known if j > k), default=None)
        if lo is None:
            t0 = times[hi][0] - 0.3 * (hi - k)
            times[k] = [t0, t0 + 0.25]
        elif hi is None:
            t0 = times[lo][1] + 0.3 * (k - lo - 1)
            times[k] = [t0, t0 + 0.25]
        else:
            span = (times[hi][0] - times[lo][1]) / (hi - lo)
            t0 = times[lo][1] + span * (k - lo - 1)
            times[k] = [t0, t0 + span]
    from .lyric_structure import FILLERS
    filler = [x in FILLERS for x in a]               # whoo, ha, oh ...: often not transcribed - not counted
    if report is not None:                           # stretches of your words that were not recognised
        k = 0
        while k < len(ref):
            if status[k] == "matched" or filler[k]:
                k += 1
                continue
            e = k
            while e + 1 < len(ref) and status[e + 1] != "matched":
                e += 1
            while e > k and filler[e]:
                e -= 1
            lo = max((j for j in known if j < k), default=None)
            hi = min((j for j in known if j > e), default=None)
            t0 = times[lo][1] if lo is not None else 0.0
            t1 = times[hi][0] if hi is not None else (float(words[-1]["end"]) if words else t0)
            got = [w["text"] for w in words if t0 - 0.01 <= float(w["start"]) < t1 + 0.01
                   and (lo is None or float(w["start"]) >= times[lo][1] - 0.01)]
            report.append({"start": round(t0, 2), "end": round(t1, 2), "line": texts[ref[k][0]],
                           "yours": [ref[x][1] for x in range(k, e + 1)], "heard": got,
                           "why": "nothing was transcribed there" if not got else
                           "heard differently" if any(status[x] == "misheard" for x in range(k, e + 1))
                           else "not heard (the transcript skips them)"})
            k = e + 1
    lines = []
    for i, t in enumerate(texts):
        ks = [k for k, (li, _) in enumerate(ref) if li == i]
        if not ks:
            continue
        ws = [{"start": round(max(0.0, times[k][0]), 3), "end": round(max(0.0, times[k][1]), 3), "text": ref[k][1]}
              for k in ks]
        lines.append({"start": ws[0]["start"], "end": ws[-1]["end"], "text": " ".join(t.split()), "words": ws})
    if pairs is not None:                            # --debug: every word and what it was paired with
        for k, (li, w) in enumerate(ref):
            pairs.append({"time": f"{times[k][0]:.2f}", "status": status[k] + (" (filler)" if filler[k] else ""),
                          "yours": w, "heard": words[heard[k]]["text"] if heard[k] is not None else "-"})
    counted = [k for k in range(len(a)) if a[k] and not filler[k]]
    return lines, sum(1 for k in counted if status[k] == "matched") / max(1, len(counted))


def describe_report(report: list, limit: int | None = 12) -> list[str]:
    def clock(t):
        return f"{int(t // 60)}:{t % 60:04.1f}"
    L = []
    for r in report[:limit] if limit else report:
        L.append(f"  {clock(r['start'])}-{clock(r['end'])}  {{b}}{' '.join(r['yours'])}{{/}}  - {r['why']}"
                 + (f": heard '{' '.join(r['heard'][:16])}'" if r["heard"] else ""))
    if limit and len(report) > limit:
        L.append(f"  ... and {len(report) - limit} more ('lyrics align FILE --report' lists them all)")
    return L


def plain_lines(text: str) -> list[str]:
    """Lyric lines from plain text: blank lines and [Chorus]-style headings dropped."""
    out = []
    for raw in text.splitlines():
        s = raw.strip()
        if not s or re.fullmatch(r"[\[(].*[\])]:?", s) or re.fullmatch(r"(?i)(verse|chorus|bridge|intro|outro)\b.*:", s):
            continue
        out.append(s)
    return out
