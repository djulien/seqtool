#!/usr/bin/env python3
"""fseqdump - what a rendered .fseq holds, channel by channel (a stand-alone tool, MIT licence).

Reads the channel data xLights renders and FPP plays, following FPP's FSEQFile.cpp: versions 1
and 2, ESEQ, uncompressed / zstd / zlib in blocks of frames, sparse channel ranges, the media and
producer headers. Python 3.9+, nothing else needed - except for zstd-compressed files (xLights'
default): the 'zstandard' package (pip install zstandard) or the zstd command-line tool.

    python fseqdump.py Song.fseq                        what it holds
    python fseqdump.py Song.fseq --start 1 --count 30   channels 1-30 (numbered from 1, as xLights'
                                                        absolute start channels), hex, one line a frame
        --from 12.5 --to 14 | --frames 40               a time (s or m:ss.s) / that many frames
        --every 4                                       every 4th frame
        --json [OUT.json]                               JSON instead (default: <file>-fseqdump/):
            {"file", "frame_ms", "start", "count", "frames": [{"frame", "t", "data": [0-255, ...]}]}
        --all                                           every frame on the screen (else it stops at 200)

As a module: FseqFile(path).info(), .frame(n), .channels(n, start0, count).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

import shutil
import struct
import subprocess
import zlib
from pathlib import Path


def _u16(b, i): return struct.unpack_from("<H", b, i)[0]
def _u32(b, i): return struct.unpack_from("<I", b, i)[0]
def _u24(b, i): return b[i] | (b[i + 1] << 8) | (b[i + 2] << 16)


class FseqError(ValueError):
    pass


class FseqFile:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.size = self.path.stat().st_size
        with open(self.path, "rb") as f:
            peek = f.read(8)
            if len(peek) < 8 or peek[1:4] != b"SEQ" or chr(peek[0]) not in "PFE":
                raise FseqError(f"{self.path.name} is not an .fseq file (it doesn't start with PSEQ / FSEQ / ESEQ)")
            if peek[0] == ord("E"):
                self.data_offset, self.major, self.minor = 20, 2, 0
            else:
                self.data_offset, self.minor, self.major = _u16(peek, 4), peek[6], peek[7]
            f.seek(0)
            h = f.read(self.data_offset)
        self.header = h
        self.compression = "none"
        self.blocks: list[tuple[int, int]] = []          # (first frame, file offset), sentinel last
        self.ranges: list[tuple[int, int]] = []          # sparse (start channel 0-based, count)
        self.variables: dict[str, object] = {}
        if peek[0] == ord("E"):
            self.kind = "ESEQ"
            self.channel_count = _u32(h, 8)
            self.step_ms = 50
            self.frames = (self.size - self.data_offset) // max(1, self.channel_count)
            start, n = _u32(h, 12), _u32(h, 16)
            self.ranges = [(start - 1 if start else 0, n)]
        else:
            self.kind = "FSEQ v%d.%d" % (self.major, self.minor)
            self.channel_count = _u32(h, 10)
            self.frames = _u32(h, 14)
            self.step_ms = h[18]
            if self.major == 1:
                self._variables(h, 28)
            elif self.major == 2:
                self.compression = {0: "none", 1: "zstd", 2: "zlib"}.get(h[20] & 0x0F, f"unknown ({h[20] & 0x0F})")
                pos, off = 32, self.data_offset
                nblocks = ((h[20] & 0xF0) << 4) | h[21]
                for _ in range(nblocks):
                    first, length = _u32(h, pos), _u32(h, pos + 4)
                    if length > 0:
                        self.blocks.append((first, off))
                        off += length
                    pos += 8
                if self.compression == "none" or not self.blocks:
                    self.blocks = [(0, self.data_offset)]
                self.blocks.append((self.frames + 2, self.size))
                for _ in range(h[22]):
                    self.ranges.append((_u24(h, pos), _u24(h, pos + 3)))
                    pos += 6
                self._variables(h, pos)
                ext = [v for v in self.variables.values() if isinstance(v, dict) and "offset" in v]
                for v in ext:                            # extended data sits after the channel data
                    if v["offset"] < self.blocks[-1][1]:
                        self.blocks[-1] = (self.blocks[-1][0], v["offset"])
            else:
                raise FseqError(f"{self.path.name}: unknown .fseq version {self.major}.{self.minor}")
        self._cache: tuple[int, bytes] | None = None

    def _variables(self, h: bytes, i: int) -> None:
        while i + 4 < len(h):
            n, code = _u16(h, i), h[i + 2:i + 4].decode("latin-1")
            i += 4
            if n <= 4:
                continue
            if code == "ED":                                # extended: the data is elsewhere in the file
                code = h[i:i + 2].decode("latin-1")
                off, ln = struct.unpack_from("<QI", h, i + 2)
                self.variables[code] = {"offset": off, "length": ln}
                i += 14
                continue
            data = h[i:i + n - 4]
            i += n - 4
            if code in ("mf", "sp"):
                self.variables[code] = data.split(b"\0", 1)[0].decode("utf-8", "replace")
            else:
                self.variables[code] = f"{len(data)} bytes"

    # ------------------------------------------------------------------ frames
    def info(self) -> dict:
        return {"file": str(self.path), "format": self.kind, "compression": self.compression,
                "channels": self.channel_count, "frames": self.frames, "frame_ms": self.step_ms,
                "duration_s": round(self.frames * self.step_ms / 1000, 3),
                "blocks": max(0, len(self.blocks) - 1), "sparse_ranges": [[a + 1, n] for a, n in self.ranges],
                "media": self.variables.get("mf"), "producer": self.variables.get("sp"),
                "variable_headers": sorted(self.variables)}

    def _block_of(self, frame: int) -> int:
        k = 0
        while k + 1 < len(self.blocks) and frame >= self.blocks[k + 1][0]:
            k += 1
        return k

    def _block_data(self, k: int) -> bytes:
        if self._cache and self._cache[0] == k:
            return self._cache[1]
        a, b = self.blocks[k][1], self.blocks[k + 1][1]
        with open(self.path, "rb") as f:
            f.seek(a)
            raw = f.read(b - a)
        if self.compression == "zstd":
            data = _unzstd(raw)
        elif self.compression == "zlib":
            data = zlib.decompressobj().decompress(raw)
        else:
            data = raw
        self._cache = (k, data)
        return data

    def frame(self, n: int) -> bytes:
        """The frame's channel data as stored (channel_count bytes; sparse: the ranges one after another)."""
        if not 0 <= n < self.frames:
            raise FseqError(f"frame {n} is outside the sequence (0 to {self.frames - 1})")
        cc = self.channel_count
        if self.major == 1 or self.kind == "ESEQ" or self.compression == "none":
            with open(self.path, "rb") as f:
                f.seek(self.data_offset + n * cc)
                return f.read(cc).ljust(cc, b"\0")
        k = self._block_of(n)
        data = self._block_data(k)
        i = (n - self.blocks[k][0]) * cc
        return data[i:i + cc].ljust(cc, b"\0")

    def channels(self, n: int, start: int, count: int) -> bytes:
        """Channels start .. start+count-1 (0-based, absolute) in frame n; channels the file
        doesn't hold (outside its sparse ranges) are 0."""
        fr = self.frame(n)
        if not self.ranges:
            out = fr[start:start + count]
            return out.ljust(count, b"\0")
        out = bytearray(count)
        pos = 0
        for a, ln in self.ranges:
            lo, hi = max(a, start), min(a + ln, start + count)
            if lo < hi:
                out[lo - start:hi - start] = fr[pos + lo - a:pos + hi - a]
            pos += ln
        return bytes(out)


