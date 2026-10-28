"""Optional stems via Demucs (ported from lyric-track.py run_demucs).

0.22.0: all four htdemucs stems - vocals, drums, bass, other - kept in the song's
results folder, <song>-seqtool/stems/<song>.<stem>.wav, and reused while newer than
the source. (Before 0.22.0 only <song>-vocal_stem.wav, beside the song, was made;
it is still read for the vocal level until the song is separated again.)
Returns None (and the analyzer simply omits the stem fields) when Demucs/torch are
unavailable or declined.

Fixed vs. the original: the up-to-date check and the produced file now use the
same filename; the transformer segment cap is applied before use; the temp
directory is not shadowed by a second nested TemporaryDirectory.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from ..common.deps import need
from ..common.log import debug, error, good, info, warn

MODEL = "htdemucs"


def demucs_progress(stream, tty: bool | None = None) -> list[str]:
    """Show Demucs' progress while it works. Demucs draws a progress bar with carriage
    returns (no newlines), so the output is read in chunks and split on both. On a
    terminal the line is rewritten in place; elsewhere (the GUI, a log) a line is
    printed every 10%. Returns the output lines, for the error message if it fails."""
    import os
    import time
    pct_re = re.compile(r"(\d+)%\|")
    if tty is None:
        from ..common.log import rewrites
        tty = rewrites(sys.stderr)
    t0, last, shown, buf, lines = time.monotonic(), -1, -10, "", []

    def dur(sec):
        return f"{sec:.0f} s" if sec < 90 else f"{sec / 60:.1f} min"

    def show(p):
        el = time.monotonic() - t0
        eta = f", about {dur(el * (100 - p) / p)} to go" if 5 <= p < 100 and el > 3 else ""
        txt = f"  Demucs: {p:3d}%  ({dur(el)} so far{eta})"
        from ..common.log import progress
        progress(txt, level="info")
    try:
        fd = stream.fileno()
    except (AttributeError, OSError, ValueError):
        fd = None
    while True:
        chunk = os.read(fd, 4096) if fd is not None else stream.read(4096)
        if not chunk:
            break
        buf += chunk.decode("utf-8", "replace") if isinstance(chunk, bytes) else chunk
        parts = re.split(r"[\r\n]", buf)
        buf = parts.pop()
        for part in parts:
            m = pct_re.search(part)
            if part.strip() and not m:
                lines.append(part)
            if m and int(m.group(1)) != last:
                last = int(m.group(1))
                if tty or last >= shown + 10 or last == 100:
                    shown = last
                    show(last)
    if buf.strip():
        lines.append(buf)
    if tty and last >= 0:
        from ..common.log import progress_end
        progress_end()                            # the progress line goes
    return lines[-30:]


STEMS = ("vocals", "drums", "bass", "other")


def stems_dir(audio: Path) -> Path:
    """<song>-seqtool/stems/ (results go in a subfolder, never beside the song)."""
    audio = Path(audio)
    if audio.parent.name.endswith("-seqtool"):
        return audio.parent / "stems"
    from ..common.paths import seqtool_folder
    return seqtool_folder(audio) / "stems"


def stem_file(audio: Path, name: str) -> Path:
    return stems_dir(audio) / f"{Path(audio).stem}.{name}.wav"


def legacy_vocal(audio: Path) -> Path:
    """Where seqtool before 0.22.0 put the vocal stem: beside the song."""
    audio = Path(audio)
    return audio.with_name(f"{audio.stem}-vocal_stem.wav")


def stem_path(audio: Path) -> Path:
    """The vocal stem: the 0.22.0 one in the stems folder, else an older one beside the song."""
    new, old = stem_file(audio, "vocals"), legacy_vocal(audio)
    return old if not new.is_file() and old.is_file() else new


def find_stem(audio: Path, filename: str) -> Path:
    """A stem file music.json names, in the stems folder or (older) beside the song."""
    d = stems_dir(audio) / filename
    return d if d.is_file() or not (Path(audio).parent / filename).is_file() else Path(audio).parent / filename


def stem_record(stem: Path) -> dict:
    """What music.json records about the stem it measured, so a cached analysis
    can tell when the stem file is missing or was replaced."""
    from ..common.canonical import file_sha256
    st = stem.stat()
    return {"stem_file": stem.name, "stem_sha256": file_sha256(stem), "size": st.st_size,
            "mtime_ns": st.st_mtime_ns}


def _changed(f: Path, rec: dict) -> bool:
    st = f.stat()
    if rec.get("size") == st.st_size and rec.get("mtime_ns") == st.st_mtime_ns:
        return False                          # same file as measured: no need to hash it again
    from ..common.canonical import file_sha256
    return file_sha256(f) != rec.get("stem_sha256")


def stem_problems(doc: dict, audio: Path | None = None, want: bool | None = None) -> list[str]:
    """Why a music.json's vocal data no longer fits ([] = fine): the stem file it
    measured is missing or replaced, or (when `want` is given) it was made with
    stems on/off while the current run asks for the other."""
    summ = doc.get("analysis", {}).get("summary", {})
    vocal = summ.get("vocal", {})
    used = vocal.get("source") == "demucs stem"
    if want is True and not used:
        return ["made without a vocal stem"]
    if want is True and "stems" not in summ:
        return ["made with the vocal stem only (drum, bass and other stems: 0.22.0)"]
    if want is False and used:
        return ["made with a vocal stem; --stems is off"]
    if not used:
        return []
    if audio is None:
        where = doc.get("run", {}).get("audio")
        if not where:
            return []                       # no record of where the audio is; nothing to check against
        audio = Path(where)
    audio = Path(audio)
    stem = find_stem(audio, vocal["stem_file"]) if vocal.get("stem_file") else stem_path(audio)
    sha = vocal.get("stem_sha256")
    if not stem.is_file():
        return [f"vocal stem {stem.name} missing"]
    if sha is None:
        return ["no vocal stem record"]      # made before 0.15.1
    if _changed(stem, vocal):
        return [f"vocal stem {stem.name} changed"]
    out = []
    for name, rec in summ.get("stems", {}).items():
        if name == "vocals" or not rec.get("stem_file"):
            continue
        f = find_stem(audio, rec["stem_file"])
        if not f.is_file():
            out.append(f"{name} stem {f.name} missing")
        elif _changed(f, rec):
            out.append(f"{name} stem {f.name} changed")
    return out


def _same_length(a: Path, b: Path) -> bool:
    try:
        from .decode import probe
        return abs(probe(a)["duration"] - probe(b)["duration"]) < 0.5
    except Exception:
        return True                          # can't tell; trust the timestamp


def _fresh(f: Path, audio: Path) -> bool:
    return f.is_file() and f.stat().st_mtime >= audio.stat().st_mtime


def separate(audio: Path, segment: int = 7, force: bool = False) -> dict[str, Path] | None:
    """All four stems ({name: wav}), separated once and kept in the stems folder.
    None when Demucs isn't there (or failed)."""
    audio = Path(audio)
    files = {n: stem_file(audio, n) for n in STEMS}
    if not force and all(_fresh(f, audio) for f in files.values()):
        if _same_length(files["vocals"], audio):
            info(f"  stems up to date: {stems_dir(audio).name}/ (vocals, drums, bass, other)")
            return files
        warn(f"  {files['vocals'].name} doesn't match the song's length; separating again")
    elif not force and legacy_vocal(audio).is_file() and not files["vocals"].is_file():
        info(f"  {legacy_vocal(audio).name} has the vocals only; separating again for drums, bass and other "
             "(0.22.0) - the old file isn't used after this and can be deleted")
    if need("demucs", purpose="stem separation (vocals, drums, bass, other)", pip="demucs", load=False) is None:
        return None
    segment = min(int(segment), 7)          # htdemucs transformer limit (~7.8 s)
    with tempfile.TemporaryDirectory(prefix="seqtool_demucs_") as tmp:
        cmd = [sys.executable, "-m", "demucs", "-n", MODEL, "--segment", str(segment), "-o", tmp, str(audio)]
        info("  separating vocals, drums, bass and other with Demucs - this takes a few minutes; progress follows ...")
        debug("  " + " ".join(cmd))
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        log = demucs_progress(proc.stdout)
        proc.stdout.close()
        if proc.wait() != 0:
            error("\n".join(log))
            return None
        made = Path(tmp) / MODEL / audio.stem
        if not (made / "vocals.wav").exists():
            error(f"Demucs did not produce {made / 'vocals.wav'}")
            return None
        stems_dir(audio).mkdir(parents=True, exist_ok=True)
        got = {}
        for n, f in files.items():
            if (made / f"{n}.wav").exists():
                shutil.move(str(made / f"{n}.wav"), str(f))
                got[n] = f
        missing = [n for n in STEMS if n not in got]
        if missing:
            warn(f"  Demucs made no {', '.join(missing)} stem - that part of the analysis is left out")
    good(f"  stems -> {stems_dir(audio)}/ ({', '.join(got)})")
    return got


def vocal_stem(audio: Path, segment: int = 7, force: bool = False) -> Path | None:
    got = separate(audio, segment, force)
    return (got or {}).get("vocals")
