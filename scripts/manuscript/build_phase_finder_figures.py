from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "manuscript_assets" / "phase_finder"
OUT.mkdir(parents=True, exist_ok=True)

INK = "#20252b"
MUTED = "#626b73"
BLUE = "#276fbf"
BLUE_LIGHT = "#eaf2fb"
GREEN = "#2f7d5a"
GREEN_LIGHT = "#eaf5ef"
RED = "#b23a3a"
RED_LIGHT = "#faeeee"
WHITE = "#ffffff"

FONT_REGULAR = "/System/Library/Fonts/Supplemental/Arial.ttf"
FONT_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"


@dataclass
class Canvas:
    width: int
    height: int
    scale: int = 6

    def __post_init__(self) -> None:
        self.image = Image.new("RGB", (self.width * self.scale, self.height * self.scale), WHITE)
        self.draw = ImageDraw.Draw(self.image)
        self.svg: list[str] = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" height="{self.height}" '
            f'viewBox="0 0 {self.width} {self.height}">',
            '<rect width="100%" height="100%" fill="white"/>',
        ]

    def font(self, size: float, bold: bool = False):
        return ImageFont.truetype(FONT_BOLD if bold else FONT_REGULAR, max(6, round(size * self.scale)))

    def text(self, x, y, value, size=9, color=INK, bold=False, anchor="mm", rotate=0):
        px, py = round(x * self.scale), round(y * self.scale)
        self.draw.text((px, py), value, font=self.font(size, bold), fill=color, anchor=anchor)
        weight = "700" if bold else "400"
        svg_anchor = {"mm": "middle", "lm": "start", "rm": "end", "la": "start", "ma": "middle"}.get(anchor, "middle")
        baseline = "middle" if anchor.endswith("m") else "alphabetic"
        transform = f' transform="rotate({rotate} {x} {y})"' if rotate else ""
        self.svg.append(
            f'<text x="{x}" y="{y}" font-family="Arial, sans-serif" font-size="{size}" '
            f'font-weight="{weight}" fill="{color}" text-anchor="{svg_anchor}" '
            f'dominant-baseline="{baseline}"{transform}>{escape(value)}</text>'
        )

    def rounded_rect(self, x, y, w, h, fill=WHITE, outline=INK, radius=7, width=1):
        coords = tuple(round(v * self.scale) for v in (x, y, x + w, y + h))
        self.draw.rounded_rectangle(coords, radius=round(radius * self.scale), fill=fill, outline=outline, width=max(1, round(width * self.scale)))
        self.svg.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" '
            f'fill="{fill}" stroke="{outline}" stroke-width="{width}"/>'
        )

    def line(self, points, color=INK, width=1):
        scaled = [(round(x * self.scale), round(y * self.scale)) for x, y in points]
        self.draw.line(scaled, fill=color, width=max(1, round(width * self.scale)), joint="curve")
        values = " ".join(f"{x},{y}" for x, y in points)
        self.svg.append(f'<polyline points="{values}" fill="none" stroke="{color}" stroke-width="{width}"/>')

    def circle(self, x, y, r, fill=WHITE, outline=INK, width=1):
        coords = tuple(round(v * self.scale) for v in (x - r, y - r, x + r, y + r))
        self.draw.ellipse(coords, fill=fill, outline=outline, width=max(1, round(width * self.scale)))
        self.svg.append(
            f'<circle cx="{x}" cy="{y}" r="{r}" fill="{fill}" stroke="{outline}" stroke-width="{width}"/>'
        )

    def triangle(self, x, y, size=5, fill=WHITE, outline=RED, width=1):
        pts = [(x, y + size), (x - size, y - size), (x + size, y - size)]
        scaled = [(round(px * self.scale), round(py * self.scale)) for px, py in pts]
        self.draw.polygon(scaled, fill=fill, outline=outline)
        values = " ".join(f"{px},{py}" for px, py in pts)
        self.svg.append(f'<polygon points="{values}" fill="{fill}" stroke="{outline}" stroke-width="{width}"/>')

    def arrow(self, x1, y1, x2, y2, color=MUTED, width=1.2):
        self.line([(x1, y1), (x2, y2)], color, width)
        dx, dy = x2 - x1, y2 - y1
        length = max((dx * dx + dy * dy) ** 0.5, 1)
        ux, uy = dx / length, dy / length
        px, py = -uy, ux
        tip = (x2, y2)
        left = (x2 - ux * 7 + px * 3.2, y2 - uy * 7 + py * 3.2)
        right = (x2 - ux * 7 - px * 3.2, y2 - uy * 7 - py * 3.2)
        scaled = [(round(x * self.scale), round(y * self.scale)) for x, y in (tip, left, right)]
        self.draw.polygon(scaled, fill=color)
        self.svg.append(
            f'<polygon points="{tip[0]},{tip[1]} {left[0]},{left[1]} {right[0]},{right[1]}" fill="{color}"/>'
        )

    def save(self, stem: str, dpi=600):
        self.svg.append("</svg>")
        (OUT / f"{stem}.svg").write_text("\n".join(self.svg), encoding="utf-8")
        self.image.save(OUT / f"{stem}.png", dpi=(dpi, dpi), optimize=True)


