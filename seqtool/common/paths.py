"""Path display: relative to the current directory when inside it."""
from __future__ import annotations

import os
from pathlib import Path


import contextlib
import threading

_anchor = threading.local()        # per thread: GUI commands run in their own threads


@contextlib.contextmanager
def anchored(file):
    """While a command works on one main file (a song, a layout, a sequence), show
    the files in its folder or below relative to that folder ('song-seqtool/song.summary.txt'
    instead of '../../Music/2026/song-seqtool/song.summary.txt'). The main file itself
    stays relative to the current folder, so you can see where it is."""
    prev = getattr(_anchor, "file", None)
    _anchor.file = Path(file).resolve() if file else None
    try:
        yield
    finally:
        _anchor.file = prev


def show(path, typed: bool = False) -> str:
    """A path for messages: relative to the current folder (or, inside anchored(),
    to the main file's folder). typed=True: always from the current folder - for paths
    inside example commands, which are typed where you are. A folder ends in '/' (0.21.5,
    the user's rule: it is clearly not a file)."""
    t = _show(path, typed)
    try:
        if Path(path).is_dir() and not t.endswith(("/", os.sep)):
            t += "/" if os.sep == "/" or "/" in t else os.sep
    except OSError:
        pass
    return t


def _show(path, typed: bool = False) -> str:
    p = Path(path)
    a = None if typed else getattr(_anchor, "file", None)
    if a is not None:
        try:
            rp = p.resolve()
            if rp != a:
                r = rp.relative_to(a.parent)
                if str(r) != ".":
                    return str(r)
        except (ValueError, OSError):
            pass
    try:
        r = p.resolve().relative_to(Path.cwd().resolve())
        return str(r) if str(r) != "." else "."
    except ValueError:
        return str(p.resolve())


def resolve(text: str) -> Path:
    """User-typed path: ~ expanded, relative paths taken from the current directory."""
    return Path(os.path.expanduser(text.strip().strip("'\""))).resolve()


GLOB_CHARS = "*?["
KINDS = ("music-profile", "music", "models", "layout", "matchup", "validation", "timeline", "summary")


class NoMatch(ValueError):
    """A typed glob pattern that matches nothing."""


def _command_hint(text: str) -> str:
    """A whole command typed where a file name was asked for (0.24.58)."""
    w = str(text).split()
    if len(w) > 1 and (any(x.startswith("--") for x in w) or w[0] in ("run", "layout", "lyrics", "sections")):
        return " - that looks like a command: a question that asks for a file wants just the file's name"
    return ""


def where(path) -> str:
    """' (relative to C:\\...)' for a relative path - which folder a typed path was looked for in."""
    try:
        return "" if Path(path).expanduser().is_absolute() else f" (looked for in {os.getcwd()}, the working folder)"
    except (OSError, ValueError):
        return ""


def expand(text: str, want: str = "any") -> Path:
    """A typed path that may contain a glob pattern (*, ?, [..]) and ~.
    One match -> that path. Several -> the user picks one (on a terminal), or an
    error listing them. None -> NoMatch, naming the working folder (0.24.58)."""
    from glob import glob
    raw = os.path.expanduser(str(text).strip().strip("'\""))
    if not any(ch in raw for ch in GLOB_CHARS):
        return Path(raw)
    hits = sorted(glob(raw))
    if want == "dir":
        hits = [h for h in hits if os.path.isdir(h)]
    elif want == "file":
        hits = [h for h in hits if os.path.isfile(h)]
    if len(hits) == 1:
        return Path(hits[0])
    if not hits:                                   # 0.24.58: said here, with where it looked
        raise NoMatch(f"nothing matches '{text}'" + ("" if os.path.isabs(raw) else f" in {os.getcwd()} (the "
                      "working folder - 'pwd' shows it, 'cd FOLDER' changes it)") + _command_hint(text))
    from .prompt import ask, interactive
    if not interactive():
        raise ValueError(f"'{text}' matches {len(hits)} paths: " + ", ".join(hits[:8])
                         + (" ..." if len(hits) > 8 else ""))
    for i, h in enumerate(hits, 1):
        print(f"  {i:>2}. {show(h)}")
    while True:
        ans = ask(f"'{text}' matches {len(hits)} - which one? (number)", "1")
        if ans.isdigit() and 1 <= int(ans) <= len(hits):
            return Path(hits[int(ans) - 1])


