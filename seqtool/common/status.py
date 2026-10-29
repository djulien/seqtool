# seqtool-command: status | main | pipeline | report stale or mismatched files in output folders
"""seqtool status [DIR...] [--clean] : report stale or mismatched artifacts in output folders.

With no folder: the current song's results (a song renamed since leaves files under
its old name; they are listed apart, and 'status --clean' deletes them).

Checks every seqtool JSON file in each folder:
  - made by an older seqtool MAJOR.MINOR than the installed one
  - built from an intermediate file whose content has since changed
  - original source file (audio named in source.filename) changed on disk
  - the vocal stem a music.json was measured from is missing or changed
Exit code 1 when anything is stale.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .. import __version__
from .canonical import content_sha256, file_sha256, read_json
from .freshness import _mm
from .paths import arg as paths_arg


def _audio_now(d: dict) -> Path | None:
    """Where the song of a music.json is now: where it was run from, or - moved or
    renamed since - the current song when it is the same audio. Only looks (status
    changes nothing)."""
    where = d.get("run", {}).get("audio")
    if where and Path(where).exists():
        return Path(where)
    from . import current
    cur = current.song()
    sha = d.get("lineage", {}).get("audio")
    if cur and sha and cur["audio"].exists() and _sha(cur["audio"]) == sha:
        return cur["audio"]
    return None


_SHAS: dict = {}


def _sha(p: Path) -> str:
    st = p.stat()
    key = (str(p), st.st_mtime_ns, st.st_size)
    if key not in _SHAS:
        _SHAS[key] = file_sha256(p)
    return _SHAS[key]


def scan(folder: Path) -> list[tuple[str, list[str]]]:
    docs = {}
    for p in sorted(folder.glob("*.json")):
        try:
            d = read_json(p)
        except Exception:
            continue
        if isinstance(d, dict) and str(d.get("schema", "")).startswith("seqtool."):
            docs[p.name] = d
    by_hash = {content_sha256(d): n for n, d in docs.items()}
    report = []
    for name, d in docs.items():
        why = []
        v = d.get("producer", {}).get("version", "0")
        if _mm(v) != _mm(__version__):
            why.append(v)
        for key, ref in d.get("source", {}).items():
            if not isinstance(ref, dict):
                continue
            if "content_sha256" in ref:
                fn = ref.get("filename")
                if ref["content_sha256"] in by_hash:
                    continue
                if fn and fn in docs:
                    why.append(f"{fn} changed")
            elif "sha256" in ref and ref.get("filename"):
                src = folder / ref["filename"]
                if src.exists() and file_sha256(src) != ref["sha256"]:
                    why.append(f"{ref['filename']} changed")
        if d.get("schema") == "seqtool.music":
            from ..music.stems import stem_problems
            audio = _audio_now(d)
            why += stem_problems(d, audio) if audio else stem_problems(d)
        report.append((name, why))
    return report


STAGE_CMD = (("music.json", "analyze-music {song}"), ("music-profile.json", "classify-music"),
             ("matchup.json", "match"), ("validation.json", "validate"))


def fix_hint(folder: Path, rows: list[tuple[str, list[str]]]) -> str | None:
    """The command that rebuilds what is stale here, as an example to type."""
    stale = [(n, why) for n, why in rows if why]
    if not stale:
        return None
    from . import current
    from .paths import show
    song = None
    for name, _ in stale + rows:
        f = folder / Path(name).name
        if f.name.endswith(".music.json") and f.exists():
            try:
                song = _audio_now(read_json(f))
            except Exception:   # noqa: BLE001
                song = None
            break
    cur = current.song()
    is_cur = bool(song and cur and Path(song).resolve() == Path(cur["audio"]).resolve())
    stems = any("stem" in w for _, why in stale for w in why)
    flags = " --stems" if stems and any("made without a vocal stem" not in w for _, why in stale for w in why) else ""
    if folder.name.endswith("-seqtool") or (folder / "layout.models.json").exists():      # a pipeline results folder
        from .paths import seqtool_folder
        if song and folder.resolve() != seqtool_folder(song).resolve():                   # written with --out
            return f"run --audio '{show(song, typed=True)}' --out '{show(folder, typed=True)}'{flags}"
        return ("run" + flags) if is_cur or not song else f"run --audio '{show(song, typed=True)}'{flags}"
    for suffix, cmd in STAGE_CMD:                    # single-stage files: start at the first stale stage
        if any(Path(n).name.endswith(suffix) for n, _ in stale):
            return cmd.format(song=f"'{show(song, typed=True)}'" if song else "SONG") + ("" if suffix != "music.json" else flags)
    return "run"


def current_paths() -> list[tuple[Path, list[str]]]:
    """(file, why stale) for the current song's result files, wherever they are."""
    from . import current
    files = [f for f in current.files() if f.suffix == ".json"]
    out = []
    for folder in sorted({f.parent for f in files}):
        names = {f.name for f in files if f.parent == folder}
        for name, why in scan(folder):
            if name in names:
                out.append((folder / name, why))
    return out


def current_rows() -> list[tuple[str, list[str]]]:
    """Status rows for the current song's result files, wherever they are."""
    return [(show_rel(p), w) for p, w in current_paths()]


def show_rel(p: Path) -> str:
    from .paths import show
    return show(p)