def centered_lines(c: Canvas, x, y, lines, size, color=INK, bold=False, spacing=30):
    values = str(lines).split("\n")
    start = y - spacing * (len(values) - 1) / 2
    for index, value in enumerate(values):
        c.text(x, start + index * spacing, value, size, color, bold)


def node(c: Canvas, x, y, w, h, title, subtitle, fill, edge):
    c.rounded_rect(x, y, w, h, fill, edge, radius=7, width=1.1)
    centered_lines(c, x + w / 2, y + h * 0.32, title, 27, INK, True, 31)
    centered_lines(c, x + w / 2, y + h * 0.72, subtitle, 26, MUTED, False, 29)


def workflow_figure() -> None:
    c = Canvas(1088, 820)
    c.text(24, 35, "Experimental evidence", 29, BLUE, True, "lm")
    c.text(394, 35, "Candidate generation", 29, GREEN, True, "lm")
    c.text(764, 35, "Iterative interpretation", 29, RED, True, "lm")

    node(c, 24, 78, 300, 130, "Experimental PXRD", "2theta and intensity", BLUE_LIGHT, BLUE)
    node(c, 24, 300, 300, 130, "Preprocessing", "smoothing • background\nactive range", WHITE, BLUE)
    node(c, 24, 522, 300, 130, "Experimental lines", "position • area\nindividual FWHM", BLUE_LIGHT, BLUE)
    c.arrow(174, 208, 174, 300, BLUE, 2.0)
    c.arrow(174, 430, 174, 522, BLUE, 2.0)

    node(c, 394, 78, 300, 130, "Sources + user CIF", "COD • MP • AFLOW\nOQMD • RRUFF", GREEN_LIGHT, GREEN)
    node(c, 394, 300, 300, 130, "Indexed cache", "metadata • chemistry\nreflection lists", WHITE, GREEN)
    node(c, 394, 522, 300, 130, "Candidate patterns", "calculated profiles\nor reference lines", GREEN_LIGHT, GREEN)
    c.arrow(544, 208, 544, 300, GREEN, 2.0)
    c.arrow(544, 430, 544, 522, GREEN, 2.0)
    c.arrow(324, 587, 394, 587, MUTED, 2.0)

    node(c, 764, 78, 300, 130, "Match ranking", "global agreement", RED_LIGHT, RED)
    node(c, 764, 260, 300, 130, "Selected phases", "explained peaks\nand fitted profiles", WHITE, RED)
    node(c, 764, 442, 300, 130, "Staged Gain ranking", "direct • overlap\nhidden evidence", RED_LIGHT, RED)
    node(c, 764, 624, 300, 130, "Phase hypothesis", "inspect • save • export\nrevise the phase set", WHITE, RED)
    c.line([(694, 587), (714, 587), (714, 143)], MUTED, 2.0)
    c.arrow(714, 143, 764, 143, MUTED, 2.0)
    c.arrow(914, 208, 914, 260, RED, 2.0)
    c.arrow(914, 390, 914, 442, RED, 2.0)
    c.arrow(914, 572, 914, 624, RED, 2.0)
    c.line([(764, 507), (744, 507), (744, 325)], RED, 2.0)
    c.arrow(744, 325, 764, 325, RED, 2.0)
    c.text(732, 416, "add phase", 26, RED, True, "mm", rotate=-90)
    c.text(24, 790, "Candidates are proposed; preprocessing and phase acceptance remain under user control.", 26, MUTED, False, "lm")
    c.save("fig1_workflow")


def baseline(c: Canvas, x1, x2, y):
    c.line([(x1, y), (x2, y)], MUTED, 0.8)
    for x in (x1 + 55, x1 + 110, x1 + 165):
        c.line([(x, y), (x, y + 5)], MUTED, 0.7)


def stick_set(c: Canvas, x0, y0, positions, heights, color, scale_x=2.25, scale_y=120, width=2.1):
    for pos, height in zip(positions, heights, strict=False):
        x = x0 + (pos - 8) * scale_x
        c.line([(x, y0), (x, y0 - height * scale_y)], color, width)


