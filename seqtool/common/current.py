"""The current song and its newest results, wherever they were written.

Results for one song can live in two places:
  * pipeline results:  <song folder>/<song>-seqtool/<song>.music.json ...   (run, demo)
  * single stages:     the same folder since 0.19.9 (before: <song>-seqtool.music.json beside the song)
The current song is the last one any command worked on (answers.json
last_audio); for each kind of result the newest matching file wins. The GUI,
explain, gui, status and sections all use this, so they always agree.
"""
from __future__ import annotations

from pathlib import Path

from . import config
from .canonical import read_json
from .paths import base_name, legacy_name, seqtool_folder, seqtool_name


def song_folders() -> list[Path]:
    """Folders songs were used from: recent songs, baselines, results of fixed songs."""
    out = [Path(x) for x in (config.answer("recent_folders") or [])]
    try:
        for bf in sorted((config.user_dir() / "baselines").glob("*.json")):
            out += [Path(k).parent for k in read_json(bf).get("songs", {})]
    except Exception:  # noqa: BLE001
        pass
    try:
        from . import songs
        out += [Path(r["music"]).parent.parent for r in songs._all().values() if r.get("music")]
    except Exception:  # noqa: BLE001
        pass
    for key in ("last_audio",):
        v = config.answer(key)
        if v:
            out.append(Path(v).parent)
    out.append(Path.cwd())
    known = [d for d in dict.fromkeys(out) if d.is_dir()]
    near = []                                    # their neighbours: a song moved to a sibling folder
    for d in known:
        try:
            near += [c for c in sorted(d.parent.iterdir())[:200] if c.is_dir() and not c.name.endswith("-seqtool")]
        except OSError:
            pass
    return list(dict.fromkeys(known + near))


def relocate(path, sha: str | None = None) -> Path | None:
    """A remembered song that isn't where it was: the same file name in a folder songs
    were used from (and, when its checksum is known, the same audio). Every remembered
    reference to the old path is updated. None when it can't be found."""
    old = Path(path)
    if old.exists():
        return old
    from .canonical import file_sha256
    for d in song_folders():
        cand = d / old.name
        if cand.is_file() and cand.resolve() != old.resolve():
            if sha and file_sha256(cand) != sha:
                continue
            _moved(old, cand.resolve())
            return cand.resolve()
    return None


_SAID: set = set()


