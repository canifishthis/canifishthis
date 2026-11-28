"""The placed depth contours (T1268 W3): the ONE producer of the depth lines the tiles draw and of the per-lake depth
facts (AGENTS 56).

For each SHIPPING frozen placing only (`placings.shipping(CURATED.bathymetry.placings)`, T1267: a withdrawn row draws
nothing), nothing else:
  zip (hash-checked, `vectors.zip_path`) -> its depth arcs (CONTOUR not 0) -> metres (feet x 0.3048, the row's units)
  -> the row's pose (`refit.apply`: mirror, scale, turn about the sheet origin, shift; the owner's adjustment is already
  composed into it) -> cut at each of the row's lakes' FWA shoreline (`lake_outlines`): a two-lake sheet's lines go to
  the lake each piece lies in, a piece on land is clipped (D7: the share per lake recorded, every lake over
  `CLIP_REPORT_PCT` listed) -> pieces shorter than `MIN_PIECE_M` dropped -> sorted, deterministic output:

    GENERATED.bathymetry/placed/contours.geojsonl   one line per piece, EPSG:3005 (what `tiles.export_contours` reads)
    GENERATED.bathymetry/placed/lake_facts.json     per lake: deepest line, survey year, sheet, units + evidence
    GENERATED.bathymetry/placed/report.json         inputs (the placings' and the hash list's sha256), counts, clip
                                                    shares, the size gate

The tiles refuse a placed set made from other inputs (`require_current`), so a new freeze cannot ship old lines.

    scripts/heavy.sh placed 40 -- python -m pipeline.bathymetry.placed_contours
    python -m pipeline.bathymetry.placed_contours --check        # current for the frozen file? (no work)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

#: bump when the lines this writes change for the same inputs (the tiles' staleness check reads it)
VERSION = 1
FEET = 0.3048
#: (named minimum) a piece of a contour line shorter than this after the shoreline cut is dropped (metres on the ground)
MIN_PIECE_M = 15.0
#: D7 (planning chat's default): clip at the FWA shoreline; list every lake whose clipped share is over this (percent)
CLIP_REPORT_PCT = 5.0
#: the size gate (rule 20a): the placed lines may not hold more vertices than this; over it the producer refuses
MAX_VERTICES = 4_000_000
#: output coordinates rounded to this many decimals (metres, EPSG:3005): 1 cm, below any tile's precision
ROUND = 2
#: an index (labelled) line: every multiple of this many metres
INDEX_EVERY_M = 10.0
#: the FWA layers a placed lake's outline comes from (the fitter's own: refit_all reads lakes + manmade)
LAKE_LAYERS = ("lakes", "manmade")


def out_dir() -> Path:
    from pipeline.common.curated import GENERATED
    return Path(GENERATED.bathymetry) / "placed"


def inputs_now(placings_path: Optional[Path] = None, hashes_path: Optional[Path] = None) -> dict:
    """What the placed set must have been made from: the frozen file's and the zips' hash list's sha256, and VERSION."""
    from pipeline.common.curated import CURATED, SOURCE
    pp = Path(placings_path or CURATED.bathymetry.placings)
    hp = Path(hashes_path or SOURCE.bathymetry_vectors_sha256)
    return {"placings_sha256": hashlib.sha256(pp.read_bytes()).hexdigest(),
            "vectors_sha256": hashlib.sha256(hp.read_bytes()).hexdigest(), "version": VERSION}


class StalePlacedContours(RuntimeError):
    pass


COMMAND = "scripts/heavy.sh placed 40 -- python -m pipeline.bathymetry.placed_contours"