def arg(text: str) -> Path:
    """argparse type for any file or folder argument: glob-aware."""
    import argparse
    try:
        return expand(text)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e))


def base_name(p: Path) -> str:
    """'song.mp3' -> 'song'; 'song-seqtool.music.json' -> 'song'; 'song.music.json' -> 'song'."""
    name = Path(p).name
    if "-seqtool." in name:
        return name.split("-seqtool.", 1)[0]
    for k in KINDS:
        if name.endswith(f".{k}.json"):
            return name[: -len(f".{k}.json")]
    return Path(name).stem


def seqtool_name(src: Path, kind: str, ext: str = "json") -> Path:
    """Default output for an input: in its results subfolder, never beside it (the
    user's rule, 0.19.9): <folder>/<base>-seqtool/<base>.<kind>.<ext> - or, for an
    input already in such a folder, beside it there."""
    src = Path(src)
    base = base_name(src)
    folder = src.parent if src.parent.name.endswith("-seqtool") else src.parent / f"{base}-seqtool"
    return folder / f"{base}.{kind}.{ext}"


def legacy_name(src: Path, kind: str, ext: str = "json") -> Path:
    """Where single stages wrote before 0.19.9, beside the input: <base>-seqtool.<kind>.<ext>.
    Still read (an older result is found), never written."""
    src = Path(src)
    return src.parent / f"{base_name(src)}-seqtool.{kind}.{ext}"


AUDIO_EXT = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".aif", ".aiff", ".wma", ".opus"}


def is_audio(p) -> bool:
    return Path(p).suffix.lower() in AUDIO_EXT


def sibling(src: Path, kind: str, ext: str = "json") -> Path:
    """Where a stage writes its result for input `src`, in the same style as the input:
    a results folder file 'song.music.json' -> 'song.<kind>.json' next to it; a
    single-stage file 'song-seqtool.music.json' -> 'song-seqtool.<kind>.json'."""
    src = Path(src)
    name = src.name
    if "-seqtool." not in name:
        for k in KINDS:
            if name.endswith(f".{k}.json"):
                return src.parent / f"{name[: -len(f'.{k}.json')]}.{kind}.{ext}"
    return seqtool_name(src, kind, ext)


def stage_output(audio: Path, kind: str = "music") -> Path:
    """analyze-music's default output: the song's results folder (made if needed), where
    'run', 'status' and the GUI look - never beside the song (0.19.9)."""
    return seqtool_folder(audio) / f"{Path(audio).stem}.{kind}.json"


def seqtool_folder(audio: Path) -> Path:
    """Default results folder for a song: <audio folder>/<base>-seqtool/."""
    return Path(audio).parent / f"{base_name(audio)}-seqtool"


def _writable(d: Path) -> bool:
    import tempfile
    try:
        with tempfile.NamedTemporaryFile(dir=d, prefix=".seqtool-", delete=True):
            return True
    except OSError:
        return False


def _system_dir(d: Path) -> bool:
    """A folder seqtool's files never belong in, even when it can write there (Windows
    starts a double-clicked program in C:\\Windows\\System32)."""
    if os.name != "nt":
        return False
    roots = [os.environ.get(k) for k in ("SystemRoot", "windir", "ProgramFiles", "ProgramFiles(x86)")]
    try:
        r = d.resolve()
        return any(x and (r == Path(x).resolve() or Path(x).resolve() in r.parents) for x in roots)
    except OSError:
        return False


def ensure_work_dir() -> Path | None:
    """When seqtool starts in a folder it can't write to (or a Windows system folder:
    the .pyz double-clicked), work in ~/seqtool-files instead (0.19.6). Returns the new
    folder, or None when the current one is fine. SEQTOOL_PREFS, if set, is untouched."""
    cwd = Path.cwd()
    if _writable(cwd) and not _system_dir(cwd):
        return None
    home = Path.home() / "seqtool-files"
    try:
        home.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    os.chdir(home)
    from . import config
    config.reanchor()
    return home
