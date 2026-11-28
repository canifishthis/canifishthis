"""The frozen ACCEPTED placings of the vector depth sheets (T1267 W1): the ONLY writer of `CURATED.bathymetry.placings`.

Owner, 2026-11-28: nothing of a lake's depth ships without its placing in this frozen file. Which placings, in his
words: "every high one plus all the ones i review. in the end it should be all of them" and "Ship them with the high
ones". So a sheet is ACCEPTED when
  * the fitter run of record classes it `high` or `high_stretched` (`ACCEPT_CLASSES`), or
  * the owner marked its chart `right` or `right_adjusted` on the review page (`ACCEPT_MARKS`);
and NEVER when he marked it `wrong_lake`, `wrong_fit` or `unsure` (`NEVER_MARKS`), whatever its class.

A mark judges the placing the review page SHOWED when it was saved, so a marked row's pose is that page's pose (its
own fitter run, `--page`), plus his adjustment EXACTLY as saved (`compose`), never the adjustment laid over another
run's pose. The page shows one run until a switch time (`--page LABEL:DATA:REFIT[:UNTIL]`, in order); a mark whose time
cannot be placed is refused and listed. The run of record's own pose for a marked sheet is REPORTED when it disagrees,
never applied.

An ACCEPTED ROW IS NEVER REWRITTEN: a rerun appends new acceptances only and reports every row it would now make
differently (`rerun_disagrees`). Held-out sheets are not rows; they are listed, by reason, in the generated report
(`GENERATED.bathymetry / "placings_report.json"`).

Held out (each a named rule, flippable): the units (`UNITS_UNSTATED`, D2: a sheet whose vector file states no unit
waits for its printed chart's words in `CURATED.bathymetry.sheet_units`), a no-data depth code the arcs cannot prove
(`NO_DATA_DEPTHS`), an older survey of a lake two surveys cover (`SURVEYS_PER_LAKE`, D9), a lake with no single registry
item, an adjustment the page's own maths does not reproduce (`OVERLAP_TOLERANCE`).

    python -m pipeline.bathymetry.placings --freeze --run-label v5 --marks MARKS.json \\
        --page v2:PAGE_DATA_DIR:V2_REFIT.json --by OWNER [--dry-run]
    python -m pipeline.bathymetry.placings --check                # every row's zip proved, the schema whole
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np

SCHEMA = "bathy-placings/1"
UNITS_SCHEMA = "bathy-sheet-units/1"

# ------------------------------------------------------------------ the policy: named, flippable (owner decisions)

#: D1 (owner 2026-11-28): the run-of-record classes taken without a mark.
ACCEPT_CLASSES = ("high", "high_stretched")
#: D1: the owner's verdicts that accept a chart, whatever its class.
ACCEPT_MARKS = ("right", "right_adjusted")
#: D1: the owner's verdicts that NEVER accept a chart, even a `high` one.
NEVER_MARKS = ("wrong_lake", "wrong_fit", "unsure")
#: D2 (planning chat's default, the owner sees it): a sheet whose vector file states no depth unit is
#: "read": accepted only with its printed chart's unit in `sheet_units.json` (the words, where, the page);
#: "hold": held out whatever the chart says;  "feet": taken as feet without reading (NOT the default).
UNITS_UNSTATED = "read"
#: the feet -> metres factor (exact, international foot)
FEET = 0.3048
#: Depth values the Province's files use as a code, not a depth. A sheet carrying one is held out: the arc data cannot
#: prove what it stands for (Albert Head Lagoon 00019301: 14 arcs at 999 beside the 1 m line, where the chart prints
#: 0.5 and 1.5 m lines). Flip to drop only those arcs once the owner rules them no-data.
NO_DATA_DEPTHS = (999.0,)
#: D9 (planning chat's default): a lake two accepted surveys cover takes "newest" (the later draft date) only; "all"
#: keeps every survey.
SURVEYS_PER_LAKE = "newest"
#: The page's own overlap (a 220-cell raster IoU) recomputed here must land within this of the figure the mark saved,
#: or the adjustment is refused as not understood.
OVERLAP_TOLERANCE = 0.02
#: Two poses AGREE when no corner of the sheet's box moves more than this (metres).
POSE_AGREE_M = 1.0
#: The page's raster size (script.js `RC`).
PAGE_RASTER = 220


# ------------------------------------------------------------------ poses and the review page's adjustment maths

def mat(angle_deg: float, scale: float, mirror: bool) -> np.ndarray:
    """The linear part of a pose: mirror (x -> -x) first, then scale, then turn counter-clockwise (refit.apply)."""
    r = math.radians(angle_deg)
    c, s = math.cos(r), math.sin(r)
    return np.array([[c, -s], [s, c]]) @ np.diag([scale, scale]) @ np.diag([-1.0 if mirror else 1.0, 1.0])


def decompose(L: np.ndarray) -> Tuple[bool, float, float]:
    """(mirror, scale, angle_deg) with mat(angle, scale, mirror) == L, angle in [0, 360)."""
    mirror = float(np.linalg.det(L)) < 0
    Lp = L @ np.diag([-1.0, 1.0]) if mirror else L
    scale = math.hypot(Lp[0, 0], Lp[1, 0])
    angle = math.degrees(math.atan2(Lp[1, 0], Lp[0, 0])) % 360.0
    return mirror, scale, angle


def place(points: np.ndarray, pose: Mapping) -> np.ndarray:
    """Sheet points (n x 2) placed by a frozen pose {origin, mirror, scale, angle_deg, dx, dy} (refit.apply's order)."""
    o = np.asarray(pose["origin"], float)
    L = mat(pose["angle_deg"], pose["scale"], pose["mirror"])
    return (np.asarray(points, float) - o) @ L.T + o + np.array([pose["dx"], pose["dy"]])


def compose(base: Mapping, adjust: Mapping, pivot: Sequence[float]) -> dict:
    """The base pose followed by the review page's adjustment, as ONE pose about the same origin.

    The page (review-page/v3/script.js `mapM`): M2 = T(c0 + (dx, dy)) . R(turn) . S(scale) . Mirror(mirror) . T(-c0),
    applied AFTER the fitter's pose M1; c0 is the fitter-placed centre of the chart's box (`page_pivot`). So the world
    point w = L1 (p - o) + o + d1 goes to A (w - c0) + c0 + dd, A = mat(turn, scale, mirror)."""
    o = np.asarray(base["origin"], float)
    L1 = mat(base["angle_deg"], base["scale"], base["mirror"])
    d1 = np.array([base["dx"], base["dy"]], float)
    A = mat(float(adjust["turn_deg"]), float(adjust["scale"]), bool(adjust["mirror"]))
    c = np.asarray(pivot, float)
    dd = np.array([float(adjust["dx_m"]), float(adjust["dy_m"])])
    L = A @ L1
    t = A @ (o + d1 - c) + c + dd - o
    mirror, scale, angle = decompose(L)
    return {"origin": [float(o[0]), float(o[1])], "mirror": mirror, "scale": round(scale, 9),
            "angle_deg": round(angle, 9), "dx": round(float(t[0]), 6), "dy": round(float(t[1]), 6)}


def pose_of_run_row(r: Mapping) -> Optional[dict]:
    """A refit.json row's final pose (refit.after.fit, else the baseline fit), or None when not placed."""
    if r.get("state") != "fitted":
        return None
    after = (r.get("refit") or {}).get("after")
    f = after["fit"] if after else r["fit"]
    origin = (r.get("refit") or {}).get("origin") or r["fit"]["origin"]
    return {"origin": [float(origin[0]), float(origin[1])], "mirror": bool(f.get("mirror", False)),
            "scale": float(f.get("scale", 1.0) or 1.0), "angle_deg": float(f["angle_deg"]),
            "dx": float(f["dx"]), "dy": float(f["dy"])}


def target_of_run_row(r: Mapping) -> str:
    after = (r.get("refit") or {}).get("after")
    return after["target"] if after else r["fit"]["wbk"]


def class_of_run_row(r: Mapping) -> str:
    after = (r.get("refit") or {}).get("after")
    return after["grade"] if after else r.get("grade", r.get("state"))


def max_shift(box: Sequence[float], a: Mapping, b: Mapping) -> float:
    """The largest distance any corner of the sheet box (minx, miny, maxx, maxy) moves between poses a and b."""
    pts = np.array([[box[0], box[1]], [box[2], box[1]], [box[2], box[3]], [box[0], box[3]]], float)
    return float(np.max(np.hypot(*(place(pts, a) - place(pts, b)).T)))


# ------------------------------------------------------------------ the review page's own data (what he saw)

def _dec(arr: Sequence[int], u: float) -> np.ndarray:
    """script.js `dec`: delta-encoded ints -> coordinates (x u)."""
    a = np.asarray(arr, float).reshape(-1, 2)
    return np.cumsum(a, axis=0) * u


class PageChart:
    """One chart's page data file (`d/<id>.json`, review-page build3.py) read the way script.js reads it."""

    def __init__(self, d: Mapping):
        self.d = d
        u = float(d["u"])
        self.shore = [_dec(a, u) for a in d.get("shore", [])]
        self.joins = [_dec(a, u) for a in d.get("joins", [])]
        self.water = [_dec(a, u) for a in d.get("water", [])]
        self.depth = [_dec(a, u) for g in d.get("depth", []) for a in g["l"]]
        lk = d.get("lake")
        self.lake_ref = np.asarray(lk["ref"], float) if lk else None
        self.lake = [_dec(a, float(lk["u"])) for a in lk["rings"]] if lk else []
        pts = [p for ring in self.shore + self.joins + self.depth for p in ring]
        if pts:
            P = np.asarray(pts)
            self.box = (P[:, 0].min(), P[:, 1].min(), P[:, 0].max(), P[:, 1].max())
        else:                                   # script.js: `if (b[0] === Infinity) b = [-1, -1, 1, 1]`
            self.box = (-1.0, -1.0, 1.0, 1.0)

    def fit_matrix(self) -> Tuple[np.ndarray, np.ndarray]:
        """script.js `fitM`: chart-relative -> lake frame, as (L, t)."""
        f = self.d["fit"]
        return mat(float(f["a"]), float(f["s"]), bool(f["m"])), np.array([float(f["tx"]), float(f["ty"])])

    def pivot_lake_frame(self) -> np.ndarray:
        """script.js `centre`: the fitter-placed centre of the chart's box, in the lake frame."""
        L, t = self.fit_matrix()
        b = self.box
        return L @ np.array([(b[0] + b[2]) / 2, (b[1] + b[3]) / 2]) + t

    def pivot_world(self) -> np.ndarray:
        return self.pivot_lake_frame() + self.lake_ref

    def world_pose(self, origin: Sequence[float]) -> dict:
        """The page's fitter pose in world coordinates about `origin` (tx = origin + dx - ref, build3.fitjson)."""
        f = self.d["fit"]
        o = np.asarray(origin, float)
        return {"origin": [float(o[0]), float(o[1])], "mirror": bool(f["m"]), "scale": float(f["s"]),
                "angle_deg": float(f["a"]), "dx": float(f["tx"]) + self.lake_ref[0] - o[0],
                "dy": float(f["ty"]) + self.lake_ref[1] - o[1]}

    def overlap(self, adjust: Optional[Mapping] = None, n: int = PAGE_RASTER) -> Optional[float]:
        """script.js `overlap`: the lake and the chart's water rasterised on an n x n grid (pixel centres, even-odd
        fill), intersection over union, with the adjustment laid on the fitter's pose about the page's pivot."""
        if not self.water or not self.lake:
            return None
        L1, t1 = self.fit_matrix()
        c0 = self.pivot_lake_frame()
        a = adjust or {"turn_deg": 0, "scale": 1, "mirror": False, "dx_m": 0, "dy_m": 0}
        A = mat(float(a["turn_deg"]), float(a["scale"]), bool(a["mirror"]))
        L = A @ L1
        t = A @ (t1 - c0) + c0 + np.array([float(a["dx_m"]), float(a["dy_m"])])
        b = self.box
        corners = np.array([[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]]]) @ L.T + t
        lake = np.vstack(self.lake)
        x0 = min(corners[:, 0].min(), lake[:, 0].min()); y0 = min(corners[:, 1].min(), lake[:, 1].min())
        x1 = max(corners[:, 0].max(), lake[:, 0].max()); y1 = max(corners[:, 1].max(), lake[:, 1].max())
        ext = max(x1 - x0, y1 - y0, 1.0)
        kk = (n - 4) / ext
        ii, jj = np.meshgrid(np.arange(n) + 0.5, np.arange(n) + 0.5)
        X = (ii.ravel() - 2) / kk + x0
        Y = (jj.ravel() - 2) / kk + y0
        in_lake = _evenodd(self.lake, X, Y)
        Q = np.linalg.solve(L, np.vstack([X - t[0], Y - t[1]]))      # lake frame -> chart-relative
        in_water = _evenodd(self.water, Q[0], Q[1])
        uni = np.count_nonzero(in_lake | in_water)
        return float(np.count_nonzero(in_lake & in_water) / uni) if uni else None


