"""The app icon (0.24.58): favicon.svg (tab-size drawing) and lightbench-32.png put into a page's <head> as data: URIs, so the GUI (which wants its token on every
request) and the stand-alone timeline page need no icon request of their own."""
from __future__ import annotations

import base64
from pathlib import Path

HERE = Path(__file__).parent


def head_links() -> str:
    out = []
    try:
        svg = (HERE / "favicon.svg").read_bytes()
        out.append('<link rel="icon" type="image/svg+xml" href="data:image/svg+xml;base64,'
                   + base64.b64encode(svg).decode() + '">')
        png = (HERE / "lightbench-32.png").read_bytes()
        out.append('<link rel="icon" type="image/png" sizes="32x32" href="data:image/png;base64,'
                   + base64.b64encode(png).decode() + '">')
    except OSError:
        pass
    return "\n".join(out)

# favicon.ico and apple-touch-icon.png are kept for an installed app / a desktop shortcut.
