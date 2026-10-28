"""Mouth shapes from a pixel image of a face (0.19).

Generic: knows nothing about xLights. Given a face image and the size of the prop's
pixel grid, it finds the mouth and eyes, draws the 10 mouth shapes (AI, E, etc, FV,
L, MBP, O, U, WQ, rest) in place of the mouth, with eyes open and closed, and
returns the images. The xLights adapter names the files and writes the faceInfo.

Detection works on the image scaled to the grid: the background is the colour of
the corners (or transparent), the skin is the face's most common colour, and the
features are blobs of other colours inside the face. The mouth is the widest blob
in the lower half; the eyes are the best matching pair above it. Both can be given
instead (`--mouth x,y,w,h`, `--eyes x,y,w,h/x,y,w,h`, in grid pixels).
"""
from __future__ import annotations

from dataclasses import dataclass, field

MOUTHS = ["AI", "E", "etc", "FV", "L", "MBP", "O", "U", "WQ", "rest"]

# width and opening as fractions of the face's own mouth width; round = O-like ring;
# teeth/tongue rows; built-in shapes, overridable with preferences faces.mouth_shapes
SHAPES = {
    "rest": {"w": 0.90, "h": 0.00},
    "MBP":  {"w": 0.70, "h": 0.00, "thick": 1},
    "etc":  {"w": 0.85, "h": 0.18, "teeth": "top"},
    "E":    {"w": 1.00, "h": 0.22, "teeth": "both"},
    "AI":   {"w": 0.90, "h": 0.50, "teeth": "top", "beyond": 1},
    "O":    {"w": 0.60, "h": 0.55, "round": True, "beyond": 1},
    "U":    {"w": 0.45, "h": 0.40, "round": True, "beyond": 1},
    "WQ":   {"w": 0.30, "h": 0.30, "round": True},
    "FV":   {"w": 0.85, "h": 0.20, "teeth": "top", "lip": True},
    "L":    {"w": 0.80, "h": 0.40, "tongue": True, "beyond": 1},
}

TEETH = (255, 255, 255, 255)
TONGUE = (225, 95, 120, 255)


@dataclass
class Box:
    x: int
    y: int
    w: int
    h: int

    @property
    def cx(self) -> float:
        return self.x + (self.w - 1) / 2

    @property
    def cy(self) -> float:
        return self.y + (self.h - 1) / 2

    def text(self) -> str:
        return f"{self.x},{self.y},{self.w},{self.h}"


@dataclass
class Face:
    size: tuple[int, int]
    mouth: Box | None = None
    eyes: list[Box] = field(default_factory=list)
    skin: tuple = (0, 0, 0, 255)
    mouth_color: tuple = (0, 0, 0, 255)
    mouth_guessed: bool = False
    eye_color: tuple = (0, 0, 0, 255)
    teeth_color: tuple = TEETH
    tongue_color: tuple = TONGUE
    notes: list[str] = field(default_factory=list)
    # 0.20.7: the exact pixels the user marked in the viewer (--marks), and colours picked there
    mouth_px: set | None = None
    eye_px: list = field(default_factory=list)
    lid_color: tuple | None = None
    eyeball_color: tuple | None = None
    pupil_color: tuple | None = None
    blank: object = None                                   # the face with no eyes or mouth (built)


def parse_box(text: str) -> Box:
    x, y, w, h = (int(v) for v in text.split(","))
    return Box(x, y, w, h)


def grid_transform(size: tuple[int, int], cols: int, rows: int) -> tuple[float, int, int]:
    """(scale, x offset, y offset) that to_grid uses."""
    if tuple(size) == (cols, rows):
        return 1.0, 0, 0
    f = min(cols / size[0], rows / size[1])
    w, h = max(1, round(size[0] * f)), max(1, round(size[1] * f))
    return f, (cols - w) // 2, (rows - h) // 2


def to_grid_box(b: Box, t: tuple[float, int, int]) -> Box:
    """A box found on the original image, on the grid."""
    f, ox, oy = t
    x0, y0 = int(b.x * f) + ox, int(b.y * f) + oy
    x1, y1 = int(round((b.x + b.w) * f)) + ox, int(round((b.y + b.h) * f)) + oy
    return Box(x0, y0, max(1, x1 - x0), max(1, y1 - y0))


