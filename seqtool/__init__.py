"""seqtool - music-to-light-sequence toolchain.

The version lives in the top-level VERSION file. Bump MINOR (0.x.0) for every
major update (new/changed analysis, scoring or output behaviour) - artifacts
made by an older MAJOR.MINOR are reported as stale. Bump PATCH for fixes that
do not change results.
"""
from pathlib import Path as _Path

try:
    __version__ = (_Path(__file__).resolve().parents[1] / "VERSION").read_text().strip()
except OSError:          # installed without the VERSION file
    __version__ = "0.24.58"
