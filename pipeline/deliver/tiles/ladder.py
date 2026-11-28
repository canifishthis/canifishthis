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


#: (T1268) THE DEPTH-LINE LADDER, decided on the sheet's NATIVE unit (the value printed on the chart), never on the
#: converted metres: {units: (index every, z12 every)}. An index line (labelled) is drawn from z11, a z12 line from z12,
#: every other line from z13. Metres: 10 m / 5 m. Feet: 100 ft / 50 ft, measured 2026-11-28 on the 322 frozen lakes so a
#: feet lake is about as dense per zoom as a metre lake (median share of a lake's lines at z11 / up to z12: metre sheets
#: 0.05 / 0.11; feet 100/50 0.07 / 0.12; feet 50/25 0.12 / 0.13; feet 50/10 0.12 / 1.0). The converted 10 ft = 3.048 m is
#: a multiple of nothing, so a metres rule on feet sheets drew no line below z13 (Charlotte Lake: 0 at z12).
DEPTH_LADDER = {"metres": (10.0, 5.0), "feet": (100.0, 50.0)}


def depth_line_zoom(native: float, units: str, floor: int = 11) -> tuple[int, bool]:
    """(minzoom, index) of one depth line from its NATIVE value and its sheet's units (`DEPTH_LADDER`). Raises on a
    unit the ladder does not know (a line is never drawn on a guessed unit)."""
    if units not in DEPTH_LADDER:
        raise ValueError(f"depth line in {units!r}: the ladder knows {sorted(DEPTH_LADDER)}")
    every_index, every_mid = DEPTH_LADDER[units]
    d = abs(float(native))

    def on(step):
        return d > 0 and abs(d / step - round(d / step)) < 1e-9

    if on(every_index):
        return max(floor, 11), True
    if on(every_mid):
        return max(floor, 12), False
    return max(floor, 13), False