def detect_scaled(src, grid, cols: int, rows: int, mouth: Box | None = None, eyes: list | None = None,
                  trace: list | None = None) -> Face:
    """Detection on the original image when it is bigger than the grid (small features
    survive there), the boxes then moved onto the grid; colours from the grid."""
    src = src.convert("RGBA")
    if src.width <= cols and src.height <= rows or (mouth is not None and eyes is not None):
        if trace is not None:
            trace.append(f"searching the image on the {cols}x{rows} grid")
        return detect(grid, mouth, eyes, trace)
    if trace is not None:
        trace.append(f"the image ({src.width}x{src.height}) is bigger than the grid ({cols}x{rows}): searching it at "
                     "its own size, then moving the boxes onto the grid")
    big = detect(src, None, None, trace)
    t = grid_transform(src.size, cols, rows)
    if trace is not None:
        trace.append(f"on the grid (scale {t[0]:.3f}, offset {t[1]},{t[2]}):")
    face = detect(grid, mouth or (to_grid_box(big.mouth, t) if big.mouth and not big.mouth_guessed else None),
                  eyes if eyes is not None else ([to_grid_box(b, t) for b in big.eyes] if big.eyes else None), trace)
    face.notes = [n for n in face.notes if not (n.startswith("no mouth") and big.mouth and not big.mouth_guessed)]
    return face


