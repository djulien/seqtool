"""Words -> mouth shapes (phonemes) for singing faces (0.19.1).

Each timed word is looked up in a pronouncing dictionary (ARPAbet: 'hello' = HH AH0
L OW1), the sounds are mapped to the 10 mouth shapes (AI, E, etc, FV, L, MBP, O, U,
WQ, rest) and spread over the word's time: vowels get twice a consonant's share,
nothing is shorter than one frame (sounds are merged when a word is too short).

Dictionaries (preferences/faces.json `phonemes.dictionaries`, tried in order):
- "cmudict" (the default): the CMU Pronouncing Dictionary (BSD-style licence),
  downloaded once on first use (asks first) into seqtool-prefs/cache/;
- a path to any file in the same format ('WORD  P1 P2 ...', e.g. xLights' own
  standard_dictionary / user_dictionary from its install, or a file of your own);
- your own pronunciations, checked first: an add-on dictionary in the same format,
  seqtool-prefs/pronunciations.dict (made with instructions the first time it is
  needed; edit it in any editor), or the file given with `--dictionary FILE` on
  lyrics / run / demo / xlights-export - remembered until another `--dictionary`,
  and `--dictionary default` goes back to pronunciations.dict.
Words in none of them are guessed from their spelling, and listed with the guess as
a line to correct and paste into the add-on dictionary.

The ARPAbet -> mouth table (`phonemes.mapping`) is the usual Papagayo-style one and
can be changed like any preference.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..common import config
from ..common.log import info, warn

CMUDICT_FILE = "cmudict.dict"
VOWELS = {"AA", "AE", "AH", "AO", "AW", "AY", "EH", "ER", "EY", "IH", "IY", "OW", "OY", "UH", "UW"}

# spelling fallback: longest match first
SPELL = [("tion", "SH AH N"), ("eigh", "EY"), ("ough", "OW"), ("igh", "AY"), ("tch", "CH"), ("sch", "S K"),
         ("ch", "CH"), ("sh", "SH"), ("th", "TH"), ("ph", "F"), ("wh", "W"), ("ng", "NG"), ("ck", "K"),
         ("qu", "K W"), ("ee", "IY"), ("ea", "IY"), ("oo", "UW"), ("ou", "AW"), ("ow", "OW"), ("oi", "OY"),
         ("oy", "OY"), ("ai", "EY"), ("ay", "EY"), ("au", "AO"), ("aw", "AO"), ("ie", "IY"), ("er", "ER"),
         ("ar", "AA R"), ("or", "AO R"),
         ("a", "AE"), ("b", "B"), ("c", "K"), ("d", "D"), ("e", "EH"), ("f", "F"), ("g", "G"), ("h", "HH"),
         ("i", "IH"), ("j", "JH"), ("k", "K"), ("l", "L"), ("m", "M"), ("n", "N"), ("o", "AA"), ("p", "P"),
         ("q", "K"), ("r", "R"), ("s", "S"), ("t", "T"), ("u", "AH"), ("v", "V"), ("w", "W"), ("x", "K S"),
         ("y", "IY"), ("z", "Z")]


def settings() -> dict:
    return config.load("faces").get("phonemes", {})


def _clean(word: str) -> str:
    return re.sub(r"[^a-z']", "", word.lower().replace("’", "'")).strip("'")


_CACHE: dict[tuple, dict] = {}
_DECLINED: list[bool] = []


def _read(path: Path) -> dict[str, list[str]]:
    """'WORD  P1 P2' or 'word(2) p1 p2 # comment' -> {word: [P1, P2]} (first pronunciation)."""
    key = (str(path), path.stat().st_mtime, path.stat().st_size)
    if key in _CACHE:
        return _CACHE[key]
    out: dict[str, list[str]] = {}
    with open(path, encoding="latin-1") as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if not line or line.startswith(";;;"):
                continue
            parts = line.split()
            w = re.sub(r"\(\d+\)$", "", parts[0]).lower()
            if w not in out and len(parts) > 1:
                out[w] = [p.upper() for p in parts[1:]]      # stress digits kept (lookup drops them)
    _CACHE[key] = out
    return out


def cmudict_path(download: bool = True) -> Path | None:
    f = config.user_dir() / "cache" / CMUDICT_FILE
    if f.exists() and f.stat().st_size > 1000:
        return f
    if not download or _DECLINED:
        return None
    from ..common.deps import confirm_download
    url = settings().get("cmudict_url", "https://raw.githubusercontent.com/cmusphinx/cmudict/master/cmudict.dict")
    if not confirm_download("Singing faces need a pronouncing dictionary: download the CMU Pronouncing Dictionary "
                            "(about 3.5 MB, BSD-style licence) once now?"):
        _DECLINED.append(True)                         # asked once per session
        return None
    import urllib.request
    f.parent.mkdir(parents=True, exist_ok=True)
    try:
        info(f"  downloading {url} ...")
        with urllib.request.urlopen(url, timeout=60) as r:
            data = r.read()
        if len(data) < 100000 or b" " not in data[:2000]:
            raise ValueError("that is not a dictionary file")
        f.write_bytes(data)
        return f
    except Exception as e:  # noqa: BLE001
        warn(f"could not download the dictionary ({e}) - put a copy at {f}, or name another one: "
             "'pref faces.phonemes.dictionaries = [\"/path/to/standard_dictionary\"]'")
        return None


ADDON_FILE = "pronunciations.dict"
ADDON_HEAD = """;;; seqtool: your own pronunciations for singing faces, checked before CMUdict.
;;; One word per line: the word, then its sounds in ARPAbet (as in CMUdict), e.g.
;;;     seqtool  S IY1 K T UW1 L
;;;     fa-la-la  F AA1 L AA1 L AA1
;;; Stress digits are optional. Lines starting with ;;; or # are ignored.
;;; 'lyrics phonemes' lists the words it had to guess, each as a line to correct and paste here.
"""


def addon_path() -> Path:
    """The add-on dictionary: the one given with --dictionary (remembered), else
    seqtool-prefs/pronunciations.dict."""
    given = config.answer("dictionary")
    return Path(given) if given else config.user_dir() / ADDON_FILE


def use_arg(value: str | None) -> None:
    """--dictionary FILE (sticky) | --dictionary default."""
    if value is None:
        return
    if value.strip().lower() in ("default", "reset", "none"):
        config.remember("dictionary", None)
        info(f"  add-on dictionary: back to the default, {config.user_dir() / ADDON_FILE}")
        return
    from ..common.paths import expand
    f = expand(value, "file").expanduser().resolve()
    if not f.exists():
        raise SystemExit(f"--dictionary: {f} not found - give a file of lines 'WORD  SOUND SOUND ...', "
                         "or '--dictionary default'")
    config.remember("dictionary", str(f))
    info(f"  add-on dictionary: {f} (from now on; '--dictionary default' goes back)")


def add_arg(ap) -> None:
    ap.add_argument("--dictionary", metavar="FILE", help="your own pronunciations (an add-on dictionary, checked "
                    "first; remembered - '--dictionary default' goes back to seqtool-prefs/pronunciations.dict)")


class Dictionary:
    def __init__(self, sources: list | None = None, addon: Path | None | bool = None, download: bool = True):
        s = settings()
        self.addon = addon_path() if addon is None else (addon or None)
        self.words: dict[str, list[str]] = {}
        if self.addon is not None:
            if not self.addon.exists() and addon is None and self.addon.parent.exists():
                try:
                    self.addon.write_text(ADDON_HEAD, encoding="utf-8")       # the template, so it can be found
                except OSError:
                    pass
            if self.addon.exists():
                self.words = _read(self.addon)
        self.tables: list[dict] = []
        self.names: list[str] = []
        self.missing: list[str] = []
        for src in (sources if sources is not None else s.get("dictionaries", ["cmudict"])):
            p = cmudict_path(download) if src == "cmudict" else Path(str(src)).expanduser()
            if p is None or not p.exists():
                self.missing.append(str(src))
                continue
            self.tables.append(_read(p))
            self.names.append("CMUdict" if src == "cmudict" else p.name)

    def lookup(self, word: str) -> tuple[list[str], str]:
        """(ARPAbet sounds, where from: 'yours' | dictionary name | 'spelling')."""
        snd, src = self.lookup_stressed(word)
        return [re.sub(r"\d", "", x) for x in snd], src

    def lookup_stressed(self, word: str) -> tuple[list[str], str]:
        """As lookup, with the dictionary's stress digits on the vowels (AH0, EY1)."""
        w = _clean(word)
        if not w:
            return [], "none"
        if w in self.words:
            return self.words[w], "yours"
        for name, t in zip(self.names, self.tables):
            if w in t:
                return t[w], name
        return guess(w), "spelling"