def _unzstd(raw: bytes) -> bytes:
    try:
        import zstandard
        return _zread(zstandard, raw)
    except ImportError:
        pass
    exe = shutil.which("zstd")
    if exe:
        return subprocess.run([exe, "-d", "-c", "-q"], input=raw, capture_output=True, check=True).stdout
    if _offer_install():
        import importlib
        importlib.invalidate_caches()
        import zstandard
        return _zread(zstandard, raw)
    raise FseqError("this .fseq is zstd-compressed (xLights' default): install the 'zstandard' package "
                    "(pip install zstandard) or the zstd tool - or save the sequence uncompressed or with zlib "
                    "(xLights: Preferences > Output > FSEQ version)")


_OFFERED = []


def _offer_install() -> bool:
    """On a terminal, offer once to install the 'zstandard' package (MIT/BSD) with pip. xLights'
    own zstd library is inside xLights and can't be used from Python, so it doesn't help here."""
    import os
    if _OFFERED or not sys.stdin.isatty() or os.environ.get("SEQTOOL_NONINTERACTIVE"):
        return False
    _OFFERED.append(1)
    cmd = [sys.executable, "-m", "pip", "install", "zstandard"]
    try:
        ans = input("this .fseq is zstd-compressed and the 'zstandard' package isn't installed - install it now "
                    f"({' '.join(cmd[1:])})? [y/N] ").strip().lower()
    except EOFError:
        return False
    if ans not in ("y", "yes"):
        return False
    if subprocess.run(cmd).returncode != 0:
        print("pip couldn't install it - try 'python -m pip install --user zstandard'", file=sys.stderr)
        return False
    try:
        import zstandard  # noqa: F401
        return True
    except ImportError:
        return False


def _zread(zstandard, raw: bytes) -> bytes:
    import io
    with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(raw), read_across_frames=True) as r:
        return r.read()


SHOW_MAX = 200


