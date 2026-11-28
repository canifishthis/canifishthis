"""Zoom ladders — which features exist at which zoom, and why.

This is the whole of "natural complexity reduction", and it is deliberately a pure
function of one attribute per geometry kind so it can be tested without a tile in
sight. Tippecanoe honours a per-feature ``tippecanoe.minzoom``, so the ladder is
applied by stamping every feature rather than by running a different build per zoom.

LINES use FWA **stream magnitude** (the count of headwater streams above a reach),
not Strahler order. Order jumps in big steps — 578 features at >=7, then 10,767 at
>=5, then 48,107 at >=4 — so a ladder built on it either shows almost nothing or
almost everything. Magnitude is nearly continuous and it drops small tributaries
while keeping whole big rivers, which is the picture people expect.

    magnitude >=   20000    1000     250     100      50      20      10       5       0
    features          101   1,122   4,569  11,947  24,049  59,906 114,251 217,568 2,053,299
    zoom                4       6       7       8       9      10      11      12      13

THE ARCHIVE STOPS AT z13 (T85, decisions D32, 2026-10-24): every reach is drawn from z13, the
bottom rung, and MapLibre overzooms the z13 tile to the camera's z18. z14 was 58% of the atlas
(315.7 of 548.3 MB, measured on the live archive; the new z13 takes on most of its content, see
`tippe.SIMPLIFICATION_AT_MAX`); the z13 tile is simplified at the top zoom with
`tippe.SIMPLIFICATION_AT_MAX`, which holds the ground error of the old z14 (about 4 m).

POLYGONS use area against the size of a pixel at that zoom, so a lake appears when
it is big enough to see rather than when a hand-picked hectare threshold says so.
"""

from __future__ import annotations

import math

# (minimum magnitude, zoom the feature first appears at). Descending.
MAGNITUDE_LADDER: tuple[tuple[int, int], ...] = (
    (20000, 4), (5000, 5), (1000, 6), (250, 7), (100, 8),
    (50, 9), (20, 10), (10, 11), (5, 12), (0, 13),
)

MIN_ZOOM = 4
#: The archive's deepest zoom (T85: was 14). `app/packages/core/src/ladder.ts` ATLAS_MAX_ZOOM is held to
#: it (`test_tiles.py`, `tools/overzoom.test.ts`).
MAX_ZOOM = 13

# Web-mercator ground resolution at the equator, metres per pixel at z0 (256 px tiles).
_EQUATOR_M_PER_PX_Z0 = 156543.03392804097
# BC spans ~48.3N to 60N; use the middle so the ladder is not tuned to one corner.
_BC_LAT_COS = math.cos(math.radians(54.0))
# A polygon is worth drawing when its side is about this many pixels.
_VISIBLE_PX = 3.0


def metres_per_pixel(zoom: int) -> float:
    """Ground resolution at ``zoom``, at BC's middle latitude."""
    return _EQUATOR_M_PER_PX_Z0 * _BC_LAT_COS / (2 ** zoom)


def zoom_for_magnitude(magnitude: int | None, floor: int = MIN_ZOOM) -> int:
    """First zoom a stream of this magnitude is drawn at.

    ``None`` and 0 both mean "no magnitude recorded", which is a headwater or an
    artifact; either way it belongs at the bottom of the ladder, never hidden
    entirely — the atlas is what makes the map look like the country.
    """
    m = magnitude or 0
    for threshold, zoom in MAGNITUDE_LADDER:
        if m >= threshold:
            return max(zoom, floor)
    return max(MAX_ZOOM, floor)


def zoom_for_area(area_m2: float | None, floor: int = MIN_ZOOM,
                  visible_px: float = _VISIBLE_PX) -> int:
    """First zoom a polygon of this area is drawn at.

    Derived, not chosen: a polygon appears once its side exceeds ``visible_px``
    pixels. Drawing a 2-hectare pond at z6 costs bytes to render a sub-pixel dot.
    """
    a = area_m2 or 0.0
    if a <= 0:
        return max(MAX_ZOOM, floor)
    side = math.sqrt(a)
    for z in range(MIN_ZOOM, MAX_ZOOM + 1):
        if side >= visible_px * metres_per_pixel(z):
            return max(z, floor)
    return max(MAX_ZOOM, floor)


#: (T1268) THE DEPTH-LINE LADDER, decided PER SHEET from the sheet's own levels in its NATIVE unit (the values printed on
#: the chart; never the converted metres, where 10 ft = 3.048 m is a multiple of nothing). The index step is the
#: smallest "nice" step (`NICE_STEPS`: 1, 2, 5 x a power of ten) that leaves the sheet between `INDEX_LINES_MIN` and
#: `INDEX_LINES_MAX` index levels; the middle step is the next finer nice step. Index lines (labelled) from z11, middle
#: from z12, every other line from z13. A sheet with one level: that line is its index. So every accepted lake has at
#: least one index line at z11, and a deep lake is not flooded. (Fixed 10 m / 100 ft steps, review of 2026-11-28: 111
#: of 322 lakes had no index line, 18 drew nothing until z13.)
NICE_STEPS = tuple(round(m * 10 ** k, 6) for k in range(-1, 4) for m in (1, 2, 5))
INDEX_LINES_MIN = 2
INDEX_LINES_MAX = 6


def _on(value: float, step: float) -> bool:
    return value > 0 and abs(value / step - round(value / step)) < 1e-6


def sheet_ladder(levels) -> tuple[float, float]:
    """(index step, middle step) for one sheet's depth levels (native unit). Raises on a sheet with no level."""
    lv = sorted({abs(float(v)) for v in levels if v and abs(float(v)) > 0})
    if not lv:
        raise ValueError("a sheet with no depth level has no ladder")
    if len(lv) == 1:
        return lv[0], lv[0]                       # its one line is its index
    fallback = None
    for i, step in enumerate(NICE_STEPS):
        n = sum(1 for v in lv if _on(v, step))
        if INDEX_LINES_MIN <= n <= INDEX_LINES_MAX:
            return step, NICE_STEPS[i - 1] if i else step
        if fallback is None and 1 <= n < INDEX_LINES_MIN:
            fallback = (step, NICE_STEPS[i - 1] if i else step)
    if fallback is None:
        raise ValueError(f"levels {lv[:8]}...: no nice step leaves an index line")
    return fallback                               # the levels jump past the band: the first step with one index line


def depth_line_zoom(native: float, ladder_steps: tuple[float, float], floor: int = 11) -> tuple[int, bool]:
    """(minzoom, index) of one depth line from its NATIVE value and its sheet's (index step, middle step)."""
    index_step, mid_step = ladder_steps
    d = abs(float(native))
    if _on(d, index_step):
        return max(floor, 11), True
    if _on(d, mid_step):
        return max(floor, 12), False
    return max(floor, 13), False
