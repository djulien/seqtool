# seqtool-command: package | main | tools | build the self-extracting seqtool-X.Y.Z.pyz (Linux and Windows) for sharing
"""seqtool package [--out DIR] [--exe]

Builds one file that holds all of seqtool: dist/seqtool-X.Y.Z.pyz. Whoever runs it
gets the files unpacked next to it (in a 'seqtool' folder) the first time, and
seqtool started; later runs start the unpacked copy straight away. A newer .pyz
upgrades that folder: files nobody changed are replaced, files that were changed are
asked about (keep yours - the new version is saved as FILE.new - or replace them),
using the manifest the previous version left there (seqtool/bootstrap.py).

How to run the .pyz (Python 3.10+ is needed, as for seqtool itself; numpy is offered
for installation if it is missing):
    Linux:    chmod +x seqtool-0.19.3.pyz; ./seqtool-0.19.3.pyz      (any seqtool arguments follow)
    Windows:  double-click it (the Python installer links .pyz files to Python),
              or: py seqtool-0.19.3.pyz
Its own options: --unpack-only, --unpack-to DIR, --where.

--exe (experimental, not tested yet) also wraps it as a stand-alone program with
PyInstaller, which must be installed and which builds for the system it runs on
(run it on Windows for a .exe). That program still uses the Python installed on
the computer to run seqtool, since seqtool installs optional packages with pip.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipapp
from pathlib import Path

from .common.log import good, info, warn
from .common.paths import arg as paths_arg, show

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {"__pycache__", ".git", ".pytest_cache", "seqtool-prefs", "seqtool-demo", "seqtool-out", "dist", "build"}
SKIP_EXT = {".pyc", ".pyo", ".pyz", ".zip", ".exe"}


def files(root: Path = ROOT, tests: bool = False) -> list[Path]:
    """What goes in the package. tests/ only on request: its fixtures hold parts of your
    own show (a trimmed layout, a training file), not something to hand out."""
    out = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if p.is_dir() or any(part in SKIP_DIRS or part.endswith("-seqtool") for part in rel.parts[:-1]):
            continue
        if not tests and rel.parts[0] == "tests":
            continue
        if p.suffix in SKIP_EXT or p.name in (".seqtool-manifest.json", "HANDOFF.md", "DESIGN-addendum.md") or p.name.endswith((".new", ".old")):
            continue
        out.append(p)
    return out


def build(out_dir: Path, root: Path = ROOT, tests: bool = False) -> Path:
    version = (root / "VERSION").read_text().strip()
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        man = {"version": version, "files": {}}
        for p in files(root, tests):
            rel = p.relative_to(root).as_posix()
            data = p.read_bytes()
            man["files"][rel] = hashlib.sha256(data).hexdigest()
            dst = t / "payload" / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(data)
        (t / "payload" / ".seqtool-manifest.json").write_text(json.dumps(man, indent=1), encoding="utf-8")
        shutil.copy(root / "seqtool" / "bootstrap.py", t / "__main__.py")
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / f"seqtool-{version}.pyz"
        zipapp.create_archive(t, target, interpreter="/usr/bin/env python3", compressed=True)
    target.chmod(0o755)
    return target


def build_exe(pyz: Path) -> Path | None:
    import importlib.util
    if importlib.util.find_spec("PyInstaller") is None:
        warn("--exe needs PyInstaller ('pip install pyinstaller'), on the system to build for (Windows for a .exe)")
        return None
    import zipfile
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        payload = t / "payload.zip"
        with zipfile.ZipFile(pyz) as src, zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as dst:
            for n in src.namelist():
                if n.startswith("payload/"):
                    dst.writestr(n, src.read(n))
        sep = ";" if sys.platform.startswith("win") else ":"
        name = pyz.stem
        rc = subprocess.call([sys.executable, "-m", "PyInstaller", "--onefile", "--console", "--name", name,
                              "--add-data", f"{payload}{sep}.", "--distpath", str(pyz.parent),
                              "--workpath", str(t / "build"), "--specpath", str(t),
                              str(ROOT / "seqtool" / "bootstrap.py")])
    exe = pyz.with_suffix(".exe" if sys.platform.startswith("win") else "")
    if rc != 0 or not exe.exists():
        warn("PyInstaller failed - the .pyz works on its own")
        return None
    return exe


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="seqtool package", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=paths_arg, default=None, help="folder for the package (default: dist/ in seqtool's folder)")
    ap.add_argument("--with-tests", action="store_true", help="include tests/ (its fixtures hold parts of your own show)")
    ap.add_argument("--exe", action="store_true", help="also a stand-alone program via PyInstaller (experimental)")
    a = ap.parse_args(argv)
    out = a.out or ROOT / "dist"
    pyz = build(out, tests=a.with_tests)
    n = len(json.loads(__import__("zipfile").ZipFile(pyz).read("payload/.seqtool-manifest.json"))["files"])
    good(f"wrote {show(pyz)} ({pyz.stat().st_size / 1e6:.1f} MB, {n} files)")
    info(f"  Linux: '{pyz.name}' runs as it is ({{do}}./{pyz.name}{{/}}); Windows: double-click it, or "
         f"{{do}}py {pyz.name}{{/}} - the files are unpacked next to it, in a 'seqtool' folder")
    if a.exe:
        exe = build_exe(pyz)
        if exe:
            good(f"wrote {show(exe)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