def _moved(old: Path, new: Path) -> None:
    """Point remembered answers, baselines and per-song records at the song's new place."""
    from .log import info
    from .paths import show
    olds = str(old)
    for key in ("last_audio",):
        if config.answer(key) == olds:
            config.remember(key, str(new))
    try:                                                    # remembered prompt answers (arg:...)
        f = config.user_dir() / "answers.json"
        import json
        a = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        changed = {k: str(new) for k, v in a.items() if v == olds}
        for k, v in changed.items():
            config.remember(k, v)
    except Exception:  # noqa: BLE001
        pass
    try:                                                    # baselines
        import json
        for bf in sorted((config.user_dir() / "baselines").glob("*.json")):
            b = read_json(bf)
            if olds in b.get("songs", {}):
                b["songs"] = {(str(new) if k == olds else k): v for k, v in b["songs"].items()}
                bf.write_text(json.dumps(b, indent=1) + "\n", encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    if old.name not in _SAID:                             # once per session
        _SAID.add(old.name)
        info(f"{old.name} has moved: now using {show(new)}")


def _audio_of_music(music_file: Path) -> Path | None:
    try:
        m = read_json(music_file)
    except Exception:  # noqa: BLE001
        return None
    p = m.get("run", {}).get("audio")
    if p and Path(p).exists():
        return Path(p)
    cand = music_file.parent / m.get("source", {}).get("filename", "")
    return cand if cand.is_file() else None


def _newest(paths) -> Path | None:
    ex = [p for p in dict.fromkeys(paths) if p and p.exists()]
    return max(ex, key=lambda p: p.stat().st_mtime) if ex else None


def music_of(arg) -> Path:
    """A stage's music.json input: given as a .json, a song (its newest analysis), or
    nothing (the current song's)."""
    from .paths import is_audio
    if arg is None:
        s = song()
        if not s or not s.get("music"):
            raise SystemExit("no song analysed yet - 'analyze-music SONG' first (or 'run --audio SONG')")
        return s["music"]
    p = Path(arg)
    if is_audio(p):
        s = song(p)
        if not s or not s.get("music"):
            raise SystemExit(f"{p.name} isn't analysed yet - 'analyze-music \"{p}\"' first")
        return s["music"]
    return p


def results_of(arg, kind: str) -> Path:
    """A stage's input of `kind` ('matchup', 'profile'): a .json, or a song's newest."""
    from .paths import is_audio
    p = Path(arg)
    if not is_audio(p):
        return p
    s = song(p)
    if not s or not s.get(kind):
        raise SystemExit(f"no {kind} for {p.name} yet - 'run --audio \"{p}\"' makes one")
    return s[kind]


def song(audio_arg=None) -> dict | None:
    """{audio, music, profile, matchup, folder, base} or None when nothing is known yet.
    Missing results are None (e.g. right after analyze-music there is no matchup)."""
    la, lm = config.answer("last_audio"), config.answer("last_music")
    if audio_arg is not None:                                       # a given song, not the current one
        if Path(la or "").resolve() != Path(audio_arg).resolve():
            la, lm = str(audio_arg), None
    audio = Path(la) if la else (_audio_of_music(Path(lm)) if lm and Path(lm).exists() else None)
    if audio is not None and not audio.exists():          # moved since? look for it (same audio)
        sha = None
        try:
            sha = read_json(Path(lm)).get("lineage", {}).get("audio") if lm and Path(lm).exists() else None
        except Exception:  # noqa: BLE001
            pass
        audio = relocate(audio, sha) or audio
    if audio is None:
        return None
    base = base_name(audio)
    folders = [seqtool_folder(audio)]
    lo = config.answer("last_out")
    if lo:
        folders.append(Path(lo))
    musics = [legacy_name(audio, "music")] + [f / f"{audio.stem}.music.json" for f in folders]
    if lm:
        musics.append(Path(lm))
    musics = [m for m in musics if m.exists() and _belongs(m, audio)]
    music = _newest(musics)
    out = {"audio": audio, "base": base, "music": music, "profile": None, "matchup": None,
           "folder": music.parent if music else seqtool_folder(audio)}
    if music is None:
        return out
    name = music.name[: -len(".music.json")]                      # "song" or "song-seqtool"
    prof = music.with_name(f"{name}.music-profile.json")
    out["profile"] = prof if prof.exists() else None
    lmu = config.answer("last_matchup")
    mus = list(music.parent.glob(f"{name}.matchup*.json"))
    if lmu and Path(lmu).exists() and Path(lmu).parent == music.parent and Path(lmu).name.startswith(name + "."):
        out["matchup"] = Path(lmu)                                # the final plan of the latest run
    else:
        out["matchup"] = _newest(mus)
    return out


def _belongs(music_file: Path, audio: Path) -> bool:
    try:
        m = read_json(music_file)
    except Exception:  # noqa: BLE001
        return False
    p = m.get("run", {}).get("audio")
    if p:
        return Path(p).resolve() == audio.resolve()
    return m.get("source", {}).get("filename") == audio.name


def leftovers() -> list[Path]:
    """Result files of the current song under a name it no longer has (renamed since):
    in its results folder, made from the same audio, with another file name. They are
    no longer used or updated."""
    s = song()
    if not s:
        return []
    audio, folder = s["audio"], seqtool_folder(s["audio"])
    if not folder.is_dir():
        return []
    try:
        from .canonical import file_sha256
        sha = file_sha256(audio)
    except OSError:
        return []
    stems = set()
    for f in folder.glob("*.music.json"):
        stem = f.name[: -len(".music.json")]
        if stem == audio.stem:
            continue
        try:
            if read_json(f).get("lineage", {}).get("audio") == sha:
                stems.add(stem)
        except Exception:  # noqa: BLE001
            pass
    return sorted(f for f in folder.iterdir() for st in stems if f.name.startswith(st + "."))


def superseded() -> list[Path]:
    """Single-stage results next to the song (<song>-seqtool.music.json ...) when the
    song's results in use are elsewhere (its -seqtool folder): older, no longer read or
    updated, so 'status' leaves them out and 'status --clean' deletes them (0.19.8)."""
    s = song()
    if not s or s.get("music") is None or s["music"].parent == s["audio"].parent:
        return []
    audio = s["audio"]
    out = []
    for f in sorted(audio.parent.glob(f"{s['base']}-seqtool.*")):
        if not f.is_file():
            continue
        if f.suffix == ".json":
            try:
                d = read_json(f)
                if d.get("lineage", {}).get("audio") not in (None, _sha_of(audio)):
                    continue                                    # another song of the same name
            except Exception:  # noqa: BLE001
                continue
        out.append(f)
    return out


def _sha_of(p: Path) -> str | None:
    try:
        from .canonical import file_sha256
        return file_sha256(p)
    except OSError:
        return None


def files() -> list[Path]:
    """Every result file of the current song (for change detection and cache status)."""
    s = song()
    if not s:
        return []
    out = []
    audio = s["audio"]
    places = [(seqtool_folder(audio), audio.stem + ".")]
    if s.get("music") is None or s["music"].parent == audio.parent:   # single-stage files next to the song: only
        places.append((audio.parent, s["base"] + "-seqtool."))         # while they are the ones in use (0.19.8)
    for folder, prefix in places:
        if folder.is_dir():                     # this song's files (and the shared layout files), not
            out += [f for f in folder.iterdir() if f.name.startswith(prefix) or    # those of an old name
                    (folder == seqtool_folder(audio) and f.name.startswith("layout") and f.suffix == ".json")]
    lo = config.answer("last_out")
    if lo and Path(lo).is_dir() and Path(lo) != seqtool_folder(audio) and \
            (s.get("music") is None or s["music"].parent.resolve() == Path(lo).resolve()):   # only the folder in use
        out += [f for f in Path(lo).iterdir() if f.name.startswith(audio.stem + ".")]
    return sorted(set(out))


FOLLOW = False                                       # an interactive session: work in the song's folder
_PENDING = False


def after_command() -> None:
    """Between commands (never during one, whose relative paths would break): move to a
    song that became current."""
    global _PENDING
    if _PENDING:
        _PENDING = False
        follow_song()


def follow_song(say: bool = True) -> Path | None:
    """The working folder becomes the current song's folder (0.21.4, the user's request: not
    the folder seqtool was started from), so relative paths and completion start there. The
    preference folder was fixed when seqtool started and doesn't move."""
    global FOLLOW
    FOLLOW = True
    import os
    from . import config
    config.user_dir()                                 # fixed before any move
    la = config.answer("last_audio")
    if not la or not Path(la).parent.is_dir():
        return None
    d = Path(la).parent.resolve()
    if d == Path.cwd().resolve():
        return None
    try:
        os.chdir(d)
    except OSError:
        return None
    if say:
        from .log import info
        from .paths import show
        info(f"working folder: {show(d)} (the current song's) " + "{note}('cd FOLDER' changes it; 'pwd' shows the folders){/}")
    return d


def remember(audio: Path | None = None, music: Path | None = None, matchup: Path | None = None) -> None:
    global _PENDING
    if audio is not None and FOLLOW and config.answer("last_audio") != str(Path(audio).resolve()):
        _PENDING = True                               # a new current song: its folder after this command
    if audio is not None:
        config.remember("last_audio", str(Path(audio).resolve()))
        recent = [str(Path(audio).resolve().parent)] + [x for x in (config.answer("recent_folders") or [])
                                                          if x != str(Path(audio).resolve().parent)]
        config.remember("recent_folders", recent[:20])
    if music is not None:
        config.remember("last_music", str(Path(music).resolve()))
    if matchup is not None:
        config.remember("last_matchup", str(Path(matchup).resolve()))
