"""seqtool self-extracting launcher (the __main__.py of seqtool-X.Y.Z.pyz; 0.19.3).

Built by 'seqtool package'. Standard library only, so it runs before anything is
unpacked. What it does each time it is started:

1. Unpack (only when this file's version isn't unpacked yet) into the folder next to
   it, <folder of the .pyz>/seqtool/ - or SEQTOOL_HOME, or --unpack-to DIR (remembered
   in the folder's .seqtool-location). The files stay there for next time.
2. Upgrading: the folder's .seqtool-manifest.json records the sha256 of every file
   as the previous version shipped it. A file on disk that still matches it was not
   changed, so it is replaced silently; a file that differs was customised, so the
   user is asked: keep it (the new version is saved next to it as FILE.new), or
   replace it (yours is kept as FILE.old). Files the new version no longer has are
   removed when unchanged, kept (and named) when customised. Then the new manifest
   is written - always with the shipped hashes, so the next version asks again
   about a file that is still customised.
3. Run seqtool from the unpacked folder with the same arguments.

Its own options (before any seqtool arguments):
    --unpack-only        unpack / upgrade, don't run seqtool
    --unpack-to DIR      unpack there instead
    --where              print where the files are
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile

MANIFEST = ".seqtool-manifest.json"
PAYLOAD = "payload/"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def archive():
    """The zip this launcher came in: the .pyz itself, or payload.zip next to a frozen exe."""
    here = os.path.dirname(os.path.abspath(__file__))
    if zipfile.is_zipfile(here):                         # running from inside seqtool.pyz
        return here, zipfile.ZipFile(here)
    frozen = getattr(sys, "_MEIPASS", None)               # a PyInstaller exe ('package --exe')
    for d in filter(None, [frozen, here]):
        p = os.path.join(d, "payload.zip")
        if os.path.exists(p):
            return (sys.executable if frozen else p), zipfile.ZipFile(p)
    sys.exit("seqtool: the package is damaged (no payload found)")


def target_dir(src, args):
    if "--unpack-to" in args:
        i = args.index("--unpack-to")
        d = args[i + 1]
        del args[i:i + 2]
        return os.path.abspath(os.path.expanduser(d))
    if os.environ.get("SEQTOOL_HOME"):
        return os.path.abspath(os.path.expanduser(os.environ["SEQTOOL_HOME"]))
    d = os.path.join(os.path.dirname(os.path.abspath(src)), "seqtool")
    try:
        os.makedirs(d, exist_ok=True)
        probe = os.path.join(d, ".write-test")
        open(probe, "w").close()
        os.remove(probe)
        return d
    except OSError:                                       # e.g. a read-only download folder
        base = os.environ.get("LOCALAPPDATA") if os.name == "nt" else \
            os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
        return os.path.join(base or os.path.expanduser("~"), "seqtool")


def ask(question, choices, default):
    """One letter from choices; the default without a terminal."""
    if not sys.stdin or not sys.stdin.isatty():
        return default
    while True:
        try:
            a = input(question + " ").strip().lower()[:1] or default
        except EOFError:
            return default
        if a in choices:
            return a


def unpack(zf, dest, quiet=False):
    """Install or upgrade the files in dest from the zip. Returns the new version."""
    new = json.loads(zf.read(PAYLOAD + MANIFEST))
    old_path = os.path.join(dest, MANIFEST)
    old = {}
    if os.path.exists(old_path):
        try:
            with open(old_path, encoding="utf-8") as f:
                old = json.load(f)
        except ValueError:
            old = {}
    if old.get("version") == new["version"] and all(os.path.exists(os.path.join(dest, p)) for p in new["files"]):
        return new["version"]                            # already unpacked: nothing to do
    first = not old
    say = (lambda *a: None) if quiet else print
    say(("unpacking" if first else f"upgrading seqtool {old.get('version', '?')} ->") +
        f" seqtool {new['version']} in {dest}")
    old_files = old.get("files", {})
    changed, write = [], []
    for rel, h in sorted(new["files"].items()):
        path = os.path.join(dest, rel)
        if not os.path.exists(path):
            write.append(rel)
            continue
        cur = file_sha(path)
        if cur == h:
            continue                                      # already the new version
        if old_files.get(rel) == cur:
            write.append(rel)                              # unchanged since the last version: replace
        elif old_files.get(rel) == h:
            continue                                       # yours, and this version didn't change it: keep, no question
        else:
            changed.append(rel)                            # customised (or not from seqtool): ask
    keep = set()
    if changed:
        say(f"\n{len(changed)} file(s) were changed since seqtool unpacked them (or were not unpacked by it):")
        for rel in changed:
            say(f"  {rel}")
        a = ask("Replace them with the new versions? [k]eep all yours (default; the new versions are saved as "
                "FILE.new) / [r]eplace all (yours are kept as FILE.old) / [o]ne by one:", "kro", "k")
        for rel in changed:
            b = a if a != "o" else ask(f"  {rel}: [k]eep yours / [r]eplace?", "kr", "k")
            if b == "r":
                shutil.copy2(os.path.join(dest, rel), os.path.join(dest, rel) + ".old")
                write.append(rel)
            else:
                keep.add(rel)
    for rel in write:
        path = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(zf.read(PAYLOAD + rel))
        if rel.endswith(".py") and rel.count("/") == 0:
            try:
                os.chmod(path, 0o755)
            except OSError:
                pass
    for rel in sorted(keep):
        with open(os.path.join(dest, rel) + ".new", "wb") as f:
            f.write(zf.read(PAYLOAD + rel))
    gone_kept = []
    for rel, h in old_files.items():                       # files this version no longer has
        if rel in new["files"]:
            continue
        path = os.path.join(dest, rel)
        if os.path.exists(path):
            if file_sha(path) == h:
                os.remove(path)
            else:
                gone_kept.append(rel)
    with open(old_path, "w", encoding="utf-8") as f:
        json.dump(new, f, indent=1)
    if keep:
        say(f"kept your {len(keep)} file(s); the new versions are next to them as .new - compare and merge when you like")
    if gone_kept:
        say("no longer part of seqtool, but changed by you, so kept: " + ", ".join(gone_kept))
    say(f"seqtool {new['version']} is ready ({len(write)} file(s) written)\n")
    return new["version"]


def python_cmd():
    """The Python to run seqtool with: this one, unless this is a frozen exe."""
    if not getattr(sys, "frozen", False):
        return [sys.executable]
    for c in (["py", "-3"], ["python3"], ["python"]):
        if shutil.which(c[0]):
            return c
    sys.exit("seqtool needs Python 3.10 or newer: install it from python.org (Windows: tick 'Add python.exe to "
             "PATH'), then start seqtool again")


def check_numpy(py):
    if subprocess.call(py + ["-c", "import numpy"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
        return
    a = ask("seqtool needs numpy, which isn't installed. Install it now with pip? [Y/n]", "yn", "y")
    if a != "y":
        sys.exit("seqtool needs numpy: " + " ".join(py) + " -m pip install numpy")
    cmd = py + ["-m", "pip", "install", "numpy"]
    if sys.platform.startswith("linux") and sys.prefix == getattr(sys, "base_prefix", sys.prefix):
        cmd.append("--break-system-packages")             # a distro's Python (PEP 668)
    if subprocess.call(cmd) != 0:
        sys.exit("installing numpy failed - try: " + " ".join(cmd))


def main():
    args = sys.argv[1:]
    src, zf = archive()
    dest = target_dir(src, args)
    if "--where" in args:
        print(dest)
        return 0
    only = "--unpack-only" in args
    if only:
        args.remove("--unpack-only")
    unpack(zf, dest)
    if only:
        return 0
    py = python_cmd()
    check_numpy(py)
    try:
        return subprocess.call(py + [os.path.join(dest, "seqtool.py")] + args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
