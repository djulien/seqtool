"""Optional-dependency loader with user prompting and on-demand pip install.

    torch = need("torch", purpose="vocal stem separation", pip="torch")

Behaviour is controlled globally (CLI flags --install / --no-install, or env
SEQTOOL_INSTALL=ask|yes|no). 'ask' prompts on a tty and declines otherwise, so
non-interactive pipelines never hang. Required packages raise MissingDependency
when declined; optional ones return None and the stage degrades gracefully.
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import shutil
import subprocess
import sys

from .log import error, good, info, warn

_mode = os.environ.get("SEQTOOL_INSTALL", "ask")   # ask | yes | no
_declined: set[str] = set()


class MissingDependency(RuntimeError):
    pass


def set_mode(mode: str) -> None:
    global _mode
    assert mode in ("ask", "yes", "no")
    _mode = mode


def _confirm(question: str) -> bool:
    if _mode == "yes":
        return True
    if _mode == "no":
        return False
    from .prompt import ask
    return ask(f"{question} [y/N]", "n", show_default=False).lower() in ("y", "yes")


def confirm_download(question: str) -> bool:
    """Yes by default on a terminal or in the GUI; follows --install=yes|no (tests: no)."""
    if _mode in ("yes", "no"):
        return _mode == "yes"
    from .prompt import ask
    return ask(f"{question} [Y/n]", "y", show_default=False).lower() not in ("n", "no")


def ask_yes_no(question: str, default: bool) -> bool:
    """A yes/no question; follows --install=yes|no (tests: no)."""
    if _mode in ("yes", "no"):
        return _mode == "yes"
    from .prompt import ask
    ans = ask(f"{question} [{'Y/n' if default else 'y/N'}]", "y" if default else "n", show_default=False)
    return ans.lower() in ("y", "yes")


def installed(module: str) -> bool:
    """Is the package there? (without importing it - torch and friends are heavy)"""
    importlib.invalidate_caches()
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def offer_restart(why: str) -> None:
    """A package installed while seqtool runs sometimes can't be loaded until seqtool
    starts again. On a terminal: offer to restart with the same command line."""
    from .prompt import ask, gui_asker, interactive
    warn(why)
    if gui_asker() is not None or not interactive():
        info("  quit seqtool and start it again, then repeat the command")
        return
    if ask("Restart seqtool now (same command line)? [Y/n]", "y", show_default=False).lower() in ("n", "no"):
        info("  later: quit seqtool and start it again, then repeat the command")
        return
    info("restarting seqtool ...")
    sys.stdout.flush()
    sys.stderr.flush()
    argv = list(getattr(sys, "orig_argv", [sys.executable, *sys.argv]))
    os.execv(sys.executable, argv)


def need(module: str, *, purpose: str, pip: str | None = None, required: bool = False, load: bool = True):
    """The module (load=True) or True (load=False: only check it is installed, e.g. a
    tool that runs as its own process), installing it with pip after asking."""
    def have():
        if not load:
            return True if installed(module) else None
        try:
            return importlib.import_module(module)
        except ImportError:
            return None
    got = have()
    if got is not None:
        return got
    pkg = pip or module
    if pkg not in _declined and _confirm(f"'{pkg}' is needed for {purpose}. Install it now with pip?"):
        info(f"installing {pkg} (this can take a while) ...")
        cmd = [sys.executable, "-m", "pip", "install", pkg]
        if sys.prefix == sys.base_prefix and sys.platform.startswith("linux"):
            cmd.append("--break-system-packages")   # system python on recent distros
        if subprocess.call(cmd) == 0:
            good(f"installed {pkg}")
            got = have()
            if got is not None:
                return got
            offer_restart(f"{pkg} is installed, but this seqtool session can't load it yet")
            return None
        error(f"pip install {pkg} failed - try it yourself: '{sys.executable} -m pip install {pkg}'")
    _declined.add(pkg)
    msg = f"{pkg} not available ({purpose})"
    if required:
        raise MissingDependency(msg + f" - install with: pip install {pkg}")
    warn(msg + f"; continuing without it (to install it later: 'pip install {pkg}', or answer y next time)")
    return None


def need_exe(name: str, *, purpose: str, required: bool = False) -> str | None:
    path = shutil.which(name)
    if path is None:
        msg = f"'{name}' executable not found on PATH ({purpose})"
        if required:
            raise MissingDependency(msg)
        warn(msg)
    return path
