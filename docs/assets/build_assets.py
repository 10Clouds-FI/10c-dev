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

CYCLE_W, CYCLE_H = 1000, 1198


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
    T = type_.text
    o: list[str] = []

    # One left edge and one width for the whole chain; only Build is wider.
    L, W = 200, 500
    MID = L + W / 2
    BX, BW = 84, 616  # Build
    PX = 800  # the column the human stands in

    # ---- 1. the ticket ---------------------------------------------------- #
    o.append(
        f'<rect x="{L}" y="22" width="{W}" height="62" rx="14" fill="none" '
        f'stroke="{MIST_GREEN}" stroke-width="1.6" opacity="0.6"/>'
    )
    o.append(T("/10c-dev:implement ABC-123", L + 18, 44, 15, "medium", WHITE))
    o.append(
        T("— a ticket key, or LOCAL-<date> when there is no ticket",
          L + 18, 63, 13, "regular", MIST_GREEN)
    )
    o.append(side_effect(type_, L + 12, 79, "auto", "moves your ticket to In Progress"))
    o.append(line(f"M{MID} 84 V 96"))

    # ---- 2. Build: the heart, and the only block with an inside ----------- #
    by, bh = 100, 374
    o.append(node(BX, by, BW, bh, stroke=MIST_GREEN, width=2.2, rx=16))
    o.append(T("Build the smallest thing that works", BX + 26, by + 34, 25, "medium", WHITE))

    # -- 1. the rung: picked once, so no arrows between the four ---------- #
    rx0, ry0, rw0 = BX + 16, 146, BW - 32
    o.append(
        f'<rect x="{rx0}" y="{ry0}" width="{rw0}" height="140" rx="10" fill="{DEEP_BLUE}" '
        f'stroke="{DEEP_TEAL}" stroke-width="1.4"/>'
    )
    o.append(badge(type_, rx0 + 21, ry0 + 20, 1))
    o.append(T("Rung — how finished this has to be", rx0 + 38, ry0 + 25, 14.5, "medium", WHITE))

    steps = [
        ("R0 probe", "throwaway, no tests"),
        ("R1 PoC", "works once, no tests"),
        ("R2 MVP", "tests and self-review"),
        ("R3 hardened", "tests, review, critic"),
    ]
    sw, sgap = 130, 14
    sx0, stop = rx0 + 12, ry0 + 34
    for i, (title, caption) in enumerate(steps):
        x = sx0 + i * (sw + sgap)
        o.append(
            f'<rect x="{x}" y="{stop}" width="{sw}" height="56" rx="6" fill="{SIGNAL_BLUE}" '
            f'stroke="{DEEP_TEAL}" stroke-width="1.2"/>'
        )
        o.append(T(title, x + 9, stop + 22, 13.5, "medium", WHITE))
        o.append(T(caption, x + 9, stop + 43, 11.5, "regular", MIST_GREEN))
    for j, part in enumerate(
        [
            "the agent proposes a rung, you agree or pick another;",
            "the ceremony scales with it — R0/R1 skip tests and the critic",
        ]
    ):
        o.append(T(part, rx0 + 12, stop + 78 + j * 16, 12.5, "regular", MIST_GREEN))

    # -- 2. the interview ------------------------------------------------- #
    iy = 296
    o.append(
        f'<rect x="{rx0}" y="{iy}" width="{rw0}" height="50" rx="10" fill="{DEEP_BLUE}" '
        f'stroke="{DEEP_TEAL}" stroke-width="1.4"/>'
    )
    o.append(badge(type_, rx0 + 21, iy + 21, 2))
    o.append(T("The interview", rx0 + 38, iy + 26, 16, "medium", WHITE))
    o.append(
        T("until the goal is clear — usually 2–5 questions; say 'go' to stop",
          rx0 + 150, iy + 26, 13, "regular", MIST_GREEN)
    )
    o.append(line(f"M{rx0 + 40} {ry0 + 140} V {iy - 4}", width=2.0))

    # -- 3. the tiny spec and 4. writing the code, same size -------------- #
    ry1, rh1 = 356, 104
    half = (rw0 - 22) / 2
    cards = [
        (3, "The tiny spec",
         [("what done means, agreed before any code", 12.5),
          ("posted in the chat, not a file", 12.5)],
         None),
        (4, "Write the code",
         [("in your checkout — on a feature branch", 11.5),
          ("when your repo runs PRs; the session board", 11.5),
          ("warns if another session holds the same files", 11.5)],
         ("auto", "edits your working tree")),
    ]
    for i, (n, title, body, effect) in enumerate(cards):
        x = rx0 + i * (half + 22)
        o.append(
            f'<rect x="{x}" y="{ry1}" width="{half}" height="{rh1}" rx="10" '
            f'fill="{DEEP_BLUE}" stroke="{DEEP_TEAL}" stroke-width="1.4"/>'
        )
        o.append(badge(type_, x + 21, ry1 + 20, n))
        o.append(T(title, x + 38, ry1 + 25, 16, "medium", WHITE))
        for j, (part, size) in enumerate(body):
            o.append(T(part, x + 14, ry1 + 46 + j * 15, size, "regular", MIST_GREEN))
        if effect:
            o.append(side_effect(type_, x + 8, ry1 + 94, effect[0], effect[1], 12))
    o.append(line(f"M{rx0 + 40} {iy + 50} V {ry1 - 4}", width=2.0))
    o.append(line(f"M{rx0 + half + 3} {ry1 + rh1 / 2} H {rx0 + half + 19}", width=2.0))

    # -- the human, on the interview's own row ---------------------------- #
    o.append(person(PX, iy + 24, 1.05))
    o.append(T("You", PX, iy - 26, 15, "medium", WHITE, "middle"))
    o.append(line(f"M{BX + BW + 4} {iy + 4} H {PX - 40}", width=2.0))
    o.append(T("one question at a time", BX + BW + 10, iy - 4, 13, "regular", MIST_GREEN))
    o.append(line(f"M{PX - 40} {iy + 44} H {BX + BW + 4}", width=2.0))
    o.append(T("you answer", BX + BW + 10, iy + 62, 13, "regular", MIST_GREEN))

    # ---- 3. verify — running the app is not a write, so no marker --------- #
    vy, vh = 502, 68
    o.append(node(L, vy, W, vh))
    o.append(T("Verify", L + 20, vy + 26, 21, "medium", WHITE))
    o.append(
        T("runs your app locally, using app.start from your config",
          L + W - 18, vy + 24, 12, "regular", MIST_GREEN, "end")
    )
    o.append(
        T("run it as a human would — UI, API or CLI — not just the compiler.",
          L + 20, vy + 46, 13, "regular", MIST_GREEN)
    )
    o.append(T("The agent judges, you can overrule.", L + 20, vy + 62, 13, "regular", MIST_GREEN))
    o.append(line(f"M300 {by + bh} V {vy - 4}"))
    o.append(T("prove it", 312, vy - 6, 13, "regular", MIST_GREEN))
    # the loop back lands on step 4's own border
    o.append(loop(f"M600 {vy - 2} V {ry1 + rh1 + 4}"))
    o.append(T("verification failed → fix in", 592 - type_.measure("verification failed → fix in", 13) - 22,
               vy - 6, 13, "regular", MIST_GREEN))
    o.append(badge(type_, 583, vy - 10, 4))

    # ---- 4. self review --------------------------------------------------- #
    ry2, rh2 = 586, 54
    o.append(node(L, ry2, W, rh2))
    o.append(T("Review your own diff", L + 20, ry2 + 26, 20, "medium", WHITE))
    o.append(
        T("fix blockers first; then cleanup — what did this change make pointless?",
          L + 20, ry2 + 45, 12.5, "regular", MIST_GREEN)
    )
    o.append(line(f"M{MID} {vy + vh} V {ry2 - 4}"))
    o.append(line(f"M{MID} {ry2 + rh2} V 652"))

    # ---- 5. the critic — dashed, because dashed means optional ------------ #
    cy0, ch0 = 656, 84
    o.append(node(L, cy0, W, ch0, dashed=True, stroke=MIST_GREEN, width=1.8))
    o.append(T("The adversarial critic", L + 20, cy0 + 26, 20, "medium", WHITE))
    o.append(
        side_effect(type_, L + W - 18, cy0 + 24, "auto",
                    "drives your running app; you start the app", 11.5, anchor="end")
    )
    for i, part in enumerate(
        [
            "A second agent that only reads the ticket — so it tests what was",
            "ASKED for, not what was built — and drives the running app trying",
            "to break it.",
        ]
    ):
        o.append(T(part, L + 20, cy0 + 44 + i * 15, 12.5, "regular", MIST_GREEN))

    # FAIL goes back to step 4. Its route is offset well clear of Verify's loop,
    # and the label sits on the vertical segment, just under Build's right border.
    o.append(loop(f"M{L + W} {cy0 + 40} H 860 V 416 H {rx0 + rw0 + 4}"))
    fail_text = "FAIL — findings go back to"
    fail_w = type_.measure(fail_text, 13, "medium")
    o.append(T(fail_text, 836 - fail_w - 18, 496, 13, "medium", MIST_GREEN))
    o.append(badge(type_, 845, 492, 4))

    o.append(line(f"M{MID} {cy0 + ch0} V 754"))
    o.append(T("PASS (or skipped)", MID + 12, 754, 13, "medium", MIST_GREEN))

    # the critic can be skipped: a bracket around that one block only
    o.append(line(f"M{L} {ry2 + rh2 - 8} H 176 V 750 H {L - 4}", width=1.5, opacity=0.85))
    o.append(T("or skip the critic — your call", 20, ry2 + 40, 11.5, "regular", MIST_GREEN))

    # ---- 6. commit and push ----------------------------------------------- #
    qy, qh = 758, 62
    o.append(node(L, qy, W, qh))
    o.append(T("Commit and push?", L + 20, qy + 26, 20, "medium", WHITE))
    o.append(side_effect(type_, L + W - 18, qy + 24, "ask", "asks you first", anchor="end"))
    o.append(
        T("to your base branch or as a PR — your repo's config decides. Only on your yes.",
          L + 20, qy + 46, 12.5, "regular", MIST_GREEN)
    )
    o.append(person(PX, qy + 20, 0.78))
    o.append(talk(PX, qy + 24, L + W + 4, PX - 32, "you say yes", type_, label_dy=32))

    # ---- 7. the state the ticket waits in --------------------------------- #
    sy, sh = 840, 66
    o.append(node(L, sy, W, sh, fill=DEEP_BLUE, stroke=DEEP_TEAL))
    o.append(T("On staging", L + 20, sy + 24, 17, "medium", WHITE))
    o.append(
        T("your CI deploys it; not part of this plugin. Ticket is In Review.",
          L + 128, sy + 24, 12.5, "regular", MIST_GREEN)
    )
    o.append(side_effect(type_, L + 12, sy + 48, "auto", "ticket moved to In Review after the push"))
    o.append(line(f"M{MID} {qy + qh} V {sy - 4}"))

    # ---- 8. the human check ----------------------------------------------- #
    dcy, dhw, dhh = 958, 190, 34
    o.append(
        f'<path d="M{MID} {dcy - dhh} L{MID + dhw} {dcy} L{MID} {dcy + dhh} '
        f'L{MID - dhw} {dcy} z" fill="{DEEP_TEAL}" stroke="{MIST_GREEN}" stroke-width="1.8"/>'
    )
    o.append(T("Checked on production", MID, dcy - 4, 16, "medium", WHITE, "middle"))
    o.append(T("by a human?", MID, dcy + 16, 16, "medium", WHITE, "middle"))
    o.append(line(f"M{MID} {sy + sh} V {dcy - dhh - 4}"))
    o.append(person(PX, dcy - 8, 0.78))
    o.append(talk(PX, dcy - 4, MID + dhw + 4, PX - 32, "you check", type_, label_dy=32))

    # "not yet" is a wait: it loops back into the staging state
    o.append(loop(f"M{MID - dhw - 4} {dcy} H 168 V {sy + 38} H {L - 4}"))
    o.append(
        f'<g transform="rotate(-90 152 920)">'
        + T("wait for the next check", 152, 924, 12, "regular", MIST_GREEN, "middle")
        + "</g>"
    )

    # a failure in production is a drawn outcome too, not a loose end
    o.append(loop(f"M{MID - 96} {dcy + 18} L 300 1010"))
    o.append(
        f'<rect x="24" y="1004" width="268" height="42" rx="14" fill="none" '
        f'stroke="{MIST_GREEN}" stroke-width="1.6" opacity="0.6"/>'
    )
    o.append(T("found a bug → a new ticket,", 40, 1023, 12.5, "regular", MIST_GREEN))
    o.append(T("this one stays In Review", 40, 1039, 12.5, "regular", MIST_GREEN))

    # ---- 9. done ----------------------------------------------------------- #
    o.append(line(f"M{MID} {dcy + dhh} V 1004"))
    o.append(T("yes", MID + 12, 1000, 13.5, "medium", MIST_GREEN, tracking=1.2))
    o.append(f'<rect x="{MID - 90}" y="1008" width="180" height="38" rx="19" fill="{MIST_GREEN}"/>')
    o.append(T("Done", MID, 1034, 19, "medium", DEEP_BLUE, "middle"))
    o.append(side_effect(type_, MID + 104, 1033, "ask", "only when you say it was checked"))

    # ---- the status rail, with the band boundaries drawn ------------------- #
    rail = 944
    bands = [("IN PROGRESS", 22, qy + qh), ("IN REVIEW", sy, dcy + dhh), ("DONE", 1008, 1046)]
    for label, y0, y1 in bands:
        o.append(f'<path d="M{rail} {y0} V {y1}" stroke="{DEEP_TEAL}" stroke-width="7" fill="none"/>')
        for edge in (y0, y1):
            o.append(
                f'<path d="M{rail - 9} {edge} H {rail + 9}" stroke="{MIST_GREEN}" '
                f'stroke-width="1.6" opacity="0.8" fill="none"/>'
            )
        mid = (y0 + y1) / 2
        o.append(
            f'<g transform="rotate(-90 {rail - 16} {mid})">'
            + T(label, rail - 16, mid + 5, 13.5, "medium", MIST_GREEN, "middle", tracking=2.0)
            + "</g>"
        )
    o.append(
        f'<g transform="rotate(-90 977 540)">'
        + T("TICKET STATUS FOLLOWS THE CODE", 977, 544, 13.5, "medium", MIST_GREEN, "middle",
            tracking=2.0)
        + "</g>"
    )

    # ---- legend, in its own band under a rule ------------------------------ #
    o.append(f'<path d="M34 1072 H 966" stroke="{DEEP_TEAL}" stroke-width="1.6" fill="none"/>')
    cols = [40, 372, 690]
    rows = [1096, 1120, 1144]

    def lg(col, row, swatch, text):
        x, y = cols[col], rows[row]
        o.append(swatch(x, y))
        o.append(T(text, x + 44, y + 4.5, 12.5, "regular", MIST_GREEN))

    lg(0, 0, lambda x, y: line(f"M{x} {y} H {x + 32}", width=2.3), "solid arrow = always")
    lg(
        0, 1,
        lambda x, y: f'<rect x="{x}" y="{y - 8}" width="32" height="16" rx="4" fill="none" '
                     f'stroke="{MIST_GREEN}" stroke-width="1.6" stroke-dasharray="9 7"/>',
        "dashed box = optional",
    )
    lg(0, 2, lambda x, y: loop(f"M{x} {y} H {x + 32}"), "dotted arrow = loop back")
    lg(1, 0, lambda x, y: person(x + 14, y - 2, 0.42), "person = you")
    lg(
        1, 1,
        lambda x, y: f'<path d="M{x + 16} {y - 10} L{x + 34} {y} L{x + 16} {y + 10} '
                     f'L{x - 2} {y} z" fill="{DEEP_TEAL}" stroke="{MIST_GREEN}" stroke-width="1.5"/>',
        "teal diamond = a decision only a human makes",
    )
    lg(
        1, 2,
        lambda x, y: f'<rect x="{x}" y="{y - 9}" width="32" height="18" rx="9" fill="{MIST_GREEN}"/>',
        "pale pill = end",
    )
    lg(2, 0, lambda x, y: mark_auto(x + 16, y, 8), "writes outside the chat, automatically")
    lg(2, 1, lambda x, y: mark_ask(x + 16, y, 9), "asks you first")
    o.append(
        T("10Clouds · dev — the build cycle", cols[2] + 44, rows[2] + 4.5, 12.5,
          "regular", MIST_GREEN, opacity=0.8)
    )
    o.append(
        T("the rail on the right is the ticket status (Jira today; tracker: none to skip)",
          cols[0], 1170, 12.5, "regular", MIST_GREEN)
    )

    alt = (
        "The 10c-dev build cycle. Invoking the implement skill on a ticket key moves the "
        "ticket to In Progress and feeds a large Build block with four numbered steps: the "
        "rung (R0 probe, R1 PoC, R2 MVP, R3 hardened), the interview with the developer, the "
        "tiny spec, and writing the code, which edits your checkout. Verify runs the app "
        "locally and loops back to step four when it fails. The diff is reviewed with a "
        "code-review skill adapted from Open Mercato, then an optional adversarial critic "
        "drives the running app: FAIL returns to step four, PASS goes on, and the critic can "
        "be skipped. Commit and push asks first and happens only on your yes; the ticket then "
        "moves to In Review on staging and waits until a human checks it in production — yes "
        "reaches Done, a bug opens a new ticket while this one stays In Review. Markers show "
        "which steps write outside the chat automatically and which ask first."
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {CYCLE_W} {CYCLE_H}" \
width="{CYCLE_W}" height="{CYCLE_H}" role="img" aria-label="{alt}">
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
<rect x="0" y="0" width="{CYCLE_W}" height="{CYCLE_H}" rx="20" fill="{DEEP_BLUE}"/>
<rect x="1.5" y="1.5" width="{CYCLE_W - 3}" height="{CYCLE_H - 3}" rx="20" fill="none" \
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
