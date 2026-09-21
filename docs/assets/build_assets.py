#!/usr/bin/env python3
"""Regenerate the two images in this directory: hero.svg and cycle.svg.

Both are built here rather than drawn by hand in a vector editor for one reason:
GitHub renders an SVG inside an <img>, where no web font can load. Any <text>
element would fall back to whatever sans the reader's machine has. So every piece
of type is converted to outlines from the brand typeface (Fustat) before it is
written out, using fontTools: the variable font is instantiated at the weight we
want, glyph outlines are drawn through an SVG path pen, and runs are laid out with
the font's own advance widths plus its GPOS kerning pairs.

The 10Clouds wordmark is never redrawn — its paths are inlined verbatim from the
canonical brand SVG and only uniformly scaled, so that its cap height matches the
Fustat text sitting on the same baseline.

Usage:

    python3 -m venv .venv && .venv/bin/pip install fonttools
    .venv/bin/python docs/assets/build_assets.py

Inputs it looks for (first hit wins), overridable with environment variables:

    FUSTAT_TTF       the Fustat variable font  (wght 200..800)
    BRAND_ASSETS     a directory holding wordmark-10clouds.svg and hero-lens@1x.jpg
                     (the 10cfi-brand skill's assets/brand/)

If the brand directory cannot be found, the hero still builds: the background
falls back to flat Deep Blue and the wordmark to a bundled copy of its paths is
NOT attempted — the script stops and says what is missing, because a redrawn
wordmark is worse than no hero.
"""

from __future__ import annotations

import base64
import os
import re
import sys
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

HERE = Path(__file__).resolve().parent

# --------------------------------------------------------------------------- #
# brand constants — 10Clouds brandbook v1
# --------------------------------------------------------------------------- #

DEEP_BLUE = "#081735"
SIGNAL_BLUE = "#152E61"
DEEP_TEAL = "#29555E"
MIST_GREEN = "#D3E3D8"
WHITE = "#FFFFFF"

# Fustat metrics (unitsPerEm 1000, OS/2 sCapHeight 700)
UPEM = 1000
CAP_HEIGHT = 700

# Ink extents of the canonical wordmark inside its own viewBox "-7 -2.75 406 85",
# measured once from the file. "10Clouds" has no descender, so the ink height is
# the distance from the baseline to the top of the digits/ascenders.
WORDMARK_INK = {"x0": 7.0, "y0": 2.75, "x1": 398.663, "y1": 73.2139}
WORDMARK_INK_H = WORDMARK_INK["y1"] - WORDMARK_INK["y0"]
WORDMARK_INK_W = WORDMARK_INK["x1"] - WORDMARK_INK["x0"]

FONT_CANDIDATES = [
    os.environ.get("FUSTAT_TTF", ""),
    "~/Library/Fonts/Fustat.ttf",
    "~/projects/10cfi-internal-marketplace/plugins/10cfi-base/skills/"
    "pptx-deck-builder/assets/fonts/Fustat.ttf",
]

BRAND_CANDIDATES = [
    os.environ.get("BRAND_ASSETS", ""),
    "~/Library/Application Support/Claude/local-agent-mode-sessions",  # searched below
    "~/projects/10cfi-internal-marketplace/plugins/10cfi-base/skills/10cfi-brand/assets/brand",
]


def find_font() -> Path:
    for candidate in FONT_CANDIDATES:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if path.is_file():
            return path
    sys.exit("Fustat.ttf not found. Set FUSTAT_TTF=/path/to/Fustat.ttf")


def find_brand_dir() -> Path:
    for candidate in BRAND_CANDIDATES:
        if not candidate:
            continue
        root = Path(candidate).expanduser()
        if (root / "wordmark-10clouds.svg").is_file():
            return root
        if root.is_dir():
            hits = sorted(root.glob("**/10cfi-brand/assets/brand/wordmark-10clouds.svg"))
            if hits:
                return hits[-1].parent
    sys.exit(
        "Brand assets not found. Set BRAND_ASSETS to the 10cfi-brand skill's "
        "assets/brand/ directory (it holds wordmark-10clouds.svg and hero-lens@1x.jpg)."
    )


# --------------------------------------------------------------------------- #
# text as outlines
# --------------------------------------------------------------------------- #


