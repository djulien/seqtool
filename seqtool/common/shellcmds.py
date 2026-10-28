# seqtool-command: pwd | cmd_pwd | tools | where relative paths start, and the folders seqtool uses
# seqtool-command: cd | cmd_cd | tools | change the working folder: cd FOLDER (glob ok)
# seqtool-command: memory | cmd_memory | tools | system memory and seqtool's own use (change since last 'memory')
"""Small shell commands: pwd, cd, memory."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_prev_rss: int | None = None


def fmt_bytes(n: float) -> str:
    """>= 1 GB: GB with one decimal; otherwise MB with one decimal; '.0' dropped."""
    sign = "-" if n < 0 else ""
    n = abs(n)
    gb, mb = n / 1024 ** 3, n / 1024 ** 2
    val, unit = (gb, "GB") if gb >= 1 else (mb, "MB")
    txt = f"{val:.1f}"
    if txt.endswith(".0"):
        txt = txt[:-2]
    return f"{sign}{txt} {unit}"


def system_memory() -> tuple[int | None, int | None]:
    """(total, available) bytes."""
    try:
        if sys.platform.startswith("linux"):
            info = {}
            for line in Path("/proc/meminfo").read_text().splitlines():
                k, v = line.split(":", 1)
                info[k] = int(v.split()[0]) * 1024
            return info.get("MemTotal"), info.get("MemAvailable", info.get("MemFree"))
        if sys.platform == "darwin":
            total = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"]).strip())
            vm = subprocess.check_output(["vm_stat"], text=True)
            page = int(vm.split("page size of")[1].split()[0])
            pages = {l.split(":")[0]: int(l.split(":")[1].strip().rstrip(".")) for l in vm.splitlines()[1:] if ":" in l}
            free = sum(pages.get(k, 0) for k in ("Pages free", "Pages inactive", "Pages speculative"))
            return total, free * page
        if os.name == "nt":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            ms = MS()
            ms.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
            return ms.ullTotalPhys, ms.ullAvailPhys
    except Exception:
        pass
    try:
        import psutil  # optional
        vm = psutil.virtual_memory()
        return vm.total, vm.available
    except Exception:
        return None, None


def process_memory() -> tuple[int | None, int | None]:
    """(current resident, peak resident) bytes for this process."""
    try:
        if sys.platform.startswith("linux"):
            st = {l.split(":")[0]: l.split(":")[1] for l in Path("/proc/self/status").read_text().splitlines()
                  if ":" in l}
            return int(st["VmRSS"].split()[0]) * 1024, int(st["VmHWM"].split()[0]) * 1024
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss          # bytes on macOS
        cur = int(subprocess.check_output(["ps", "-o", "rss=", "-p", str(os.getpid())]).strip()) * 1024
        return cur, peak
    except Exception:
        pass
    try:
        import psutil
        mi = psutil.Process().memory_info()
        return mi.rss, getattr(mi, "peak_wset", None)
    except Exception:
        return None, None


def cmd_memory(argv=None) -> int:
    global _prev_rss
    total, avail = system_memory()
    rss, peak = process_memory()
    if total:
        print(f"system:  {fmt_bytes(avail)} available of {fmt_bytes(total)}")
    if rss:
        line = f"seqtool: {fmt_bytes(rss)} in use"
        if peak:
            line += f" (peak {fmt_bytes(peak)})"
        if _prev_rss is not None:
            d = rss - _prev_rss
            line += f", {'+' if d >= 0 else ''}{fmt_bytes(d)} since the last 'memory'"
        print(line)
        _prev_rss = rss
    if not total and not rss:
        print("memory information is not available on this system")
    return 0


def cmd_pwd(argv=None) -> int:
    from . import config
    from .paths import show
    print(f"working folder: {Path.cwd()}{os.sep}   (relative paths start here)")
    rows = [("preferences", config.user_dir())]
    last_out, last_audio, kit = config.answer("last_out"), config.answer("last_audio"), config.answer("kit_dir")
    if last_audio:
        rows.append(("last song", Path(last_audio)))
    if last_out:
        rows.append(("last results", Path(last_out)))
    try:
        from ..layout.store import source_info
        src = source_info()
        if src:
            rows.append(("show layout", Path(src["path"])))
    except Exception:
        pass
    if kit:
        rows.append(("kit folder", Path(kit)))
    for k, v in rows:
        print(f"  {k + ':':<14} {show(v)}")
    return 0


def cmd_cd(argv=None) -> int:
    from .paths import expand
    from .prompt import ask
    target = " ".join(argv or []) or ask("cd: folder?", str(Path.home()), complete="dir")
    p = expand(target, "dir")
    try:
        os.chdir(p)
    except OSError as e:
        raise SystemExit(f"cd: {e.strerror}: {p}")
    print(f"{Path.cwd()}{os.sep}")
    return 0


def to_clipboard(text: str) -> str | None:
    """Put text on the system clipboard with whatever tool there is (wl-copy, xclip, xsel,
    pbcopy, clip). Returns the tool's name, or None."""
    import shutil
    import subprocess
    for cmd in (["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"],
                ["pbcopy"], ["clip.exe"], ["clip"]):
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, input=text.encode("utf-8"), check=True, timeout=5,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return cmd[0]
            except Exception:  # noqa: BLE001
                continue
    return None
