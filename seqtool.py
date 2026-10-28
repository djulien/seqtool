#!/usr/bin/env python3
"""Launcher: ./seqtool.py <command> [options]   (no arguments = usage, -demo = demo, --test = unit tests)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from seqtool.__main__ import main  # noqa: E402

try:
    sys.exit(main())
except BrokenPipeError:
    sys.exit(0)