class Fustat:
    """One instance of the variable font at a fixed weight, able to emit runs of
    text as a single SVG path with correct advances and kerning."""

    def __init__(self, ttf: Path, weight: int) -> None:
        font = TTFont(str(ttf))
        self.font = instancer.instantiateVariableFont(font, {"wght": weight}, inplace=True)
        self.glyphset = self.font.getGlyphSet()
        self.cmap = self.font.getBestCmap()
        self.hmtx = self.font["hmtx"]
        self.kern = self._load_kerning()
        self._cache: dict[str, str] = {}

    # -- kerning ---------------------------------------------------------- #

    def _load_kerning(self) -> dict[tuple[str, str], int]:
        pairs: dict[tuple[str, str], int] = {}
        if "GPOS" not in self.font:
            return pairs
        gpos = self.font["GPOS"].table
        if not gpos.LookupList:
            return pairs
        for lookup in gpos.LookupList.Lookup:
            if lookup.LookupType != 2:  # PairPos
                continue
            for sub in lookup.SubTable:
                if sub.Format == 1:
                    coverage = sub.Coverage.glyphs
                    for first, pairset in zip(coverage, sub.PairSet):
                        for record in pairset.PairValueRecord:
                            value = getattr(record.Value1, "XAdvance", 0) or 0
                            if value:
                                pairs[(first, record.SecondGlyph)] = value
                elif sub.Format == 2:
                    class1 = _class_map(sub.ClassDef1, sub.Coverage.glyphs)
                    class2 = _class_map(sub.ClassDef2, self.font.getGlyphOrder())
                    for first, c1 in class1.items():
                        if c1 >= len(sub.Class1Record):
                            continue
                        records = sub.Class1Record[c1].Class2Record
                        for second, c2 in class2.items():
                            if c2 >= len(records):
                                continue
                            value = getattr(records[c2].Value1, "XAdvance", 0) or 0
                            if value:
                                pairs[(first, second)] = value
        return pairs

    # -- layout ----------------------------------------------------------- #

    def glyph_names(self, text: str) -> list[str]:
        names = []
        for char in text:
            name = self.cmap.get(ord(char))
            if name is None:
                if char != " ":
                    print(f"  ! no glyph for {char!r}, dropped", file=sys.stderr)
                name = self.cmap.get(0x20)
            names.append(name)
        return names

    def width(self, text: str, size: float, tracking: float = 0.0) -> float:
        names = self.glyph_names(text)
        units = 0
        for i, name in enumerate(names):
            units += self.hmtx[name][0]
            if i + 1 < len(names):
                units += self.kern.get((name, names[i + 1]), 0)
        return units * size / UPEM + tracking * max(len(names) - 1, 0)

    def path(
        self,
        text: str,
        x: float,
        y: float,
        size: float,
        anchor: str = "start",
        tracking: float = 0.0,
    ) -> str:
        """Return the `d` attribute of one path holding the whole run, with (x, y)
        the start (or middle/end, per `anchor`) of the baseline in SVG coordinates."""
        names = self.glyph_names(text)
        scale = size / UPEM
        total = self.width(text, size, tracking)
        pen_x = {"start": x, "middle": x - total / 2, "end": x - total}[anchor]
        commands: list[str] = []
        for i, name in enumerate(names):
            key = f"{name}@{scale:.6f}@{pen_x:.3f}@{y:.3f}"
            pen = SVGPathPen(self.glyphset, ntos=lambda v: f"{v:.1f}")
            self.glyphset[name].draw(TransformPen(pen, (scale, 0, 0, -scale, pen_x, y)))
            drawn = pen.getCommands()
            if drawn:
                commands.append(drawn)
            self._cache[key] = drawn
            pen_x += self.hmtx[name][0] * scale + tracking
            if i + 1 < len(names):
                pen_x += self.kern.get((name, names[i + 1]), 0) * scale
        return "".join(commands)


def _class_map(classdef, glyphs) -> dict[str, int]:
    mapping = {}
    table = getattr(classdef, "classDefs", {}) if classdef else {}
    for glyph in glyphs:
        mapping[glyph] = table.get(glyph, 0)
    return mapping