def _evenodd(rings: Iterable[np.ndarray], X: np.ndarray, Y: np.ndarray) -> np.ndarray:
    """Points inside the rings under the even-odd rule (canvas `fill(path, "evenodd")`)."""
    inside = np.zeros(X.shape, bool)
    for ring in rings:
        xs, ys = ring[:, 0], ring[:, 1]
        xa, ya = xs, ys
        xb, yb = np.roll(xs, -1), np.roll(ys, -1)
        for k in range(len(xs)):
            cond = (ya[k] > Y) != (yb[k] > Y)
            if not cond.any():
                continue
            with np.errstate(divide="ignore", invalid="ignore"):
                xi = xa[k] + (Y - ya[k]) * (xb[k] - xa[k]) / (yb[k] - ya[k])
            inside ^= cond & (X < xi)
    return inside


def read_page_chart(data_dir: Path, sheet: str) -> PageChart:
    p = Path(data_dir) / "d" / f"{sheet}.json"
    if not p.is_file():
        p = Path(data_dir) / f"{sheet}.json"
    if not p.is_file():
        raise FileNotFoundError(f"{sheet}: no review-page data file under {data_dir} (d/{sheet}.json)")
    return PageChart(json.loads(p.read_text(encoding="utf-8")))


# ------------------------------------------------------------------ the inputs