def match_gain_figure() -> None:
    c = Canvas(1088, 920)
    panel_w = 508
    panel_h = 390
    panel_positions = [(24, 30), (556, 30), (24, 444), (556, 444)]
    for x, y in panel_positions:
        c.rounded_rect(x, y, panel_w, panel_h, WHITE, "#b7bdc3", 5, 0.9)

    obs_x = [12, 21, 33, 43, 58, 71, 84]
    obs_h = [0.55, 0.42, 1.00, 0.32, 0.72, 0.45, 0.35]
    cand_x = [12.2, 21.1, 32.8, 58.2, 83.8]
    cand_h = [0.50, 0.35, 0.92, 0.68, 0.30]
    scale_x = 4.45
    scale_y = 105

    x, y = panel_positions[0]
    c.text(x + 18, y + 35, "(a) Experimental lines", 29, INK, True, "lm")
    c.text(x + 18, y + 80, "profile → position, area and FWHM", 26, MUTED, False, "lm")
    base_y = y + 275
    profile_points = []
    for offset in range(0, 385, 3):
        signal = 7.0
        for centre, amplitude, width in ((55, 72, 11), (155, 125, 14), (272, 88, 12), (342, 48, 16)):
            signal += amplitude * math.exp(-0.5 * ((offset - centre) / width) ** 2)
        profile_points.append((x + 60 + offset, base_y - signal))
    c.line(profile_points, INK, 2.2)
    c.line([(x + 52, base_y), (x + 455, base_y)], MUTED, 1.0)
    for offset, height in ((55, 55), (155, 88), (272, 65), (342, 38)):
        c.line([(x + 60 + offset, base_y + 12), (x + 60 + offset, base_y + 12 + height)], BLUE, 2.8)
    c.text(x + 438, y + 132, "observed profile", 26, INK, False, "rm")
    c.rounded_rect(x + 48, y + 328, 262, 40, WHITE, WHITE, 0, 0)
    c.text(x + 60, y + 348, "integrated line records", 26, BLUE, False, "lm")

    x, y = panel_positions[1]
    c.text(x + 18, y + 35, "(b) Global Match", 29, INK, True, "lm")
    c.text(x + 18, y + 80, "two-way coverage after bounded alignment", 25, MUTED, False, "lm")
    base_y = y + 250
    baseline(c, x + 55, x + 455, base_y)
    stick_set(c, x + 55, base_y, obs_x, obs_h, INK, scale_x, scale_y)
    stick_set(c, x + 55, base_y + 3, cand_x, [-0.48 * h for h in cand_h], BLUE, scale_x, scale_y)
    c.text(x + 55, y + 120, "strong observed anchors", 26, INK, False, "lm")
    c.text(x + 55, y + 335, "candidate reflection support", 26, BLUE, False, "lm")

    x, y = panel_positions[2]
    c.text(x + 18, y + 35, "(c) Condition on selected phases", 29, INK, True, "lm")
    c.text(x + 18, y + 80, "joint non-negative fit reveals deficits", 25, MUTED, False, "lm")
    base_y = y + 250
    baseline(c, x + 55, x + 455, base_y)
    stick_set(c, x + 55, base_y, obs_x, obs_h, INK, scale_x, scale_y)
    stick_set(c, x + 55, base_y, [12, 21, 33, 58], [0.50, 0.38, 0.92, 0.66], GREEN, scale_x, scale_y, 5.0)
    for pos, height in zip([43, 71, 84], [0.32, 0.45, 0.35], strict=False):
        px = x + 55 + (pos - 8) * scale_x
        py = base_y - height * scale_y - 14
        c.triangle(px, py, 6, WHITE, RED)
    c.text(x + 55, y + 335, "uncovered and under-fitted lines", 26, RED, False, "lm")

    x, y = panel_positions[3]
    c.text(x + 18, y + 35, "(d) Staged Gain", 29, INK, True, "lm")
    c.text(x + 18, y + 80, "direct → overlap → hidden evidence", 25, MUTED, False, "lm")
    base_y = y + 225
    baseline(c, x + 55, x + 455, base_y)
    stick_set(c, x + 55, base_y, [43, 71, 84], [0.32, 0.45, 0.35], INK, scale_x, scale_y)
    stick_set(c, x + 55, base_y + 5, [12, 21, 33, 58], [-0.16, -0.14, -0.25, -0.18], MUTED, scale_x, scale_y, 1.7)
    stick_set(c, x + 55, base_y + 5, [42.9, 71.2, 84.1], [-0.30, -0.40, -0.31], RED, scale_x, scale_y, 2.8)
    c.text(x + panel_w / 2, y + 300, "reward supported deficits", 26, RED)
    c.text(x + panel_w / 2, y + 346, "penalize duplicates and absent strong lines", 25, MUTED)

    c.text(544, 858, "Match tests global compatibility.", 25, INK, True)
    c.text(544, 890, "Gain measures added evidence after selected phases are fitted.", 25, INK, True)
    c.save("fig4_match_gain")


def graphical_abstract() -> None:
    c = Canvas(1088, 460)
    c.text(544, 42, "Open, inspectable phase identification", 31, INK, True)
    node(c, 24, 120, 240, 150, "Experimental PXRD", "pattern + optional\nchemistry", BLUE_LIGHT, BLUE)
    node(c, 300, 120, 240, 150, "Open candidates", "databases +\nuser CIF files", GREEN_LIGHT, GREEN)
    node(c, 576, 120, 210, 150, "Match", "global\nagreement", RED_LIGHT, RED)
    node(c, 822, 120, 240, 150, "Gain", "additional\nexplanation", RED_LIGHT, RED)
    c.arrow(264, 195, 300, 195, width=2.0)
    c.arrow(540, 195, 576, 195, width=2.0)
    c.arrow(786, 195, 822, 195, width=2.0)
    c.arrow(942, 270, 681, 345, RED, 2.0)
    c.text(814, 405, "iterative phase model", 28, RED)
    c.save("graphical_abstract")


if __name__ == "__main__":
    workflow_figure()
    match_gain_figure()
    graphical_abstract()
    print(OUT)