def guess(word: str) -> list[str]:
    out, i = [], 0
    w = re.sub(r"([b-df-hj-np-tv-z])\1", r"\1", word.replace("'", ""))     # a doubled consonant is one sound
    while i < len(w):
        for g, ph in SPELL:
            if w.startswith(g, i):
                if not (g == "e" and i == len(w) - 1 and i > 1):        # a silent final e
                    out += ph.split()
                i += len(g)
                break
        else:
            i += 1
    return out


def mouths(sounds: list[str], mapping: dict | None = None) -> list[tuple[str, bool]]:
    """ARPAbet -> [(mouth, is_vowel)], neighbours with the same mouth merged."""
    mp = mapping if mapping is not None else settings().get("mapping", {})
    out: list[tuple[str, bool]] = []
    for snd in sounds:
        m = mp.get(snd, "etc")
        v = snd in VOWELS
        if out and out[-1][0] == m:
            out[-1] = (m, out[-1][1] or v)
        else:
            out.append((m, v))
    return out


def for_words(words: list[dict], dictionary: Dictionary, frame: float = 0.05,
              mapping: dict | None = None) -> tuple[list[tuple[float, float, str]], dict]:
    """Timed words -> timed mouth shapes [(start, end, mouth)], plus a report
    {total, from: {source: n}, guessed: [words]}."""
    marks: list[tuple[float, float, str]] = []
    rep: dict = {"total": 0, "from": {}, "guessed": []}
    for w in words:
        sounds, src = dictionary.lookup(w.get("text", ""))
        if not sounds:
            continue
        rep["total"] += 1
        rep["from"][src] = rep["from"].get(src, 0) + 1
        if src == "spelling" and _clean(w["text"]) not in rep["guessed"]:
            rep["guessed"].append(_clean(w["text"]))
        if w.get("sounds"):                          # each sound already timed (from phrase times, 0.19.7)
            mp = mapping if mapping is not None else settings().get("mapping", {})
            row: list[list] = []
            # 0.24.23: the sounds were timed when the word was; it may have been moved or stretched
            # since (the magnifier, 'lyrics time') - they are fitted to the word as it is now
            s0, s1 = float(w["sounds"][0][1]), float(w["sounds"][-1][2])
            a, b = float(w["start"]), float(w["end"])
            k_ = (b - a) / (s1 - s0) if s1 - s0 > 1e-6 else 0.0
            fit = (lambda v: a + (float(v) - s0) * k_) if k_ > 0 else None
            for snd, t0, t1 in w["sounds"]:
                if fit is None:
                    t0, t1 = a, b
                else:
                    t0, t1 = fit(t0), fit(t1)
                m = mp.get(snd.rstrip("012"), mp.get(snd, "etc"))
                if row and row[-1][2] == m:
                    row[-1][1] = t1
                else:
                    row.append([float(t0), float(t1), m])
            k = 0
            while len(row) > 1 and k < len(row):         # nothing shorter than a frame: into its neighbour
                if row[k][1] - row[k][0] < frame - 1e-9:
                    j = k - 1 if k > 0 and (k == len(row) - 1 or row[k - 1][1] - row[k - 1][0] <= row[k + 1][1] - row[k + 1][0]) else k + 1
                    if j < k:
                        row[j][1] = row[k][1]
                    else:
                        row[j][0] = row[k][0]
                    row.pop(k)
                    k = max(0, k - 1)
                    continue
                k += 1
            marks += [(round(x, 3), round(y, 3), m) for x, y, m in row]
            continue
        ms = mouths(sounds, mapping)
        a, b = float(w["start"]), float(w["end"])
        n_max = max(1, int(round((b - a) / frame)))
        while len(ms) > n_max:                       # too short for every sound: drop the shortest (consonants)
            k = next((i for i, (_, v) in enumerate(ms) if not v), len(ms) - 1)
            ms.pop(k)
        weights = [2.0 if v else 1.0 for _, v in ms]
        tot = sum(weights)
        t = a
        for (m, _), wt in zip(ms, weights):
            e = t + (b - a) * wt / tot
            marks.append((round(t, 3), round(e, 3), m))
            t = e
    return marks, rep


def describe(rep: dict, dictionary: Dictionary) -> list[str]:
    L = []
    if dictionary.missing:
        L.append("{warn}dictionary not available: " + ", ".join(dictionary.missing)
                 + "{/} - 'pref faces.phonemes.dictionaries' lists the ones to use")
    if rep["total"]:
        src = ", ".join(f"{n} from {'your add-on' if k == 'yours' else 'the spelling (guessed)' if k == 'spelling' else k}"
                        for k, n in sorted(rep["from"].items(), key=lambda kv: -kv[1]))
        L.append(f"phonemes for {rep['total']} sung words ({src})")
    if rep["guessed"]:
        g = rep["guessed"]
        where = dictionary.addon or addon_path()
        L.append(f"{{warn}}{len(g)} different word(s) not in any dictionary, guessed from the spelling:{{/}} "
                 + ", ".join(g[:12]) + (" ..." if len(g) > 12 else ""))
        L.append(f"  to fix them, correct the sounds and add the line(s) to {where} {{note}}(ARPAbet, as in "
                 f"CMUdict){{/}}:")
        L += ["{copy}" + "\n".join(f"{w}  {' '.join(guess(w))}" for w in g[:40]) + "{/}"]
    return L