def file_sha256(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def load(path: Optional[Path] = None) -> dict:
    """The frozen placings. RAISES on a missing file or a wrong schema (AGENTS 37), never returns an empty set."""
    if path is None:
        from pipeline.common.curated import CURATED
        path = CURATED.bathymetry.placings
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"{p}: the frozen placings are missing; restore from git, or "
                                "`empty_file()` is its first committed state")
    d = json.loads(p.read_text(encoding="utf-8"))
    if d.get("schema") != SCHEMA or not isinstance(d.get("placings"), list):
        raise ValueError(f"{p}: not a {SCHEMA} file")
    return d


def load_units(path: Optional[Path] = None) -> Dict[str, dict]:
    if path is None:
        from pipeline.common.curated import CURATED
        path = CURATED.bathymetry.sheet_units
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    if d.get("schema") != UNITS_SCHEMA:
        raise ValueError(f"{path}: not a {UNITS_SCHEMA} file")
    out = {}
    for r in d["sheets"]:
        if r["sheet"] in out:
            raise ValueError(f"{path}: sheet {r['sheet']} twice")
        if r["unit"] not in ("feet", "metres"):
            raise ValueError(f"{path}: sheet {r['sheet']}: unit {r['unit']!r}")
        out[r["sheet"]] = r
    return out