class Type:
    """The two weights used across both images."""

    def __init__(self, ttf: Path) -> None:
        self.light = Fustat(ttf, 300)
        self.regular = Fustat(ttf, 400)
        self.medium = Fustat(ttf, 500)

    def get(self, weight: str) -> Fustat:
        return {"light": self.light, "regular": self.regular, "medium": self.medium}[weight]

    def text(
        self,
        s: str,
        x: float,
        y: float,
        size: float,
        weight: str = "regular",
        fill: str = WHITE,
        anchor: str = "start",
        tracking: float = 0.0,
        opacity: float | None = None,
    ) -> str:
        d = self.get(weight).path(s, x, y, size, anchor=anchor, tracking=tracking)
        extra = f' opacity="{opacity}"' if opacity is not None else ""
        return f'<path fill="{fill}"{extra} d="{d}"/>'

    def measure(self, s: str, size: float, weight: str = "regular", tracking: float = 0.0):
        return self.get(weight).width(s, size, tracking)


# --------------------------------------------------------------------------- #
# the wordmark
# --------------------------------------------------------------------------- #


def wordmark_paths(brand_dir: Path) -> str:
    """Inline the canonical wordmark's own paths. Never redrawn, never re-fitted —
    only the `fill` is forced, because the canonical file uses currentColor."""
    svg = (brand_dir / "wordmark-10clouds.svg").read_text()
    body = re.findall(r"<path[^>]*/>", svg)
    if not body:
        sys.exit("No paths found in wordmark-10clouds.svg — refusing to draw a substitute.")
    out = []
    for path in body:
        path = re.sub(r'\sfill="[^"]*"', "", path)
        out.append(path.replace("<path", f'<path fill="{WHITE}"', 1))
    return "".join(out)


def wordmark_group(brand_dir: Path, baseline_x: float, baseline_y: float, cap: float) -> str:
    """Place the wordmark so that its baseline sits on `baseline_y`, its left ink
    edge on `baseline_x`, and its cap height equals `cap`."""
    k = cap / WORDMARK_INK_H
    tx = baseline_x - WORDMARK_INK["x0"] * k
    ty = baseline_y - WORDMARK_INK["y1"] * k
    return (
        f'<g transform="translate({tx:.3f} {ty:.3f}) scale({k:.5f})">'
        f"{wordmark_paths(brand_dir)}</g>"
    )


def wordmark_width(cap: float) -> float:
    return WORDMARK_INK_W * (cap / WORDMARK_INK_H)


# --------------------------------------------------------------------------- #
# hero.svg
# --------------------------------------------------------------------------- #

HERO_W, HERO_H = 1920, 360
HERO_LEFT = 132
HERO_BASELINE = 180
HERO_SIZE = 74          # cap height 51.8 for both wordmark and product word
HERO_SUB_BASELINE = 242
HERO_SUB_SIZE = 25

PRODUCT_WORD = "dev"
SUBLINE = "10c-dev — the delivery workflow for Claude Code"