def require_current(directory: Optional[Path] = None, *, inputs: Optional[dict] = None) -> Path:
    """The placed contours file when it was made from the frozen placings as they are now; RAISES otherwise (missing,
    or made from another freeze, another zip list or another VERSION), naming the command."""
    d = Path(directory or out_dir())
    rep, lines = d / "report.json", d / "contours.geojsonl"
    if not rep.is_file() or not lines.is_file():
        raise StalePlacedContours(f"{d}: no placed depth contours, but the frozen placings have rows; make them: {COMMAND}")
    got = json.loads(rep.read_text(encoding="utf-8")).get("inputs")
    want = inputs or inputs_now()
    if got != want:
        raise StalePlacedContours(f"{d}: placed from other inputs ({got}) than the frozen placings now ({want}); "
                                  f"remake them: {COMMAND}")
    return lines


def lake_outlines(gpkg: Path, wbks: Iterable[int]) -> Dict[int, object]:
    """WATERBODY_KEY -> its FWA outline (the union of its polygons over `LAKE_LAYERS`), EPSG:3005."""
    import pyogrio
    from shapely.ops import unary_union
    want = sorted(set(int(w) for w in wbks))
    parts: Dict[int, list] = defaultdict(list)
    for layer in LAKE_LAYERS:
        for i in range(0, len(want), 300):
            chunk = want[i:i + 300]
            df = pyogrio.read_dataframe(gpkg, layer=layer, columns=["WATERBODY_KEY"],
                                        where="WATERBODY_KEY IN (%s)" % ",".join(map(str, chunk)))
            if df.crs is not None and df.crs.to_epsg() != 3005:
                df = df.to_crs(3005)
            for w, g in zip(df.WATERBODY_KEY, df.geometry):
                if g is not None and not g.is_empty:
                    parts[int(w)].append(g)
    return {w: unary_union(gs) for w, gs in sorted(parts.items())}


def _lines(g) -> List:
    if g.is_empty:
        return []
    t = g.geom_type
    if t == "LineString":
        return [g]
    if t in ("MultiLineString", "GeometryCollection"):
        return [x for p in g.geoms for x in _lines(p)]
    return []


def _merged(g) -> List:
    from shapely.ops import linemerge
    ls = _lines(g)
    if len(ls) > 1:
        m = linemerge(ls)
        ls = _lines(m)
    return ls


def depth_m(native: float, units: str) -> float:
    if units == "metres":
        return round(native, 1)
    if units == "feet":
        return round(native * FEET, 1)
    raise ValueError(f"units {units!r}: only feet or metres are placed")


def is_index(d_m: float) -> bool:
    return d_m > 0 and abs(d_m / INDEX_EVERY_M - round(d_m / INDEX_EVERY_M)) < 1e-9


def place_sheet(row: Mapping, contours: Iterable[Tuple], outlines: Mapping[int, object]) -> Tuple[List[dict], dict]:
    """One frozen row's depth arcs placed, cut per lake at the shoreline. Returns (pieces, stats).
    A piece: {item, wbk, sheet, depth_m, native, units, index, coords}. stats per lake: total / kept / clipped m,
    stubs dropped."""
    from shapely.geometry import LineString
    from pipeline.bathymetry.refit import Pose, apply
    p = row["pose"]
    pose = Pose(bool(p["mirror"]), float(p["scale"]), float(p["angle_deg"]), float(p["dx"]), float(p["dy"]))
    origin = (float(p["origin"][0]), float(p["origin"][1]))
    lakes = [(lk["item"], int(lk["wbk"].split(":")[1])) for lk in row["lakes"]]
    missing = [w for _i, w in lakes if w not in outlines]
    if missing:
        raise ValueError(f"{row['sheet']}: no FWA outline for lake(s) {missing} (layers {LAKE_LAYERS})")
    stats = {item: {"total_m": 0.0, "kept_m": 0.0, "stubs": 0, "stub_m": 0.0} for item, _w in lakes}
    pieces = []
    for cv, _fc, pts in contours:
        if cv in (None, 0) or len(pts) < 2:
            continue
        native = abs(float(cv))
        d = depth_m(native, row["units"])
        line = apply(LineString(pts), pose, origin)
        if line.length == 0:
            continue
        inside = [(item, w, line.intersection(outlines[w])) for item, w in lakes]
        owner = max(inside, key=lambda t: (t[2].length, t[0]))[0]      # the lake that holds most of it
        stats[owner]["total_m"] += line.length
        for item, w, part in inside:
            for piece in _merged(part):
                if piece.length < MIN_PIECE_M:
                    stats[item]["stubs"] += 1
                    stats[item]["stub_m"] += piece.length
                    continue
                stats[item]["kept_m"] += piece.length
                if item != owner:
                    stats[item]["total_m"] += piece.length              # a crossing piece counts for the lake it is in
                    stats[owner]["total_m"] -= piece.length
                pieces.append({"item": item, "wbk": f"wbk:{w}", "sheet": row["sheet"], "depth_m": d,
                               "native": native, "units": row["units"], "index": is_index(d),
                               "coords": [(round(x, ROUND), round(y, ROUND)) for x, y in piece.coords]})
    return pieces, stats