def empty_file() -> dict:
    return {"_about": ("PROMOTED (T1267): the vector depth sheets ACCEPTED onto their lakes, frozen. Written ONLY by "
                       "`python -m pipeline.bathymetry.placings --freeze` (through curated_write); an accepted row is "
                       "NEVER rewritten by a rerun (a disagreeing run is reported, not applied). Accepted = the fitter "
                       "run of record's `high` / `high_stretched` placings plus every chart the owner marked `right` / "
                       "`right_adjusted` (his adjustment composed into `pose` and kept as saved in `adjust`); a chart "
                       "he marked wrong_lake / wrong_fit / unsure never. Each row: the sheet and its zip's sha256, the "
                       "lake(s) by durable item id, the full pose (origin, mirror, scale, angle_deg, dx, dy; "
                       "refit.apply's order, EPSG:3005 metres), the units with their evidence, how and when it was "
                       "accepted. Read by pipeline.bathymetry.placed_contours (T1268); nothing of a lake's depth ships "
                       "without its row here (owner 2026-11-28)."),
            "schema": SCHEMA,
            "licence": "Province of BC vector lake depth maps; the owner holds the permission (T201, 2026-11-26)",
            "placings": []}




_PHRASE = re.compile(r"\bdepths?\s+(?:are\s+)?in\s+(feet|foot|ft|metres|meters|metre|meter|m)\b", re.I)


def e00_units(zpath: Path, coverage: str) -> Tuple[Optional[str], Optional[str]]:
    """(unit, the words) as the vector file's own META / annotation says "depth(s) in ...", else (None, None)."""
    from pipeline.bathymetry import e00
    sh = [s for s in e00.read_zip_all(zpath) if s.lines.name == coverage]
    texts = [sh[0].text()] if sh else []
    texts += e00.annotation_words(zpath)
    unit = e00.units_stated(texts)
    words = next((m.group(0) for t in texts for m in _PHRASE.finditer(t)), None)
    return unit, words