def build_hero(type_: Type, brand_dir: Path) -> str:
    cap = CAP_HEIGHT * HERO_SIZE / UPEM

    lens = brand_dir / "hero-lens@1x.jpg"
    if lens.is_file():
        data = base64.b64encode(lens.read_bytes()).decode("ascii")
        # The composite is 1920x900; this window keeps the glass lens low and to the
        # right of the lockup, away from the type.
        background = (
            f'<image x="0" y="-330" width="1920" height="900" '
            f'preserveAspectRatio="xMidYMid slice" href="data:image/jpeg;base64,{data}"/>'
        )
    else:
        print("  ! hero-lens@1x.jpg missing, falling back to flat Deep Blue", file=sys.stderr)
        background = ""

    x = HERO_LEFT
    parts = [wordmark_group(brand_dir, x, HERO_BASELINE, cap)]
    x += wordmark_width(cap)

    gap = HERO_SIZE * 0.42
    x += gap
    parts.append(
        type_.text("·", x, HERO_BASELINE, HERO_SIZE, "light", MIST_GREEN, opacity=0.75)
    )
    x += type_.measure("·", HERO_SIZE, "light") + gap
    parts.append(type_.text(PRODUCT_WORD, x, HERO_BASELINE, HERO_SIZE, "light", WHITE))

    parts.append(
        type_.text(
            SUBLINE,
            HERO_LEFT,
            HERO_SUB_BASELINE,
            HERO_SUB_SIZE,
            "regular",
            MIST_GREEN,
            tracking=0.2,
        )
    )

    alt = "10Clouds · dev — 10c-dev, the delivery workflow for Claude Code"
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {HERO_W} {HERO_H}" \
width="{HERO_W}" height="{HERO_H}" role="img" aria-label="{alt}">
<title>10Clouds · dev</title>
<defs>
<clipPath id="hero_clip"><rect x="0" y="0" width="{HERO_W}" height="{HERO_H}" rx="18"/></clipPath>
<linearGradient id="hero_veil" x1="0" y1="0" x2="1" y2="0">
<stop offset="0" stop-color="{DEEP_BLUE}" stop-opacity="0.92"/>
<stop offset="0.45" stop-color="{DEEP_BLUE}" stop-opacity="0.72"/>
<stop offset="1" stop-color="{DEEP_BLUE}" stop-opacity="0.30"/>
</linearGradient>
</defs>
<g clip-path="url(#hero_clip)">
<rect x="0" y="0" width="{HERO_W}" height="{HERO_H}" fill="{DEEP_BLUE}"/>
{background}
<rect x="0" y="0" width="{HERO_W}" height="{HERO_H}" fill="url(#hero_veil)"/>
{"".join(parts)}
</g>
</svg>
"""


# --------------------------------------------------------------------------- #
# cycle.svg — the build cycle
# --------------------------------------------------------------------------- #

CYCLE_W = 1000  # the height follows from the content


def node(x, y, w, h, fill=SIGNAL_BLUE, stroke=DEEP_TEAL, width=1.6, dashed=False, rx=12):
    """A block. `dashed` means exactly one thing in this diagram: optional."""
    dash = ' stroke-dasharray="9 7"' if dashed else ""
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" '
        f'stroke="{stroke}" stroke-width="{width}"{dash}/>'
    )


def line(d, opacity=0.9, width=2.3, arrow=True):
    """A step that always happens: a solid arrow."""
    head = ' marker-end="url(#cy_arrow)"' if arrow else ""
    return (
        f'<path d="{d}" fill="none" stroke="{MIST_GREEN}" stroke-width="{width}" '
        f'opacity="{opacity}"{head}/>'
    )


def loop(d, width=2.0):
    """A loop back: a dotted arrow, visibly a different thing from a dashed (optional)
    box outline. Every loop in the diagram uses this one style."""
    return (
        f'<path d="{d}" fill="none" stroke="{MIST_GREEN}" stroke-width="{width}" '
        f'stroke-dasharray="1.5 6" stroke-linecap="round" opacity="0.85" '
        f'marker-end="url(#cy_loop)"/>'
    )


def person(cx, cy, scale=1.0, opacity=1.0):
    """The developer. Same icon everywhere a human is needed, so the reader can see
    at a glance where they come into it."""
    return (
        f'<g opacity="{opacity}" transform="translate({cx} {cy}) scale({scale})" '
        f'fill="none" stroke="{MIST_GREEN}" stroke-width="2.6" stroke-linecap="round">'
        f'<circle cx="0" cy="-15" r="9.5"/>'
        f'<path d="M-16 16 a16 16 0 0 1 32 0"/>'
        f"</g>"
    )


def talk(cx, cy, left, right, label, type_, label_dy=34, gap=8):
    """A short bidirectional stem between a block edge and a person: the block asks,
    the human answers. Used for every person in the diagram, so a human is never
    drawn as a destination the flow runs into."""
    return "".join(
        [
            line(f"M{left} {cy - gap} H {right}", width=2.0),
            line(f"M{right} {cy + gap} H {left}", width=2.0),
            type_.text(label, cx, cy + label_dy, 13, "regular", MIST_GREEN, "middle"),
        ]
    )


def badge(type_: Type, cx, cy, n: int) -> str:
    """A small numbered disc giving the inside of the Build block a reading order.
    Circled-digit characters are not in the font, so they are drawn."""
    return (
        f'<circle cx="{cx}" cy="{cy}" r="9" fill="{DEEP_TEAL}" stroke="{MIST_GREEN}" '
        f'stroke-width="1.2"/>'
        + type_.text(str(n), cx, cy + 4.6, 12.5, "medium", WHITE, "middle")
    )


def mark_auto(cx, cy, r=6.0) -> str:
    """Filled diamond: this step writes outside the chat on its own."""
    return (
        f'<path d="M{cx} {cy - r} L{cx + r} {cy} L{cx} {cy + r} L{cx - r} {cy} z" '
        f'fill="{MIST_GREEN}"/>'
    )


def mark_ask(cx, cy, r=6.6) -> str:
    """Stop sign: this step asks you before it does anything."""
    k = r * 0.4142
    pts = [
        (cx - k, cy - r), (cx + k, cy - r), (cx + r, cy - k), (cx + r, cy + k),
        (cx + k, cy + r), (cx - k, cy + r), (cx - r, cy + k), (cx - r, cy - k),
    ]
    d = "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in pts) + " z"
    return f'<path d="{d}" fill="none" stroke="{MIST_GREEN}" stroke-width="1.7"/>'


def side_effect(type_: Type, x, y, kind: str, text: str, size=12.0, anchor="start") -> str:
    """A marker plus the one thing this step does outside the conversation."""
    glyph = mark_auto if kind == "auto" else mark_ask
    if anchor == "end":
        width = type_.measure(text, size)
        return glyph(x - width - 14, y - 4) + type_.text(text, x, y, size, "regular", MIST_GREEN, "end")
    return glyph(x + 6, y - 4) + type_.text(text, x + 18, y, size, "regular", MIST_GREEN)


def build_cycle(type_: Type) -> str:
    """The build cycle.

    Geometry rules, so the picture stays tidy when the wording changes:
    every box is sized from its content plus a fixed PAD on all four sides, the
    stacked blocks are laid out by a cursor with one GAP between them (big enough
    that every arrow has a stem, not just a head), and nothing is eyeballed.
    """
    T = type_.text
    o: list[str] = []

    PAD, GAP, LINE = 16, 44, 18
    L, W = 200, 470            # the chain
    MID = L + W / 2
    BX, BW = 130, 610          # Build, the only wider block
    PX = 812                   # the column the human stands in

    def block(y, title, sub=None, body=(), marker=None, dashed=False,
              fill=SIGNAL_BLUE, stroke=DEEP_TEAL, x=L, w=W, tsize=20):
        """One box: a title, optionally a sub-line on the same baseline, optionally
        extra body lines, optionally a side-effect marker on the right."""
        h = PAD * 2 + 22 + LINE * len(body)
        out = [node(x, y, w, h, fill=fill, stroke=stroke, dashed=dashed,
                    width=1.8 if dashed else 1.6)]
        base = y + PAD + 21
        out.append(T(title, x + PAD, base, tsize, "medium", WHITE))
        if sub:
            tw = type_.measure(title, tsize, "medium")
            out.append(T(sub, x + PAD + tw + 9, base, 13, "regular", MIST_GREEN))
        for i, part in enumerate(body):
            out.append(T(part, x + PAD, base + 22 + i * LINE, 12.5, "regular", MIST_GREEN))
        if marker:
            out.append(side_effect(type_, x + w - PAD, base, marker[0], marker[1], 12,
                                   anchor="end"))
        o.extend(out)
        return h

    def strip(y, n, title, sub, x, w, marker=None, h=36):
        """A single-line row inside Build."""
        o.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{DEEP_BLUE}" '
            f'stroke="{DEEP_TEAL}" stroke-width="1.3"/>'
        )
        base = y + 24
        o.append(badge(type_, x + 26, y + h / 2, n))
        o.append(T(title, x + 44, base, 14, "medium", WHITE))
        tw = type_.measure(title, 14, "medium")
        if sub:
            o.append(T(sub, x + 44 + tw + 9, base, 12.5, "regular", MIST_GREEN))
        if marker:
            o.append(side_effect(type_, x + 36, base + 20, marker[0], marker[1], 11.5))
        return h

    def down(y0, y1, x=MID, label=None, lx=None):
        o.append(line(f"M{x} {y0 + 2} V {y1 - 3}"))
        if label:
            o.append(T(label, (lx or x + 12), (y0 + y1) / 2 + 5, 13, "regular", MIST_GREEN))

    y = 28

    # ---- the ticket ------------------------------------------------------- #
    o.append(
        f'<rect x="{L}" y="{y}" width="{W}" height="70" rx="14" fill="none" '
        f'stroke="{MIST_GREEN}" stroke-width="1.6" opacity="0.6"/>'
    )
    o.append(T("/10c-dev:implement ABC-123", L + PAD, y + PAD + 18, 16, "medium", WHITE))
    o.append(side_effect(type_, L + W - PAD, y + PAD + 18, "auto", "moves ticket", 12, anchor="end"))
    o.append(T("a ticket key, or LOCAL-<date>", L + PAD, y + PAD + 40, 13, "regular", MIST_GREEN))
    ticket_bottom = y + 70
    y = ticket_bottom + GAP

    # ---- Build ------------------------------------------------------------ #
    build_top = y
    mark = len(o)              # the Build frame is inserted here once its height is known
    o.append(T("Build", BX + PAD + 4, y + PAD + 26, 27, "medium", WHITE))
    inner_x, inner_w = BX + PAD, BW - PAD * 2
    sy = y + PAD + 44
    strip(sy, 1, "Rung",
          "R0 probe · R1 PoC · R2 MVP · R3 hardened — the ceremony scales with it",
          inner_x, inner_w)
    iy = sy + 36 + 12
    strip(iy, 2, "Interview", "until the goal is clear", inner_x, inner_w)
    ry = iy + 36 + 12
    cw = (inner_w - 20) / 2
    strip(ry, 3, "Tiny spec", "what done means", inner_x, cw, h=54)
    strip(ry, 4, "Write the code", "in your checkout", inner_x + cw + 20, cw, h=54,
          marker=("auto", "edits files"))
    build_h = (ry + 54 + PAD) - build_top
    o.insert(mark, node(BX, build_top, BW, build_h, stroke=MIST_GREEN, width=2.2, rx=16))
    build_bottom = build_top + build_h
    # step 3 leads into step 4
    o.append(line(f"M{inner_x + cw + 3} {ry + 27} H {inner_x + cw + 17}", width=2.0))

    # The human stands further right than the other two, because this row's labels
    # are long: the icon starts at least 10px clear of the end of "one question at
    # a time", and the labels sit clear of the stems.
    IX = 906
    o.append(person(IX, iy + 16, 0.85))
    o.append(T("You", IX, iy - 26, 15, "medium", WHITE, "middle"))
    o.append(line(f"M{BX + BW + 4} {iy + 6} H {IX - 32}", width=2.0))
    o.append(T("one question at a time", BX + BW + 14, iy - 10, 12.5, "regular", MIST_GREEN))
    o.append(line(f"M{IX - 32} {iy + 36} H {BX + BW + 4}", width=2.0))
    o.append(T("you answer", BX + BW + 14, iy + 54, 12.5, "regular", MIST_GREEN))

    y = build_bottom + GAP

    # ---- verify ------------------------------------------------------------ #
    verify_top = y
    vh = block(y, "Verify", "— on the running app, not just the compiler")
    verify_bottom = y + vh
    down(build_bottom, verify_top, x=330, label="prove it", lx=342)
    y = verify_bottom + GAP

    # ---- review ------------------------------------------------------------ #
    review_top = y
    rh = block(y, "Review your own diff")
    review_bottom = y + rh
    down(verify_bottom, review_top)
    y = review_bottom + GAP

    # ---- the critic — the one block that keeps two lines ------------------- #
    critic_top = y
    ch = block(
        y, "The adversarial critic",
        body=[
            "It reads only the ticket — so it tests what was asked for,",
            "not what was built — then tries to break the running app.",
        ],
        marker=("auto", "drives your app"),
        dashed=True, stroke=MIST_GREEN,
    )
    critic_bottom = y + ch
    down(review_bottom, critic_top)
    y = critic_bottom + GAP

    # ---- commit and push --------------------------------------------------- #
    commit_top = y
    qh = block(y, "Commit and push?", "— only on your yes", marker=("ask", "asks first"))
    commit_bottom = y + qh
    down(critic_bottom, commit_top, label="PASS (or skipped)")
    o.append(person(PX, commit_top + 20, 0.78))
    o.append(talk(PX, commit_top + 24, L + W + 4, PX - 32, "you say yes", type_, label_dy=32))
    y = commit_bottom + GAP

    # the critic can be skipped: a bracket around that one block
    o.append(line(f"M{L} {review_bottom - 10} H 156 V {commit_top + 24} H {L - 4}",
                  width=1.5, opacity=0.85))
    o.append(T("or skip the critic", 24, review_bottom - 16, 12, "regular", MIST_GREEN))

    # ---- both failure loops, on the right at different offsets ------------- #
    code_right = inner_x + cw + 20 + cw           # right edge of step 4
    o.append(loop(f"M{L + W} {verify_top + 22} H 790 V {ry + 20} H {code_right + 4}"))
    o.append(T("failed → fix in", 620, verify_top - 12, 12.5, "regular", MIST_GREEN))
    o.append(badge(type_, 620 + type_.measure("failed → fix in ", 12.5) + 8, verify_top - 16, 4))
    o.append(loop(f"M{L + W} {critic_top + 30} H 856 V {ry + 40} H {code_right + 4}"))
    o.append(T("FAIL → back to", 660, verify_bottom + 26, 12.5, "medium", MIST_GREEN))
    o.append(badge(type_, 660 + type_.measure("FAIL → back to ", 12.5, "medium") + 8,
                   verify_bottom + 22, 4))

    # ---- on staging --------------------------------------------------------- #
    staging_top = y
    sh = block(y, "On staging", "— ticket In Review", marker=("auto", "ticket → In Review"),
               fill=DEEP_BLUE)
    staging_bottom = y + sh
    down(commit_bottom, staging_top)
    y = staging_bottom + GAP

    # ---- the human check ----------------------------------------------------- #
    dhw, dhh = 180, 36
    dcy = y + dhh
    o.append(
        f'<path d="M{MID} {dcy - dhh} L{MID + dhw} {dcy} L{MID} {dcy + dhh} '
        f'L{MID - dhw} {dcy} z" fill="{DEEP_TEAL}" stroke="{MIST_GREEN}" stroke-width="1.8"/>'
    )
    o.append(T("Checked on production", MID, dcy - 4, 15.5, "medium", WHITE, "middle"))
    o.append(T("by a human?", MID, dcy + 16, 15.5, "medium", WHITE, "middle"))
    down(staging_bottom, dcy - dhh)
    o.append(person(PX, dcy - 8, 0.78))
    o.append(talk(PX, dcy - 4, MID + dhw + 4, PX - 32, "you check", type_, label_dy=32))
    diamond_bottom = dcy + dhh

    # not yet: back into staging
    o.append(loop(f"M{MID - dhw - 4} {dcy} H 150 V {staging_top + 26} H {L - 4}"))
    o.append(
        f'<g transform="rotate(-90 132 {(staging_top + dcy) / 2})">'
        + T("wait for the next check", 132, (staging_top + dcy) / 2 + 4, 12, "regular",
            MIST_GREEN, "middle")
        + "</g>"
    )
    y = diamond_bottom + GAP

    # ---- done, and the other outcome ----------------------------------------- #
    done_h = 58
    done_top = y
    o.append(f'<rect x="{MID - 100}" y="{done_top}" width="200" height="{done_h}" rx="29" '
             f'fill="{MIST_GREEN}"/>')
    o.append(T("Done", MID, done_top + 36, 21, "medium", DEEP_BLUE, "middle"))
    down(diamond_bottom, done_top, label="yes")
    o.append(side_effect(type_, MID - 112, done_top + 36, "ask", "you confirm", 12, anchor="end"))

    bug_y = done_top - 4
    o.append(
        f'<rect x="24" y="{bug_y}" width="196" height="46" rx="14" fill="none" '
        f'stroke="{MIST_GREEN}" stroke-width="1.6" opacity="0.6"/>'
    )
    o.append(T("a new ticket", 40, bug_y + 20, 13, "medium", WHITE))
    o.append(T("this one stays In Review", 40, bug_y + 37, 12, "regular", MIST_GREEN))
    o.append(loop(f"M{MID - 92} {dcy + 20} L 228 {bug_y + 16}"))
    o.append(T("found a bug", MID - 200, dcy + 56, 12, "regular", MIST_GREEN, "end"))

    done_bottom = done_top + done_h

    # ---- the status rail ------------------------------------------------------ #
    rail = 958
    bands = [
        ("IN PROGRESS", 28, commit_bottom),
        ("IN REVIEW", staging_top, diamond_bottom),
        ("DONE", done_top, done_bottom),
    ]
    for label, y0, y1 in bands:
        o.append(f'<path d="M{rail} {y0} V {y1}" stroke="{DEEP_TEAL}" stroke-width="7" fill="none"/>')
        for edge in (y0, y1):
            o.append(
                f'<path d="M{rail - 8} {edge} H {rail + 8}" stroke="{MIST_GREEN}" '
                f'stroke-width="1.6" opacity="0.8" fill="none"/>'
            )
        mid = (y0 + y1) / 2
        o.append(
            f'<g transform="rotate(-90 {rail - 20} {mid})">'
            + T(label, rail - 20, mid + 4, 12, "medium", MIST_GREEN, "middle", tracking=1.4)
            + "</g>"
        )
    o.append(
        f'<g transform="rotate(-90 986 {(28 + done_bottom) / 2})">'
        + T("TICKET STATUS FOLLOWS THE CODE", 986, (28 + done_bottom) / 2 + 4, 12, "medium",
            MIST_GREEN, "middle", tracking=1.4)
        + "</g>"
    )

    # ---- legend, in the free corner beside Done -------------------------------- #
    cols, rows = [568, 762], [done_top - 16, done_top + 8, done_top + 32]

    def lg(col, row, swatch, text):
        x, yy = cols[col], rows[row]
        o.append(swatch(x, yy))
        o.append(T(text, x + 40, yy + 4.5, 12, "regular", MIST_GREEN))

    lg(0, 0, lambda x, yy: line(f"M{x} {yy} H {x + 28}", width=2.3), "always")
    lg(
        0, 1,
        lambda x, yy: f'<rect x="{x}" y="{yy - 8}" width="28" height="16" rx="4" fill="none" '
                      f'stroke="{MIST_GREEN}" stroke-width="1.6" stroke-dasharray="9 7"/>',
        "optional",
    )
    lg(0, 2, lambda x, yy: loop(f"M{x} {yy} H {x + 28}"), "loops back")
    lg(1, 0, lambda x, yy: person(x + 12, yy - 2, 0.4), "you")
    lg(1, 1, lambda x, yy: mark_auto(x + 14, yy, 7), "writes on its own")
    lg(1, 2, lambda x, yy: mark_ask(x + 14, yy, 8), "asks you first")

    o.append(T("10Clouds · dev", 26, 54, 13, "medium", MIST_GREEN, opacity=0.85))
    o.append(T("the build cycle", 26, 72, 12.5, "regular", MIST_GREEN, opacity=0.7))

    height = int(done_bottom + 22)
    alt = (
        "The 10c-dev build cycle. The implement skill on a ticket key moves the ticket to In "
        "Progress and opens Build, which holds the rung (R0 probe to R3 hardened), the "
        "interview with the developer, the tiny spec and writing the code. Verify runs it on "
        "the live app and fails back into step four. The diff is reviewed, then an optional "
        "critic drives the running app: FAIL returns to step four, PASS goes on, and the "
        "critic can be skipped. Commit and push happens only on your yes; the ticket waits on "
        "staging In Review until a human checks production — yes reaches Done, a bug opens a "
        "new ticket. Markers show which steps write outside the chat and which ask first."
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {CYCLE_W} {height}" \
width="{CYCLE_W}" height="{height}" role="img" aria-label="{alt}">
<title>The 10c-dev build cycle</title>
<defs>
<marker id="cy_arrow" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="6.5" \
markerHeight="6.5" orient="auto-start-reverse">
<path d="M0 0 L10 5 L0 10 z" fill="{MIST_GREEN}"/>
</marker>
<marker id="cy_loop" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="6" \
markerHeight="6" orient="auto-start-reverse">
<path d="M0 0 L10 5 L0 10 z" fill="{MIST_GREEN}" opacity="0.85"/>
</marker>
</defs>
<rect x="0" y="0" width="{CYCLE_W}" height="{height}" rx="20" fill="{DEEP_BLUE}"/>
<rect x="1.5" y="1.5" width="{CYCLE_W - 3}" height="{height - 3}" rx="20" fill="none" \
stroke="{DEEP_TEAL}" stroke-width="3"/>
{"".join(o)}
</svg>
"""


# --------------------------------------------------------------------------- #


def main() -> None:
    ttf = find_font()
    brand = find_brand_dir()
    print(f"font  {ttf}")
    print(f"brand {brand}")
    type_ = Type(ttf)

    hero = HERE / "hero.svg"
    hero.write_text(build_hero(type_, brand))
    print(f"wrote {hero} ({hero.stat().st_size // 1024} KB)")

    cycle = HERE / "cycle.svg"
    cycle.write_text(build_cycle(type_))
    print(f"wrote {cycle} ({cycle.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