def to_grid(img, cols: int, rows: int):
    """The image on the prop's grid: scaled to fit (pixel art stays sharp), centred."""
    from PIL import Image
    img = img.convert("RGBA")
    if img.size == (cols, rows):
        return img
    f = min(cols / img.width, rows / img.height)
    w, h = max(1, round(img.width * f)), max(1, round(img.height * f))
    small = img.resize((w, h), Image.NEAREST if f >= 1 or _few_colors(img) else Image.BOX)
    out = Image.new("RGBA", (cols, rows), (0, 0, 0, 0))
    out.paste(small, ((cols - w) // 2, (rows - h) // 2))
    return out


def _few_colors(img) -> bool:
    return img.getcolors(256) is not None          # pixel art: keep hard edges


def _dist(a, b) -> float:
    return sum((x - y) ** 2 for x, y in zip(a[:3], b[:3])) ** 0.5


def _components(mask: list[list[bool]]):
    """4-connected blobs: [(pixels, Box)]."""
    H, W = len(mask), len(mask[0])
    seen = [[False] * W for _ in range(H)]
    out = []
    for y in range(H):
        for x in range(W):
            if not mask[y][x] or seen[y][x]:
                continue
            stack, px = [(x, y)], []
            seen[y][x] = True
            while stack:
                a, b = stack.pop()
                px.append((a, b))
                for c, d in ((a + 1, b), (a - 1, b), (a, b + 1), (a, b - 1)):
                    if 0 <= c < W and 0 <= d < H and mask[d][c] and not seen[d][c]:
                        seen[d][c] = True
                        stack.append((c, d))
            xs, ys = [p[0] for p in px], [p[1] for p in px]
            out.append((px, Box(min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1)))
    return out


def detect(img, mouth: Box | None = None, eyes: list[Box] | None = None, trace: list | None = None) -> Face:
    """Find the face's skin colour, eyes and mouth (0.19.4: eyes first, then the mouth
    below them - so a hat or a body under the face doesn't hide the mouth)."""
    W, H = img.size
    px = img.load()
    from collections import Counter
    # background: everything reachable from the edges through transparent pixels or the
    # edge's own colours (padding and a painted background alike; 0.19.4)
    border = [px[x, y] for x in range(W) for y in (0, H - 1)] + [px[x, y] for y in range(H) for x in (0, W - 1)]
    bgcols = [c for c, _ in Counter(c for c in border if c[3] >= 40).most_common(2)]

    def bgish(c):
        return c[3] < 40 or any(_dist(c, b) < 30 for b in bgcols)
    bgset, stack = set(), [(x, y) for x in range(W) for y in (0, H - 1)] + [(x, y) for y in range(H) for x in (0, W - 1)]
    while stack:
        x, y = stack.pop()
        if (x, y) in bgset or not (0 <= x < W and 0 <= y < H) or not bgish(px[x, y]):
            continue
        bgset.add((x, y))
        stack += [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
    face_px = [(x, y) for y in range(H) for x in range(W) if (x, y) not in bgset]
    f = Face(size=(W, H))
    if not face_px:
        f.notes.append("the image is empty (only background)")
        return f
    f.skin = Counter(px[x, y] for x, y in face_px).most_common(1)[0][0]
    T = trace.append if trace is not None else (lambda *_: None)
    T(f"image {W}x{H}; background colours at the edges {bgcols or 'transparent'}; {len(bgset)} background pixels, "
      f"{len(face_px)} face pixels; skin colour {f.skin}")
    inside = {(x, y) for x, y in face_px}
    fy0, fy1 = min(y for _, y in face_px), max(y for _, y in face_px)
    fx0, fx1 = min(x for x, _ in face_px), max(x for x, _ in face_px)
    fcx = sum(x for x, _ in face_px) / len(face_px)

    def blobs_at(limit):
        feat = [[(x, y) in inside and _dist(px[x, y], f.skin) > limit and
                 all((c, d) in inside for c, d in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))
                 for x in range(W)] for y in range(H)]
        return [(p, b) for p, b in _components(feat) if len(p) >= 1]
    def in_skin(b):                                   # eyes and mouth sit in the face: mostly skin round them
        ring = [(x, b.y - 1) for x in range(b.x - 1, b.x + b.w + 1)] + [(x, b.y + b.h) for x in range(b.x - 1, b.x + b.w + 1)] \
            + [(b.x - 1, y) for y in range(b.y, b.y + b.h)] + [(b.x + b.w, y) for y in range(b.y, b.y + b.h)]
        ok = [(x, y) for x, y in ring if 0 <= x < W and 0 <= y < H]
        return bool(ok) and sum(1 for x, y in ok if _dist(px[x, y], f.skin) <= 35) >= 0.6 * len(ok)
    raw = blobs_at(60)
    if not raw:
        T("no features at contrast 60 - trying 35")
        raw = blobs_at(35)
    for p_, b_ in raw:
        T(f"  feature at {b_.text()}: {len(p_)} px, colour {Counter(px[x, y] for x, y in p_).most_common(1)[0][0]}"
          + ("" if in_skin(b_) else "  - dropped: not surrounded by skin (a hat, a body, an outline?)"))
    blobs = [(p, b) for p, b in raw if in_skin(b)]   # faint features: lower contrast

    def colour(boxes):
        cols = [px[x, y] for b in boxes for y in range(b.y, b.y + b.h) for x in range(b.x, b.x + b.w)
                if 0 <= x < W and 0 <= y < H and _dist(px[x, y], f.skin) > 35]
        return Counter(cols).most_common(1)[0][0] if cols else (0, 0, 0, 255)

    if eyes is None:
        best, score = [], None
        top = fy0 + 0.75 * (fy1 - fy0)
        for i in range(len(blobs)):
            for j in range(i + 1, len(blobs)):
                (p1, a), (p2, b) = blobs[i], blobs[j]
                if a.cy > top or b.cy > top:
                    continue
                big, small = max(len(p1), len(p2)), min(len(p1), len(p2))
                apart = abs(a.cx - b.cx)
                if big > 3 * small or abs(a.cy - b.cy) > max(a.h, b.h) + 1 or apart < max(a.w, b.w):
                    continue
                s = (big - small) + abs(a.cy - b.cy) * 2 + abs((a.cx + b.cx) / 2 - fcx) * 0.5 - small
                T(f"  eye pair {a.text()} + {b.text()}: score {s:.1f} (lower is better)")
                if score is None or s < score:
                    best, score = [(p1, a), (p2, b)], s
        if best:
            eyes = sorted([b for _, b in best], key=lambda b: b.x)
            f.eye_color = Counter(px[x, y] for p, _ in best for x, y in p).most_common(1)[0][0]
        else:
            eyes = []
            f.notes.append("no pair of eyes found - closed eyes are left as open (give them with --eyes x,y,w,h/x,y,w,h)")
    else:
        f.eye_color = colour(eyes)
    f.eyes = eyes
    if mouth is None:
        if eyes:                                       # below the eyes, between them (give or take)
            ex0, ex1 = min(b.x for b in eyes), max(b.x + b.w for b in eyes)
            span = ex1 - ex0
            ebot = max(b.y + b.h for b in eyes)
            cand = [(p, b) for p, b in blobs if b.y >= ebot and ex0 - 0.5 * span <= b.cx <= ex1 + 0.5 * span
                    and b.w >= 2 and b not in eyes]
            pick = max(cand, key=lambda pb: (pb[1].w - 0.3 * (pb[1].y - ebot), -pb[1].y)) if cand else None
        else:
            mid = (fy0 + fy1) / 2
            cand = [(p, b) for p, b in blobs if b.cy > mid and b.w >= 2]
            pick = max(cand, key=lambda pb: (pb[1].w - 0.5 * abs(pb[1].cx - fcx), -pb[1].cy)) if cand else None
        T("  mouth candidates: " + (", ".join(b.text() for _, b in cand) or "none"))
        if pick:
            p, mouth = pick
            f.mouth_color = Counter(px[x, y] for x, y in p).most_common(1)[0][0]
        else:
            if eyes:
                cx = (min(b.x for b in eyes) + max(b.x + b.w for b in eyes)) / 2
                w = max(3, round(0.6 * (max(b.x + b.w for b in eyes) - min(b.x for b in eyes))))
                y = min(H - 2, round(max(b.y + b.h for b in eyes) + 0.9 * w))
            else:
                cx, w = fcx, max(3, round(0.35 * (fx1 - fx0)))
                y = round(fy0 + 0.72 * (fy1 - fy0))
            mouth = Box(round(cx - w / 2), y, w, 1)
            f.mouth_guessed = True
            f.notes.append(f"no mouth found - placing one at {mouth.text()} (see the boxes picture; give it with "
                           "--mouth x,y,w,h)")
            f.mouth_color = (40, 0, 0, 255) if sum(f.skin[:3]) > 300 else (255, 255, 255, 255)
    else:
        f.mouth_color = colour([mouth])
    f.mouth = mouth
    T(f"chosen: eyes {', '.join(b.text() for b in f.eyes) or 'none'}; mouth {mouth.text()}"
      + (" (guessed)" if f.mouth_guessed else ""))
    return f


def overlay(img, face: Face):
    """The base image enlarged, with a pixel ruler and boxes where the mouth (red) and
    eyes (cyan) are - to read coordinates for --mouth / --eyes."""
    from PIL import Image, ImageDraw, ImageFont
    W, H = img.size
    k = max(1, min(16, 900 // max(W, H)))
    m = 34
    try:
        font = ImageFont.load_default(size=15)          # Pillow 10.1+: a readable size
    except TypeError:
        font = ImageFont.load_default()
    out = Image.new("RGBA", (W * k + m + 6, H * k + m + 6), (24, 26, 30, 255))
    base = Image.alpha_composite(Image.new("RGBA", img.size, (0, 0, 0, 255)), img.convert("RGBA"))
    out.paste(base.resize((W * k, H * k), Image.NEAREST), (m, m))
    d = ImageDraw.Draw(out)
    step = 1 if W <= 32 else 5 if W <= 160 else 10
    if k >= 8:                                         # a faint pixel grid, blended over the picture
        layer = Image.new("RGBA", out.size, (0, 0, 0, 0))
        g = ImageDraw.Draw(layer)
        for x in range(W + 1):
            g.line([(m + x * k, m), (m + x * k, m + H * k)], fill=(128, 128, 128, 70))
        for y in range(H + 1):
            g.line([(m, m + y * k), (m + W * k, m + y * k)], fill=(128, 128, 128, 70))
        out = Image.alpha_composite(out, layer)
        d = ImageDraw.Draw(out)
    lab = max(step, 5 if W <= 64 else 10)
    for x in range(0, W, step):
        d.line([(m + x * k, m - (6 if x % lab == 0 else 3)), (m + x * k, m)], fill=(200, 200, 200, 255))
        if x % lab == 0:
            d.text((m + x * k + 1, 2), str(x), fill=(220, 220, 220, 255), font=font)
    for y in range(0, H, step):
        d.line([(m - (6 if y % lab == 0 else 3), m + y * k), (m, m + y * k)], fill=(200, 200, 200, 255))
        if y % lab == 0:
            d.text((1, m + y * k + 1), str(y), fill=(220, 220, 220, 255), font=font)

    def box(b, col, text):
        x0, y0 = m + b.x * k, m + b.y * k
        x1, y1 = m + (b.x + b.w) * k - 1, m + (b.y + b.h) * k - 1
        for t in range(max(2, k // 3)):
            d.rectangle([x0 - t, y0 - t, x1 + t, y1 + t], outline=col)
        tw = d.textlength(text, font=font) if hasattr(d, "textlength") else 8 * len(text)
        tx, ty = min(x0, out.width - tw - 4), y1 + 4
        d.rectangle([tx - 2, ty - 1, tx + tw + 2, ty + 17], fill=(0, 0, 0, 200))
        d.text((tx, ty), text, fill=col, font=font)
    for i, b in enumerate(face.eyes):
        box(b, (0, 230, 255, 255), f"eye {b.text()}")
    if face.mouth:
        box(face.mouth, (255, 60, 60, 255), f"mouth {face.mouth.text()}" + (" (guessed)" if face.mouth_guessed else ""))
    out.info["seqtool"] = {"cols": W, "rows": H, "k": k, "m": m,
                           "boxes": [{"label": f"eye {b.text()}", **b.__dict__} for b in face.eyes]
                           + ([{"label": f"mouth {face.mouth.text()}" + (" (guessed)" if face.mouth_guessed else ""),
                                **face.mouth.__dict__}] if face.mouth else [])}
    return out


def _lum(c) -> float:
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def _mean(cols) -> tuple:
    return tuple(round(sum(c[i] for c in cols) / len(cols)) for i in range(3)) + (255,)


def ring_colour(img, box: Box, width: int = 2, fallback=(0, 0, 0, 255)) -> tuple:
    """The average colour just outside a box (the user's rule, 0.19.6): what an eyelid or
    the skin round a mouth should be filled with - not the face's overall skin colour,
    and not the colours inside the box (the pupils)."""
    W, H = img.size
    px = img.load()
    cols = [px[x, y] for y in range(box.y - width, box.y + box.h + width)
            for x in range(box.x - width, box.x + box.w + width)
            if 0 <= x < W and 0 <= y < H and not (box.x <= x < box.x + box.w and box.y <= y < box.y + box.h)
            and px[x, y][3] >= 40]
    return _mean(cols) if cols else fallback


def mouth_colours(img, face: Face) -> None:
    """Lips, tongue and teeth from the mouth box (0.19.6, the user's rule): the darkest
    pixels in it are the lips or tongue, the lightest the teeth - each averaged; pixels
    like the skin round the mouth don't count."""
    if not face.mouth or face.mouth_guessed:
        return
    W, H = img.size
    px = img.load()
    b = face.mouth
    around = ring_colour(img, b, fallback=face.skin)
    cols = [px[x, y] for y in range(b.y, b.y + b.h) for x in range(b.x, b.x + b.w)
            if 0 <= x < W and 0 <= y < H and px[x, y][3] >= 40 and _dist(px[x, y], around) > 35]
    if not cols:
        return
    cols.sort(key=_lum)
    n = max(1, len(cols) // 3)
    dark = _mean(cols[:n])
    face.mouth_color = face.tongue_color = dark
    light = _mean(cols[-n:])
    if len(cols) >= 3 and _lum(light) - _lum(dark) > 60 and _dist(light, around) > 35:
        face.teeth_color = light


def _erase(img, box: Box, skin, grow: int = 1):
    """Paint a feature over with the skin colour (only inside the face)."""
    W, H = img.size
    px = img.load()
    for y in range(box.y - grow, box.y + box.h + grow):
        for x in range(box.x - grow, box.x + box.w + grow):
            if 0 <= x < W and 0 <= y < H and px[x, y][3] >= 40:
                px[x, y] = skin


def _ellipse(cx, cy, a, b):
    """Pixels inside an ellipse with half-axes a, b (pixel centres)."""
    out = set()
    for y in range(int(cy - b) - 1, int(cy + b) + 2):
        for x in range(int(cx - a) - 1, int(cx + a) + 2):
            if a > 0 and b > 0 and ((x - cx) / a) ** 2 + ((y - cy) / b) ** 2 <= 1.0 + 1e-9:
                out.add((x, y))
    return out


def draw_mouth(img, face: Face, mouth: str, shapes: dict | None = None):
    sh = {**SHAPES, **(shapes or {})}[mouth]
    W, H = img.size
    px = img.load()
    m = face.mouth
    base = max(m.w, 3)
    w = max(2, round(base * sh["w"]))
    lip = face.mouth_color
    inner = tuple(int(c * 0.25) for c in lip[:3]) + (255,)
    cx = m.cx
    cy = m.y + (m.h - 1) / 2

    # 0.22.3: a mouth marked pixel by pixel (3 or more rows) keeps every shape inside the marked
    # pixels - the user's marks are where the mouth may go; a line of lips only lets it open below
    marked = set(face.mouth_px) if face.mouth_px and m.h >= 3 else None
    g = int(sh.get("beyond", 0)) if marked and sh["h"] > 0 else 0
    if g:                                    # 0.24.25: a wide-open mouth may go 'beyond' px past the marks
        for _ in range(g):
            marked |= {(x + dx, y + dy) for x, y in marked for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))}
        w = max(w, round((m.w + 2 * g) * sh["w"]))

    def put(x, y, c):
        if 0 <= x < W and 0 <= y < H and px[x, y][3] >= 40 and (marked is None or (x, y) in marked):
            px[x, y] = c
    if sh["h"] <= 0:                                        # closed: a line (pressed lips: thicker)
        thick = max(1, round(base / 12)) + sh.get("thick", 0)
        x0 = round(cx - (w - 1) / 2)
        for t in range(thick):
            for x in range(x0, x0 + w):
                put(x, round(cy) + t, lip)
        return
    h = max(3, round(base * sh["h"]))                       # open: lips round an inside
    top = round(cy - h * 0.3)                              # the jaw drops: most of the opening is below
    if marked:                               # 0.24.25: the open ones use the marked height (and 'beyond')
        hm = m.h + 2 * g
        h = min(max(h, round(hm * min(1.0, sh["h"] / 0.5))), hm)
        top = min(max(top, m.y - g), m.y + m.h + g - h)
    a, b = (w - 1) / 2, (h - 1) / 2
    ccx, ccy = cx, top + b
    outer = _ellipse(ccx, ccy, a + 0.5, b + 0.5) if sh.get("round") else \
        {(x, y) for y in range(top, top + h) for x in range(round(cx - a), round(cx - a) + w)
         if not (y in (top, top + h - 1) and x in (round(cx - a), round(cx - a) + w - 1))}
    inside = {(x, y) for x, y in outer if all(q in outer for q in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))}
    for x, y in outer:
        put(x, y, lip)
    for x, y in inside:
        put(x, y, inner)
    if inside:
        ys = sorted({y for _, y in inside})
        if sh.get("teeth") in ("top", "both"):
            for x, y in inside:
                if y == ys[0]:
                    put(x, y, face.teeth_color)
        if sh.get("teeth") == "both" and len(ys) > 1:
            for x, y in inside:
                if y == ys[-1]:
                    put(x, y, face.teeth_color)
        if sh.get("tongue"):                               # L: the tongue tip up behind the teeth
            xs = sorted({x for x, _ in inside})
            mid = xs[len(xs) // 2]
            for x, y in inside:
                if abs(x - mid) <= max(0, len(xs) // 4 - 1) and (y != ys[0] or len(ys) == 1):
                    put(x, y, face.tongue_color if face.tongue_color != lip else TONGUE)
    if sh.get("lip"):                                      # FV: the upper teeth resting on the lower lip
        y0 = min(y for _, y in outer)
        for x, y in outer:
            if y == y0:
                put(x, y, face.teeth_color)


def close_eyes(img, face: Face, lids: list | None = None):
    px = img.load()
    for i, b in enumerate(face.eyes):
        _erase(img, b, lids[i] if lids else ring_colour(img, b, fallback=face.skin), grow=0)
        y = b.y + (2 * b.h) // 3 if b.h > 2 else b.y + b.h - 1
        for x in range(b.x, b.x + b.w):
            if px[x, y][3] >= 40:
                px[x, y] = face.eye_color


def build(img, face: Face, shapes: dict | None = None) -> dict[str, dict[str, object]]:
    """{mouth: {"open": image, "closed": image}} - every mouth, eyes open and closed."""
    if face.mouth_px:
        return build_marked(img, face, shapes)
    base = img.copy()
    mouth_colours(img, face)
    lids = [ring_colour(img, b, fallback=face.skin) for b in face.eyes]   # from the picture before any change
    _erase(base, face.mouth, ring_colour(img, face.mouth, fallback=face.skin))
    out = {}
    for mouth in MOUTHS:
        im = base.copy()
        draw_mouth(im, face, mouth, shapes)
        closed = im.copy()
        if face.eyes:
            close_eyes(closed, face, lids)
        out[mouth] = {"open": im, "closed": closed}
    return out


def _hex(c) -> tuple:
    c = str(c).lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4)) + (255,)


def _bbox(pts) -> Box:
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return Box(min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1)


def face_from_marks(img, marks: dict) -> Face:
    """A face from the pixels the user marked in the viewer (0.20.7, the user's design):
    marks = {"mouth": [[x, y], ...], "eyes": [[[x, y], ...], [[x, y], ...]] (left, right),
    "colors": {"lips", "tongue", "teeth", "eyelid", "eyeball", "pupil": "#RRGGBB"}} in grid
    pixels. Colours left out come from the marked pixels, as with boxes."""
    W, H = img.size
    ok = lambda p: 0 <= p[0] < W and 0 <= p[1] < H                     # noqa: E731
    mouth = {tuple(int(v) for v in p) for p in marks.get("mouth", []) if ok(p)}
    eyes = [{tuple(int(v) for v in p) for p in e if ok(p)} for e in marks.get("eyes", [])]
    eyes = [e for e in eyes if e]
    if not mouth:
        raise SystemExit("the marks have no mouth pixels - in 'face show NAME', pick 'mouth' and click its pixels, "
                         "then 'save marks'")
    from collections import Counter
    px = img.load()
    feat = mouth.union(*eyes)
    skin = Counter(px[x, y] for y in range(H) for x in range(W)
                   if px[x, y][3] >= 40 and (x, y) not in feat).most_common(1)
    f = Face(size=(W, H), mouth=_bbox(mouth), eyes=[_bbox(e) for e in sorted(eyes, key=lambda e: min(p[0] for p in e))],
             skin=skin[0][0] if skin else (0, 0, 0, 255), mouth_px=mouth,
             eye_px=sorted(eyes, key=lambda e: min(p[0] for p in e)))
    cols = [px[p] for p in mouth if px[p][3] >= 40]
    if cols:                                               # lips/tongue the darkest third, teeth the lightest
        cols.sort(key=_lum)
        n = max(1, len(cols) // 3)
        f.mouth_color = f.tongue_color = _mean(cols[:n])
        light = _mean(cols[-n:])
        if len(cols) >= 3 and _lum(light) - _lum(f.mouth_color) > 60:
            f.teeth_color = light
    ecols = [px[p] for e in eyes for p in e if px[p][3] >= 40]
    if ecols:
        f.eye_color = min(ecols, key=_lum)
    c = marks.get("colors") or {}
    for k, attr in (("lips", "mouth_color"), ("tongue", "tongue_color"), ("teeth", "teeth_color"),
                    ("eyelid", "lid_color"), ("eyeball", "eyeball_color"), ("pupil", "pupil_color")):
        if c.get(k):
            setattr(f, attr, _hex(c[k]))
    if c.get("lips") and not c.get("tongue"):
        f.tongue_color = f.mouth_color
    if f.pupil_color:
        f.eye_color = f.pupil_color
    return f


def inpaint(img, pts: set, smooth: int = 40):
    """The marked pixels filled from the colours round them (0.20.7): rings peeled in from
    the edge, each pixel the average of its filled neighbours, then smoothed so the fill is
    a gradient between the surrounding colours. Transparent pixels stay as they are."""
    W, H = img.size
    px = img.load()
    todo = {p for p in pts if 0 <= p[0] < W and 0 <= p[1] < H and px[p][3] >= 40}
    val = {}
    N8 = [(-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0), (-1, -1, .7), (1, -1, .7), (-1, 1, .7), (1, 1, .7)]

    def known(q):
        return 0 <= q[0] < W and 0 <= q[1] < H and q not in todo and px[q][3] >= 40
    rest = set(todo)
    while rest:
        layer = {}
        for (x, y) in rest:
            acc, wt = [0.0, 0.0, 0.0], 0.0
            for dx, dy, w in N8:
                q = (x + dx, y + dy)
                c = val.get(q) or (px[q][:3] if known(q) else None)
                if c is not None:
                    for i in range(3):
                        acc[i] += c[i] * w
                    wt += w
            if wt:
                layer[(x, y)] = tuple(a / wt for a in acc)
        if not layer:                                     # cut off from any colour: the skin
            layer = {p: tuple(float(v) for v in (px[p][:3])) for p in rest}
        val.update(layer)
        rest -= set(layer)
    for _ in range(smooth):                               # a gradient: the average of the 4 neighbours
        nv = {}
        for (x, y), c in val.items():
            acc, n = [0.0, 0.0, 0.0], 0
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                q = (x + dx, y + dy)
                cc = val.get(q) or (px[q][:3] if known(q) else None)
                if cc is not None:
                    for i in range(3):
                        acc[i] += cc[i]
                    n += 1
            nv[(x, y)] = tuple(a / n for a in acc) if n else c
        val = nv
    for p, c in val.items():
        px[p] = tuple(max(0, min(255, round(v))) for v in c) + (px[p][3],)
    return img


def _eyes_open(img, face: Face, orig):
    """Open eyes on the blank face: eyeball and pupil colours when picked, else the
    marked pixels as they were in the picture."""
    px, op = img.load(), orig.load()
    for e in face.eye_px:
        if face.eyeball_color is None and face.pupil_color is None:
            for p in e:
                px[p] = op[p]
            continue
        b = _bbox(e)
        r = max(0.5, min(b.w, b.h) / 3)
        for p in e:
            inner = (p[0] - b.cx) ** 2 + (p[1] - b.cy) ** 2 <= r * r + 1e-9
            px[p] = (face.pupil_color or face.eye_color) if inner else (face.eyeball_color or op[p])


def _eyes_closed(img, face: Face):
    """Closed: the eyelid colour (picked, else the blank face there) and a lash line at
    two thirds down each column of the eye."""
    px = img.load()
    for e in face.eye_px:
        if face.lid_color:
            for p in e:
                px[p] = face.lid_color
        cols: dict[int, list[int]] = {}
        for x, y in e:
            cols.setdefault(x, []).append(y)
        for x, ys in cols.items():
            y0, y1 = min(ys), max(ys)
            y = y0 + (2 * (y1 - y0 + 1)) // 3 if y1 > y0 + 1 else y1
            if (x, y) in e:
                px[x, y] = face.eye_color


def build_marked(img, face: Face, shapes: dict | None = None) -> dict[str, dict[str, object]]:
    """build() for a face marked pixel by pixel (0.20.7): the eyes and mouth are filled from
    the colours round them (the blank face), then every mouth and the eyes are drawn on it."""
    blank = inpaint(img.copy(), set(face.mouth_px or ()).union(*face.eye_px))
    face.blank = blank
    out = {}
    for mouth in MOUTHS:
        im = blank.copy()
        _eyes_open(im, face, img)
        draw_mouth(im, face, mouth, shapes)
        closed = blank.copy()
        draw_mouth(closed, face, mouth, shapes)
        if face.eye_px:
            _eyes_closed(closed, face)
        out[mouth] = {"open": im, "closed": closed}
    return out


def alike(images: dict) -> list[tuple[str, str]]:
    """Pairs of mouths that came out identical (too few pixels to tell them apart)."""
    keys = list(images)
    data = {k: images[k]["open"].tobytes() for k in keys}
    return [(a, b) for i, a in enumerate(keys) for b in keys[i + 1:] if data[a] == data[b]]


def sheet(images: dict, scale: int | None = None):
    """All mouths, eyes open (top row) and closed (bottom row), enlarged, labelled."""
    from PIL import Image, ImageDraw
    first = images[MOUTHS[0]]["open"]
    scale = scale or max(1, min(8, 240 // max(first.width, 1)))
    w, h = first.width * scale, first.height * scale
    pad, lab = 6, 14
    cols = len(MOUTHS)
    out = Image.new("RGBA", (cols * (w + pad) + pad, 2 * (h + lab + pad) + pad), (24, 26, 30, 255))
    d = ImageDraw.Draw(out)
    for i, m in enumerate(MOUTHS):
        for r, state in enumerate(("open", "closed")):
            x, y = pad + i * (w + pad), pad + r * (h + lab + pad)
            d.text((x, y), f"{m}" + (" (eyes closed)" if state == "closed" and i == 0 else ""), fill=(230, 230, 230, 255))
            big = images[m][state].resize((w, h), Image.NEAREST)
            bgc = Image.new("RGBA", big.size, (0, 0, 0, 255))
            out.paste(Image.alpha_composite(bgc, big), (x, y + lab))
    return out


def recolor(files: list, src: str, dst: str) -> int:
    """Every pixel of colour src (#RRGGBB) becomes dst, in each of the files (PNG). Returns
    how many pixels changed (0.20.5: touching up a face's colours without an image editor)."""
    from PIL import Image
    a = tuple(int(src.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    b = tuple(int(dst.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    n = 0
    for f in files:
        im = Image.open(f).convert("RGBA")
        px = im.load()
        k = 0
        for y in range(im.height):
            for x in range(im.width):
                c = px[x, y]
                if c[3] >= 40 and c[:3] == a:
                    px[x, y] = b + (c[3],)
                    k += 1
        if k:
            im.save(f)
            n += k
    return n