def _t(text: str) -> float:
    t = text.lstrip("@")
    if ":" in t:
        m, s = t.split(":", 1)
        return int(m) * 60 + float(s)
    return float(t)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="fseqdump", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", help="the .fseq")
    ap.add_argument("--start", type=int, default=None, help="first channel, numbered from 1")
    ap.add_argument("--count", type=int, default=None, help="how many channels (default 3: one RGB pixel)")
    ap.add_argument("--from", dest="t0", default=None, help="start time (s or m:ss.s; default 0)")
    ap.add_argument("--to", dest="t1", default=None, help="end time")
    ap.add_argument("--frames", type=int, default=None, help="this many frames from --from")
    ap.add_argument("--every", type=int, default=1, help="every K-th frame")
    ap.add_argument("--json", nargs="?", const="", default=None, metavar="OUT", help="write JSON (default: <file>-fseqdump/)")
    ap.add_argument("--all", action="store_true", help="show every frame (the dump stops at 200 without it)")
    a = ap.parse_args(argv)
    f = Path(os.path.expanduser(a.file))
    if any(ch in a.file for ch in "*?["):                 # wildcards
        hits = sorted(Path(p) for p in glob.glob(os.path.expanduser(a.file)))
        if len(hits) > 1:
            raise SystemExit("fseqdump: " + a.file + " matches " + str(len(hits)) + " files - name one:\n  "
                             + "\n  ".join(str(h) for h in hits[:20]))
        f = hits[0] if hits else f
    if not f.is_file():
        raise SystemExit(f"fseqdump: no file {f} - e.g. 'python fseqdump.py ~/xLights/show/Song.fseq'")
    try:
        fs = FseqFile(f)
    except FseqError as e:
        raise SystemExit(f"fseqdump: {e}") from None
    inf = fs.info()
    if a.start is None and a.count is None and a.json is None:
        print(f"{f.name}: {inf['format']}, {inf['compression']}"
              + (f" ({inf['blocks']} blocks)" if inf["compression"] != "none" else ""))
        print(f"  {inf['channels']} channels, {inf['frames']} frames of {inf['frame_ms']} ms = {inf['duration_s']} s")
        if inf["sparse_ranges"]:
            print("  holds only channels " + ", ".join(f"{s}-{s + n - 1}" for s, n in inf["sparse_ranges"]))
        if inf["media"]:
            print(f"  media: {inf['media']}")
        if inf["producer"]:
            print(f"  made by: {inf['producer']}")
        print("channels: 'python fseqdump.py FILE --start CH --count N [--from T --to T] [--json]'")
        return 0
    start = (a.start or 1)
    if start < 1:
        raise SystemExit("fseqdump --start: channels are numbered from 1 - e.g. --start 1")
    count = a.count or 3
    step = inf["frame_ms"] / 1000 or 0.05
    f0 = int(round(_t(a.t0) / step)) if a.t0 else 0
    f1 = (f0 + a.frames) if a.frames else (int(round(_t(a.t1) / step)) + 1 if a.t1 else fs.frames)
    f0, f1 = max(0, f0), min(fs.frames, f1)
    if f0 >= f1:
        raise SystemExit(f"fseqdump: no frames there - the sequence is {inf['duration_s']} s ({fs.frames} frames)")
    frames = range(f0, f1, max(1, a.every))
    if a.json is not None:
        out = Path(a.json) if a.json else f.parent / f"{f.stem}-fseqdump" / f"{f.stem}.ch{start}-{start + count - 1}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        doc = {"file": str(f), "frame_ms": inf["frame_ms"], "start": start, "count": count,
               "frames": []}
        for k, n in enumerate(frames):
            doc["frames"].append({"frame": n, "t": round(n * step, 3), "data": list(fs.channels(n, start - 1, count))})
            if k and k % 2000 == 0:
                print(f"  {k} of {len(frames)} frames ...", file=sys.stderr)
        out.write_text(json.dumps(doc, separators=(",", ":")) + "\n", encoding="utf-8")
        print(f"wrote {out}: channels {start}-{start + count - 1}, {len(doc['frames'])} frames "
             f"({frames.start * step:.2f}-{(frames[-1]) * step:.2f} s)")
        return 0
    print(f"{f.name} channels {start}-{start + count - 1}, frames {f0}-{f1 - 1} "
          f"({f0 * step:.2f}-{(f1 - 1) * step:.2f} s, {inf['frame_ms']} ms each)")
    for k, n in enumerate(frames):
        if k >= SHOW_MAX and not a.all:
            print(f"... {len(frames) - k} more frames ('--all' shows them, '--json' writes them)")
            break
        d = fs.channels(n, start - 1, count)
        hx = " ".join(d[i:i + 3].hex() for i in range(0, len(d), 3))
        print(f"  {n * step:9.3f} s  #{n:<6} {hx}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