def contour_values(zpath: Path, coverage: str) -> List[float]:
    from pipeline.bathymetry import e00
    sh = [s for s in e00.read_zip_all(zpath) if s.lines.name == coverage]
    if len(sh) != 1:
        raise ValueError(f"{zpath}: {len(sh)} coverages named {coverage}")
    return sorted({abs(float(c)) for c, _f, _p in sh[0].contours() if c not in (None, 0)})


def sheet_box(zpath: Path, coverage: str) -> Tuple[float, float, float, float]:
    from pipeline.bathymetry import e00
    sh = [s for s in e00.read_zip_all(zpath) if s.lines.name == coverage][0]
    P = np.array([p for _c, _f, pts in sh.contours() for p in pts], float)
    return (float(P[:, 0].min()), float(P[:, 1].min()), float(P[:, 0].max()), float(P[:, 1].max()))


def lake_items(registry_items: Iterable[Mapping]) -> Dict[str, List[str]]:
    """`wbk:<key>` -> the registry item ids that name it (its own lake item, or the item that took it in)."""
    out: Dict[str, List[str]] = defaultdict(list)
    for it in registry_items:
        for ref in it.get("ref_ids") or []:
            if ref.startswith("wbk:"):
                out[ref].append(it["id"])
    return {k: sorted(set(v)) for k, v in out.items()}


# ------------------------------------------------------------------ the freeze

class Page:
    """One fitter run the review page showed, until `until` (ISO; None = still showing)."""

    def __init__(self, label: str, data_dir: Path, refit: Path, until: Optional[str] = None):
        self.label, self.data_dir, self.refit, self.until = label, Path(data_dir), Path(refit), until
        self.rows = json.loads(self.refit.read_text(encoding="utf-8"))["rows"]
        self.sha256 = file_sha256(self.refit)

    @staticmethod
    def parse(spec: str) -> "Page":
        parts = spec.split(":")
        if len(parts) < 3:
            raise SystemExit(f"--page {spec}: LABEL:DATA_DIR:REFIT_JSON[:UNTIL_ISO]")
        label, data, refit = parts[0], parts[1], parts[2]
        until = ":".join(parts[3:]) or None
        return Page(label, Path(data), Path(refit), until)