def facts_row(row: Mapping, pieces: List[dict], item: str, wbk: str) -> dict:
    mine = [p for p in pieces if p["item"] == item]
    dd = row.get("draft_date")
    return {"item": item, "wbk": int(wbk.split(":")[1]),
            "deepest_m": max((p["depth_m"] for p in mine), default=None),
            "contours": len({p["depth_m"] for p in mine}),
            "sheet": row["sheet"], "zip": row["zip"], "coverage": row["coverage"], "title": row.get("title"),
            "draft_date": dd, "survey_year": int(dd[:4]) if dd else None,
            "units": row["units"], "units_evidence": row["units_evidence"],
            "two_lake_sheet": len(row["lakes"]) > 1, "accepted_as": row["accepted_as"]}


def build(frozen: Mapping, *, read_contours, outlines: Mapping[int, object], inputs: dict) -> Tuple[list, dict, dict]:
    """(pieces sorted, facts, report) for every SHIPPING frozen row (`placings.shipping`: a withdrawn row draws
    nothing). `read_contours(row)` -> the sheet's (CONTOUR, FCODE, pts)."""
    from pipeline.bathymetry.placings import shipping
    rows = shipping(frozen)
    pieces: List[dict] = []
    facts, per_lake = [], {}
    for row in sorted(rows, key=lambda r: r["sheet"]):
        ps, st = place_sheet(row, read_contours(row), outlines)
        pieces += ps
        for lk in row["lakes"]:
            facts.append(facts_row(row, ps, lk["item"], lk["wbk"]))
            s = st[lk["item"]]
            clipped = max(0.0, s["total_m"] - s["kept_m"] - s["stub_m"])
            per_lake[lk["item"]] = {"sheet": row["sheet"], "title": row.get("title"),
                                    "total_m": round(s["total_m"], 1), "kept_m": round(s["kept_m"], 1),
                                    "clipped_pct": round(100 * clipped / s["total_m"], 2) if s["total_m"] else 0.0,
                                    "stubs_dropped": s["stubs"], "stub_m": round(s["stub_m"], 1)}
    pieces.sort(key=lambda p: (p["item"], p["depth_m"], p["coords"][0], p["coords"][-1], len(p["coords"])))
    facts.sort(key=lambda f: f["item"])
    vertices = sum(len(p["coords"]) for p in pieces)
    over = sorted(((v["clipped_pct"], k) for k, v in per_lake.items() if v["clipped_pct"] > CLIP_REPORT_PCT),
                  reverse=True)
    report = {"inputs": inputs, "rows": len(rows), "withdrawn_not_drawn": len(frozen["placings"]) - len(rows),
              "lakes": len(facts), "pieces": len(pieces),
              "vertices": vertices, "index_pieces": sum(1 for p in pieces if p["index"]),
              "clipped_over_pct": [{"item": k, "clipped_pct": pct, "sheet": per_lake[k]["sheet"],
                                    "title": per_lake[k]["title"]} for pct, k in over],
              "per_lake": dict(sorted(per_lake.items())),
              "policy": {"MIN_PIECE_M": MIN_PIECE_M, "CLIP_REPORT_PCT": CLIP_REPORT_PCT,
                         "MAX_VERTICES": MAX_VERTICES, "INDEX_EVERY_M": INDEX_EVERY_M, "FEET": FEET}}
    if vertices > MAX_VERTICES:
        raise RuntimeError(f"placed depth contours: {vertices:,} vertices, over the gate MAX_VERTICES "
                           f"{MAX_VERTICES:,}; nothing written")
    return pieces, {"schema": "bathy-lake-facts/1", "placings_sha256": inputs["placings_sha256"], "lakes": facts}, report