def _layout_line() -> bool:
    """One line about the stored layout; True when it is stale."""
    from .paths import show
    try:
        from ..layout import store
        why = store.stale_reasons()
        src = store.source_info()
    except Exception as e:  # noqa: BLE001
        print(f"layout:       {{warn}}can't be read{{/}} ({e}) - 'layout SHOWFOLDER' stores it again")
        return True
    if why is None:
        print("layout:       none stored yet - 'layout SHOWFOLDER' stores your xLights layout")
        return False
    where = show(Path(src["path"]))
    if why:
        print(f"layout:       {{warn}}STALE{{/}}  {where}  {{note}}({'; '.join(why)}){{/}}")
        print("fix: 'layout' re-reads it" + ("" if Path(src["path"]).exists() else
                                              f" - but {where} is gone: 'layout NEW/SHOWFOLDER'"))
        return True
    print(f"layout:       {{ok}}ok{{/}}     {where}")
    return False


def _kit_line() -> None:
    """One line about the xLights kit training: none, complete, or which steps it lacks (skipped ones too)."""
    try:
        from ..adapters.xlights import kit
        from ..adapters.xlights.encoding import find
        vers = kit.learned_versions()
        if not vers:
            print("xLights kit:  {warn}not run yet{/} - 'xlights-kit' learns how your xLights stores effects")
            return
        enc = find()
        obs, todo = kit.missing_steps(enc.version) if enc else (None, [])
        skipped = len((obs or {}).get("skipped_steps") or [])
        if not todo:
            print(f"xLights kit:  {{ok}}complete{{/}} for xLights {enc.version if enc else ', '.join(vers)}")
            return
        print(f"xLights kit:  {{warn}}incomplete{{/}} for xLights {enc.version}: {len(todo)} step(s) to learn"
              + (f" ({skipped} skipped)" if skipped else "") + f" - {kit.todo_names(todo)}")
        print("fix: 'xlights-kit --update' learns only those")
    except Exception as e:  # noqa: BLE001 - status never fails over this
        print(f"xLights kit:  can't be read ({e.__class__.__name__})")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool status", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folders", nargs="*", type=paths_arg, default=None,
                    help="default: the last results folder")
    ap.add_argument("--clean", action="store_true",
                    help="delete result files left from the current song's old name (asks first)")
    a = ap.parse_args(argv)
    from . import current
    from .paths import show
    cur = current.song()
    if cur:
        print(f"current song: {show(cur['audio'])}" + ("" if cur["audio"].exists() else "  (file not found)"))
    lay_bad = _layout_line()                         # the stored show layout too (0.19.11)
    _kit_line()                                      # 0.24.58: and the xLights training
    if not a.folders:
        if not cur:
            print("no song yet - run {do}seqtool run --audio SONG{/}")
            return 1 if lay_bad else 0
        paths = current_paths()
        rows = [(show_rel(p), w) for p, w in paths]
        print(f"results:      {show(cur['folder'])}" + ("" if rows else "  (none yet)"))
        bad = 0
        for name, why in rows:
            bad += bool(why)
            print(f"  {'{warn}STALE{/}' if why else '{ok}ok   {/}'}  {name}" + (f"  {{note}}({'; '.join(why)}){{/}}" if why else ""))
        if bad:                                      # one fix per folder: run only rebuilds its own results folder
            for folder in sorted({p.parent for p, w in paths if w}):
                hint = fix_hint(folder, [(p.name, w) for p, w in paths if p.parent == folder])
                if hint:
                    print(f"fix: '{hint}' rebuilds the stale files" + (f" in {show(folder)}" if len({p.parent for p, w in paths if w}) > 1 else "")
                          + " (fresh ones are reused)")
        old = current.leftovers()
        sup = current.superseded()
        if (old or sup) and a.clean:
            from .log import good
            from .prompt import ask
            gone = old + sup
            if ask(f"delete these {len(gone)} file(s) no longer used ({', '.join(f.name for f in gone[:4])}"
                   f"{' ...' if len(gone) > 4 else ''})? [Y/n]", "y", show_default=False).lower() in ("n", "no"):
                print("nothing deleted")
            else:
                for f in gone:
                    f.unlink()
                good(f"deleted {len(gone)} file(s): {', '.join(f.name for f in gone)}")
        else:
            if old:
                names = sorted({f.name.split(".")[0] for f in old})
                print(f"{{note}}{len(old)} file(s) in {show(cur['folder'])} are from this song's old name "
                      f"({', '.join(repr(n) for n in names)}, same audio) and no longer used{{/}} - "
                      "'{do}status --clean{/}' deletes them")
            if sup:
                print(f"{{note}}{len(sup)} older file(s) next to the song ({', '.join(f.name for f in sup[:3])}"
                      f"{' ...' if len(sup) > 3 else ''}) were made by single stages; the song's results are now "
                      f"in {show(cur['folder'])}, so they are no longer used{{/}} - '{{do}}status --clean{{/}}' deletes them")
            if a.clean and not old and not sup:
                print("nothing to clean: no files of an old name or older results for this song")
        return 1 if bad or lay_bad else 0
    stale = 0
    for f in a.folders:
        print(f"{f}/")
        rows = scan(f)
        if not rows:
            print("  no seqtool artifacts found")
        for name, why in rows:
            stale += bool(why)
            print(f"  {'{warn}STALE{/}' if why else '{ok}ok   {/}'}  {name}" + (f"  {{note}}({'; '.join(why)}){{/}}" if why else ""))
        hint = fix_hint(Path(f), rows)
        if hint:
            print(f"  fix: '{hint}' rebuilds the stale files (fresh ones are reused)")
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