def page_for(pages: Sequence[Page], saved_at: Optional[str]) -> Optional[Page]:
    """The page a mark saved at `saved_at` was made on: the first whose `until` is after it. None when not placeable."""
    if not saved_at or not pages:
        return None
    try:
        t = dt.datetime.fromisoformat(saved_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    for p in pages:
        if p.until is None:
            return p
        u = dt.datetime.fromisoformat(p.until.replace("Z", "+00:00"))
        if t < u:
            return p
    return None


def _rows_by_sheet(rows: Sequence[Mapping]) -> Dict[str, Mapping]:
    """sheet file number -> its one placeable row (a duplicate coverage of the same zip is never a sheet)."""
    by: Dict[str, List[Mapping]] = defaultdict(list)
    for r in rows:
        if r.get("state") == "duplicate_coverage":
            continue
        by[r["zip"][:8]].append(r)
    out = {}
    for k, v in by.items():
        if len(v) != 1:
            raise ValueError(f"sheet {k}: {len(v)} rows in one run; a sheet is one row")
        out[k] = v[0]
    return out


def freeze(frozen: dict, *, run_rows: Sequence[Mapping], run_label: str, run_sha256: str,
           marks: Mapping[str, Mapping], pages: Sequence[Page], units: Mapping[str, dict],
           sheets_meta: Mapping[str, Mapping], items: Mapping[str, List[str]], titles: Mapping[str, List[str]],
           zip_of, today: str, by: str) -> dict:
    """Append every newly accepted sheet to `frozen` (in place). Returns the report: added, held out by reason, the
    run-of-record disagreements and the rerun disagreements. Never rewrites a row already in `frozen`."""
    run = _rows_by_sheet(run_rows)
    have = {r["sheet"]: r for r in frozen["placings"]}
    held: Dict[str, List[dict]] = defaultdict(list)
    run_disagrees, rerun_disagrees, cands = [], [], []

    def hold(reason, sheet, **kw):
        held[reason].append(dict(sheet=sheet, **kw))

    for sheet in sorted(set(run) | set(marks)):
        r = run.get(sheet)
        m = marks.get(sheet) or {}
        verdict = m.get("verdict")
        title = (titles.get(r["zip"]) if r else None) or [m.get("chart_title")]
        if verdict in NEVER_MARKS:
            hold(f"owner_marked_{verdict}", sheet, title=title, note=m.get("note", ""))
            continue
        if verdict and verdict not in ACCEPT_MARKS:
            hold("mark_verdict_unknown", sheet, verdict=verdict)
            continue
        conf = r.get("confidence") if r else None
        if not verdict and conf not in ACCEPT_CLASSES:
            if r is not None:
                held["not_accepted_review_unmarked" if r.get("state") == "fitted" else "not_placed"].append(
                    {"sheet": sheet, "confidence": conf, "state": r.get("state")})
            continue
        # --- the base pose: the run of record's, or (a mark) the page's he saw
        adjust_rec = None
        if verdict:
            page = page_for(pages, m.get("saved_at"))
            if page is None:
                hold("mark_base_unknown", sheet, saved_at=m.get("saved_at"))
                continue
            prow = _rows_by_sheet(page.rows).get(sheet)
            if prow is None or prow.get("state") != "fitted":
                hold("mark_on_unplaced_sheet", sheet, page=page.label)
                continue
            base_row, base_label, base_sha = prow, page.label, page.sha256
            base = pose_of_run_row(prow)
            target = target_of_run_row(prow)
            if m.get("lake_after") and m["lake_after"] != target:
                hold("mark_lake_differs", sheet, mark=m["lake_after"], page=target)
                continue
            pc = read_page_chart(page.data_dir, sheet)
            pw = pc.world_pose(base["origin"])
            if abs(pw["dx"] - base["dx"]) > 0.05 or abs(pw["dy"] - base["dy"]) > 0.05 or \
                    abs(pw["angle_deg"] - base["angle_deg"]) > 1e-3:
                hold("page_data_not_its_run", sheet, page=page.label)
                continue
            pose = dict(base)
            a = m.get("adjust") if m.get("adjusted") or verdict == "right_adjusted" else None
            if verdict == "right_adjusted" and not a:
                hold("adjusted_mark_without_adjust", sheet)
                continue
            if a:
                if a.get("on_lake") and a["on_lake"] != target:
                    hold("adjusted_onto_another_lake", sheet, on_lake=a["on_lake"], placed=target)
                    continue
                ov = pc.overlap(a)
                saved = a.get("overlap")
                if saved is None or ov is None or abs(ov - float(saved)) > OVERLAP_TOLERANCE:
                    hold("adjust_not_reproduced", sheet, saved=saved, recomputed=ov)
                    continue
                pivot = pc.pivot_world()
                pose = compose(base, a, pivot)
                adjust_rec = {"as_saved": dict(a), "relative_to": base_label, "base_pose": base,
                              "pivot": [round(float(pivot[0]), 3), round(float(pivot[1]), 3)],
                              "pivot_is": "the page's fitter-placed centre of the chart's box (script.js centre())",
                              "overlap_recomputed": round(ov, 4),
                              "overlap_fitter": round(pc.overlap(None) or 0.0, 4)}
            accepted_as = verdict
        else:
            base_row, base_label, base_sha = r, run_label, run_sha256
            base = pose_of_run_row(r)
            target = target_of_run_row(r)
            pose = dict(base)
            accepted_as = conf
        zname, cov = base_row["zip"], base_row["coverage"]
        zpath, zsha = zip_of(zname)
        # --- units
        unit, words = e00_units(zpath, cov)
        if unit == "both":
            hold("units_both_stated", sheet, words=words)
            continue
        if unit:
            ev = {"from": "vector file", "words": words}
        else:
            row = units.get(sheet)
            if UNITS_UNSTATED == "hold":
                hold("units_unstated", sheet)
                continue
            if UNITS_UNSTATED == "feet":
                unit, ev = "feet", {"from": "policy UNITS_UNSTATED=feet (not read)"}
            elif row is None:
                hold("units_not_read", sheet)
                continue
            else:
                unit = row["unit"]
                ev = {"from": "printed chart", "words": row["words"], "where": row["where"], "page": row["page"],
                      "pdf": row["pdf"]}
        values = contour_values(zpath, cov)
        bad = [v for v in values if v in NO_DATA_DEPTHS]
        if bad:
            hold("depth_code_unproven", sheet, codes=bad, levels=values)
            continue
        lakes = target.split("+")
        lake_rows = []
        ok = True
        for w in lakes:
            ids = items.get(w, [])
            if len(ids) != 1:
                hold("no_single_registry_item", sheet, lake=w, items=ids)
                ok = False
                break
            lake_rows.append({"wbk": w, "item": ids[0]})
        if not ok:
            continue
        meta = sheets_meta.get(sheet) or {}
        cand = {
            "sheet": sheet, "zip": zname, "zip_sha256": zsha, "coverage": cov,
            "title": (titles.get(zname) or [meta.get("map_title")])[0],
            "lakes": lake_rows,
            "pose": pose,
            "units": unit, "units_evidence": ev,
            "accepted_as": accepted_as,
            "fitter_run": {"label": base_label, "sha256": base_sha, "class": class_of_run_row(base_row),
                           "confidence": base_row.get("confidence")},
            "adjust": adjust_rec,
            "mark": ({k: m.get(k) for k in ("verdict", "saved_at", "note", "chart_title", "lake_after")}
                     if verdict else None),
            "draft_date": (meta.get("draft_date") or "").rstrip("Z") or None,
            "accepted_on": today, "accepted_by": by,
        }
        # the run of record's own pose for a marked sheet: reported, never applied
        if verdict and r is not None and r.get("state") == "fitted":
            box = sheet_box(zpath, cov)
            rp = pose_of_run_row(r)
            shift = max_shift(box, pose, rp)
            if shift > POSE_AGREE_M or target_of_run_row(r) != target:
                run_disagrees.append({"sheet": sheet, "run": run_label, "max_shift_m": round(shift, 1),
                                      "run_lake": target_of_run_row(r), "frozen_lake": target,
                                      "run_confidence": r.get("confidence")})
        cands.append(cand)

    # --- D9: one survey per lake
    if SURVEYS_PER_LAKE == "newest":
        by_lake: Dict[str, List[dict]] = defaultdict(list)
        for c in cands + list(have.values()):
            for lk in c["lakes"]:
                by_lake[lk["wbk"]].append(c)
        drop = set()
        for w, cs in sorted(by_lake.items()):
            if len({c["sheet"] for c in cs}) < 2:
                continue
            keep = max(cs, key=lambda c: (c.get("draft_date") or "", c["sheet"]))
            for c in cs:
                if c["sheet"] != keep["sheet"] and c["sheet"] not in have:
                    drop.add(c["sheet"])
                    hold("older_survey", c["sheet"], lake=w, draft_date=c.get("draft_date"),
                         kept=keep["sheet"], kept_draft_date=keep.get("draft_date"))
        cands = [c for c in cands if c["sheet"] not in drop]

    added = []
    for c in cands:
        if c["sheet"] in have:
            old = have[c["sheet"]]
            diff = {k: (old.get(k), c.get(k)) for k in ("pose", "lakes", "units", "accepted_as", "zip_sha256")
                    if old.get(k) != c.get(k)}
            if diff:
                rerun_disagrees.append({"sheet": c["sheet"], "differs": sorted(diff)})
            continue
        frozen["placings"].append(c)
        added.append(c["sheet"])
    frozen["placings"].sort(key=lambda r: r["sheet"])
    return {"added": added, "kept": sorted(have), "held_out": {k: sorted(v, key=lambda x: x["sheet"])
                                                                 for k, v in sorted(held.items())},
            "run_disagrees": run_disagrees, "rerun_disagrees": rerun_disagrees,
            "counts": {"rows": len(frozen["placings"]), "added": len(added),
                       "held_out": {k: len(v) for k, v in sorted(held.items())},
                       "accepted_as": dict(Counter(r["accepted_as"] for r in frozen["placings"])),
                       "units": dict(Counter(r["units"] for r in frozen["placings"])),
                       "lakes": len({lk["item"] for r in frozen["placings"] for lk in r["lakes"]})},
            "policy": {"ACCEPT_CLASSES": ACCEPT_CLASSES, "ACCEPT_MARKS": ACCEPT_MARKS, "NEVER_MARKS": NEVER_MARKS,
                       "UNITS_UNSTATED": UNITS_UNSTATED, "NO_DATA_DEPTHS": NO_DATA_DEPTHS,
                       "SURVEYS_PER_LAKE": SURVEYS_PER_LAKE, "OVERLAP_TOLERANCE": OVERLAP_TOLERANCE,
                       "POSE_AGREE_M": POSE_AGREE_M}}


def check(frozen: dict) -> List[str]:
    """Every row's zip proved against the committed list and its sha256 as frozen; the rows whole. [] = fine."""
    from pipeline.bathymetry import vectors
    bad = []
    seen = set()
    for r in frozen["placings"]:
        if r["sheet"] in seen:
            bad.append(f"{r['sheet']}: twice")
        seen.add(r["sheet"])
        try:
            if vectors.zip_sha256(r["zip"]) != r["zip_sha256"]:
                bad.append(f"{r['sheet']}: {r['zip']} sha256 differs from the frozen row")
        except vectors.VectorSourceError as e:
            bad.append(f"{r['sheet']}: {e}")
        if r["units"] not in ("feet", "metres"):
            bad.append(f"{r['sheet']}: units {r['units']!r}")
        for k in ("origin", "mirror", "scale", "angle_deg", "dx", "dy"):
            if k not in r["pose"]:
                bad.append(f"{r['sheet']}: pose lacks {k}")
        if not r["lakes"] or any(not lk.get("item") for lk in r["lakes"]):
            bad.append(f"{r['sheet']}: no lake item")
    return bad


def _dump(d: dict) -> str:
    return json.dumps(d, indent=1, ensure_ascii=False) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="the frozen accepted depth-sheet placings (T1267)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--freeze", action="store_true", help="append the newly accepted sheets")
    g.add_argument("--check", action="store_true", help="prove every row's zip and shape")
    ap.add_argument("--run", type=Path, help="the run of record's refit.json (default GENERATED.bathymetry/refit.json)")
    ap.add_argument("--run-label", help="the run of record's name (e.g. v5)")
    ap.add_argument("--marks", type=Path, help="the owner's marks export (marks-<date>.json)")
    ap.add_argument("--page", action="append", default=[],
                    help="LABEL:PAGE_DATA_DIR:REFIT_JSON[:UNTIL_ISO], in the order the page showed them")
    ap.add_argument("--by", help="who accepts (the owner's rule, recorded on every new row)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--today", default=None, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    from pipeline.common.curated import CURATED, GENERATED, SOURCE
    from pipeline.common import curated_write
    path = Path(CURATED.bathymetry.placings)
    frozen = load(path)
    if a.check:
        bad = check(frozen)
        for b in bad:
            print(b)
        print(f"{len(frozen['placings'])} rows, {len(bad)} problems")
        return 1 if bad else 0
    if not a.run_label or not a.by:
        raise SystemExit("--freeze needs --run-label and --by")
    run_path = a.run or Path(GENERATED.bathymetry) / "refit.json"
    if not run_path.is_file():
        raise SystemExit(f"{run_path}: no run of record; run `python -m pipeline.bathymetry.refit_all` (heavy.sh) first")
    run_doc = json.loads(run_path.read_text(encoding="utf-8"))
    marks = json.loads(a.marks.read_text(encoding="utf-8"))["marks"] if a.marks else {}
    pages = [Page.parse(s) for s in a.page]
    if marks and not pages:
        raise SystemExit("--marks needs --page: a mark is relative to the placing the page showed")
    from pipeline.bathymetry import vectors
    sheets_meta = {s["map_image_filename"][:8]: s
                   for s in json.loads((SOURCE / "bc_bathymetry_sheets.json").read_text(encoding="utf-8"))}
    reg = json.loads(GENERATED.registry().read_text(encoding="utf-8"))["items"]
    report = freeze(frozen, run_rows=run_doc["rows"], run_label=a.run_label, run_sha256=file_sha256(run_path),
                    marks=marks, pages=pages, units=load_units(), sheets_meta=sheets_meta, items=lake_items(reg),
                    titles=run_doc.get("titles", {}),
                    zip_of=lambda n: (vectors.zip_path(n), vectors.zip_sha256(n)),
                    today=a.today or dt.date.today().isoformat(), by=a.by)
    report["run"] = {"label": a.run_label, "path": str(run_path), "sha256": file_sha256(run_path)}
    report["marks"] = str(a.marks) if a.marks else None
    report["pages"] = [{"label": p.label, "refit": str(p.refit), "sha256": p.sha256, "until": p.until} for p in pages]
    out = GENERATED.mkdir("bathymetry") / "placings_report.json"
    out.write_text(_dump(report), encoding="utf-8")
    print(json.dumps(report["counts"], indent=1))
    print(f"report: {out}")
    if a.dry_run:
        print("dry run: the frozen file is unchanged")
        return 0
    curated_write.write(path, _dump(frozen), tool="pipeline.bathymetry.placings", by=a.by,
                        source=f"--freeze {a.run_label}: +{len(report['added'])}")
    print(f"wrote {path} ({len(frozen['placings'])} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