def write(directory: Path, pieces: list, facts: dict, report: dict) -> None:
    """The three files, each atomically; the report LAST (it is what says the set is current)."""
    import os
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    rep = d / "report.json"
    if rep.exists():
        rep.unlink()                     # a half-written set is never current
    tmp = d / "contours.geojsonl.tmp"
    with tmp.open("w", encoding="utf-8") as f:
        for p in pieces:
            props = {k: p[k] for k in ("item", "wbk", "sheet", "depth_m", "native", "units", "index")}
            f.write(json.dumps({"type": "Feature", "properties": props,
                                "geometry": {"type": "LineString", "coordinates": p["coords"]}},
                               separators=(",", ":")) + "\n")
    os.replace(tmp, d / "contours.geojsonl")
    facts = dict(facts, _about="GENERATED by pipeline.bathymetry.placed_contours (T1268) from the frozen placings: "
                               "per lake the deepest contour line drawn (metres, not a sounding), the sheet's draft "
                               "year, the chart number and its units with the evidence. One producer (AGENTS 56).")
    (d / "lake_facts.json.tmp").write_text(json.dumps(facts, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(d / "lake_facts.json.tmp", d / "lake_facts.json")
    (d / "report.json.tmp").write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(d / "report.json.tmp", rep)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="the placed depth contours from the frozen placings (T1268)")
    ap.add_argument("--check", action="store_true", help="is the placed set current for the frozen file? no work")
    ap.add_argument("--out", type=Path, help="another folder (a side run); default GENERATED.bathymetry/placed")
    ap.add_argument("--gpkg", type=Path, help="default SOURCE.fwa_gpkg")
    a = ap.parse_args(argv)
    from pipeline.bathymetry import e00, placings, vectors
    from pipeline.common.curated import SOURCE
    d = a.out or out_dir()
    frozen = placings.load()
    if a.check:
        if not placings.shipping(frozen):
            print("no shipping frozen placings: nothing to place")
            return 0
        print(require_current(d))
        return 0
    inputs = inputs_now()
    rows = placings.shipping(frozen)
    wbks = [int(lk["wbk"].split(":")[1]) for r in rows for lk in r["lakes"]]
    outlines = lake_outlines(Path(a.gpkg or SOURCE.fwa_gpkg), wbks)

    def read_contours(row):
        z = vectors.zip_path(row["zip"])
        if vectors.zip_sha256(row["zip"]) != row["zip_sha256"]:
            raise vectors.VectorSourceError(f"{row['zip']}: the committed hash differs from the one frozen with "
                                            f"placing {row['sheet']}")
        sh = [s for s in e00.read_zip_all(z) if s.lines.name == row["coverage"]]
        if len(sh) != 1:
            raise e00.E00Error(f"{z}: {len(sh)} coverages named {row['coverage']}")
        return sh[0].contours()

    pieces, facts, report = build(frozen, read_contours=read_contours, outlines=outlines, inputs=inputs)
    write(d, pieces, facts, report)
    print(f"{report['rows']} sheets, {report['lakes']} lakes, {report['pieces']:,} pieces, {report['vertices']:,} "
          f"vertices; {len(report['clipped_over_pct'])} lakes over {CLIP_REPORT_PCT} % clipped -> {d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
