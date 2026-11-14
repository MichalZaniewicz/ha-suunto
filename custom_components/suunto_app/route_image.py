"""Draw a workout's route as an image, for the route image entity (image.py).

The GPS track the integration already holds (``[[lat, lon, speed_kmh], ...]``,
see coordinator._normalize_route) drawn as a line coloured by speed, slow to
fast, with a dot at the start and the finish. No map underneath: free tile
servers forbid hotlinking from a distributed app (the Route card ran into
this), and the image is meant for a notification or a dashboard tile.

PNG through Pillow, which Home Assistant ships; SVG when Pillow is missing.
Pure functions, run in the executor.
"""

from __future__ import annotations

import io
import math

WIDTH = 800
HEIGHT = 500
PAD = 36
BACKGROUND = (28, 31, 34)
# Slow to fast, the same order the Route card uses for its pace colours.
PALETTE = [(79, 144, 196), (76, 154, 106), (224, 166, 62), (232, 132, 58), (199, 62, 62)]
START = (93, 180, 127)
FINISH = (240, 240, 240)


def _project(route: list[list[float]], width: int, height: int, pad: int) -> list[tuple[float, float]]:
    """Lat/lon to pixels, equirectangular with the latitude's scale, fitted
    into the frame and centred, north up."""
    lats = [p[0] for p in route]
    lons = [p[1] for p in route]
    mid = math.radians((min(lats) + max(lats)) / 2)
    xs = [lon * math.cos(mid) for lon in lons]
    ys = lats
    span_x = (max(xs) - min(xs)) or 1e-9
    span_y = (max(ys) - min(ys)) or 1e-9
    scale = min((width - 2 * pad) / span_x, (height - 2 * pad) / span_y)
    off_x = (width - span_x * scale) / 2
    off_y = (height - span_y * scale) / 2
    return [
        (off_x + (x - min(xs)) * scale, height - (off_y + (y - min(ys)) * scale))
        for x, y in zip(xs, ys)
    ]


def _color(speed: float, low: float, high: float) -> tuple[int, int, int]:
    if high <= low:
        return PALETTE[len(PALETTE) // 2]
    ratio = min(max((speed - low) / (high - low), 0.0), 1.0)
    return PALETTE[min(int(ratio * len(PALETTE)), len(PALETTE) - 1)]


def _speed_range(route: list[list[float]]) -> tuple[float, float]:
    """5th to 95th percentile of the moving speeds, so a stop or a GPS spike
    does not wash out the colours."""
    speeds = sorted(p[2] for p in route if len(p) > 2 and p[2] > 0)
    if not speeds:
        return 0.0, 0.0
    return speeds[int(len(speeds) * 0.05)], speeds[min(int(len(speeds) * 0.95), len(speeds) - 1)]


def render_png(route: list[list[float]]) -> bytes:
    """The route as PNG (2x drawn and scaled down for smooth lines)."""
    from PIL import Image, ImageDraw  # noqa: PLC0415 - optional, see render()

    factor = 2
    width, height, pad = WIDTH * factor, HEIGHT * factor, PAD * factor
    image = Image.new("RGB", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(image)
    points = _project(route, width, height, pad)
    low, high = _speed_range(route)
    line = 7 * factor
    for (a, b, point) in zip(points, points[1:], route[1:]):
        draw.line([a, b], fill=_color(point[2] if len(point) > 2 else 0, low, high), width=line)
        r = line / 2
        draw.ellipse([b[0] - r, b[1] - r, b[0] + r, b[1] + r], fill=_color(point[2] if len(point) > 2 else 0, low, high))
    for (x, y), color in ((points[-1], FINISH), (points[0], START)):
        r = 11 * factor
        draw.ellipse([x - r, y - r, x + r, y + r], fill=color, outline=BACKGROUND, width=3 * factor)
    image = image.resize((WIDTH, HEIGHT), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def render_svg(route: list[list[float]]) -> bytes:
    """The same drawing as SVG, when Pillow is not available."""
    points = _project(route, WIDTH, HEIGHT, PAD)
    low, high = _speed_range(route)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">',
        f'<rect width="100%" height="100%" fill="rgb{BACKGROUND}"/>',
    ]
    for (a, b, point) in zip(points, points[1:], route[1:]):
        color = _color(point[2] if len(point) > 2 else 0, low, high)
        parts.append(
            f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" '
            f'stroke="rgb{color}" stroke-width="7" stroke-linecap="round"/>'
        )
    for (x, y), color in ((points[-1], FINISH), (points[0], START)):
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="11" fill="rgb{color}" stroke="rgb{BACKGROUND}" stroke-width="3"/>'
        )
    parts.append("</svg>")
    return "".join(parts).encode()


def render(route: list[list[float]]) -> tuple[bytes, str] | None:
    """(image bytes, content type), or None for a route too short to draw."""
    route = [p for p in route if isinstance(p, (list, tuple)) and len(p) >= 2]
    if len(route) < 2:
        return None
    try:
        return render_png(route), "image/png"
    except ImportError:
        return render_svg(route), "image/svg+xml"
