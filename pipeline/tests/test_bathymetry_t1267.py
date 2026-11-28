"""T1267: the vector zips as a hash-checked source, and the frozen accepted placings.

What must never happen: a placing drawn from a zip other than the one it was frozen against; a chart the owner marked
wrong shipped because its class was high; an adjustment laid over a pose the owner never saw; a rerun rewriting an
accepted row; a sheet with no stated depth unit shipped as metres. Synthetic inputs, plus the committed lists.
"""
from __future__ import annotations

import hashlib
import json
import math
import zipfile

import numpy as np
import pytest

from pipeline.bathymetry import placings as P
from pipeline.bathymetry import vectors as V
from pipeline.common.curated import SOURCE
from pipeline.tests import under_test
from pipeline.tests.test_bathymetry_t634 import _f, _info


# ---------------------------------------------------------------------------------------------- the zips as a source

def _vec(tmp_path, names=("a.zip", "b.zip")):
    d = tmp_path / "vec"
    d.mkdir()
    zips = {}
    for n in names:
        (d / n).write_bytes(n.encode() * 10)
        zips[n] = {"sha256": hashlib.sha256((d / n).read_bytes()).hexdigest(), "bytes": 30}
    h = tmp_path / "list.json"
    h.write_text(json.dumps({"schema": V.SCHEMA, "zips": zips}))
    V._checked.cache_clear()
    return d, h


def test_a_listed_zip_with_its_bytes_is_read(tmp_path):
    d, h = _vec(tmp_path)
    assert V.zip_path("a.zip", folder=d, hashes=h) == d / "a.zip"


def test_a_missing_folder_raises_naming_the_fetch_command(tmp_path):
    d, h = _vec(tmp_path)
    with pytest.raises(V.VectorSourceError, match="fetch_vectors"):
        V.zip_path("a.zip", folder=tmp_path / "nowhere", hashes=h)


def test_a_differing_zip_raises_naming_the_file(tmp_path):
    d, h = _vec(tmp_path)
    (d / "b.zip").write_bytes(b"changed")
    with pytest.raises(V.VectorSourceError, match=r"b\.zip: sha256 .* differs"):
        V.zip_path("b.zip", folder=d, hashes=h)


def test_an_unlisted_or_missing_zip_raises(tmp_path):
    d, h = _vec(tmp_path)
    (d / "c.zip").write_bytes(b"x")
    with pytest.raises(V.VectorSourceError, match="not in"):
        V.zip_path("c.zip", folder=d, hashes=h)
    (d / "a.zip").unlink()
    V._checked.cache_clear()
    with pytest.raises(V.VectorSourceError, match="missing"):
        V.zip_path("a.zip", folder=d, hashes=h)
    got = V.check(d, h)
    assert got["missing"] == ["a.zip"] and got["unlisted"] == ["c.zip"] and got["ok"] == ["b.zip"]


def test_the_committed_hash_list_names_510_zips_for_512_sheets():
    d = json.loads(SOURCE.bathymetry_vectors_sha256.read_text())
    assert d["schema"] == V.SCHEMA and len(d["zips"]) == 510
    assert all(len(r["sha256"]) == 64 and r["bytes"] > 0 for r in d["zips"].values())
    assert "duplicate_coverage" in d["_about"]


# ---------------------------------------------------------------------------------------------- poses and adjustments

def _rand_pose(rng, mirror):
    return {"origin": [float(rng.uniform(0, 900)), float(rng.uniform(0, 900))], "mirror": mirror,
            "scale": float(rng.uniform(0.9, 1.1)), "angle_deg": float(rng.uniform(0, 360)),
            "dx": float(rng.uniform(1e6, 1.1e6)), "dy": float(rng.uniform(4e5, 5e5))}


@pytest.mark.parametrize("base_mirror", [False, True])
@pytest.mark.parametrize("adj_mirror", [False, True])
def test_one_composed_pose_is_the_page_s_two_steps(base_mirror, adj_mirror):
    """The page lays the adjustment on the fitter's pose about a pivot (mirror first, then turn and scale, then the
    move east / north). `compose` folds both into one pose `refit.apply` order reproduces exactly."""
    rng = np.random.default_rng(7)
    base = _rand_pose(rng, base_mirror)
    adj = {"turn_deg": 17.5, "scale": 0.84, "mirror": adj_mirror, "dx_m": 40, "dy_m": -50}
    pts = rng.uniform(0, 900, size=(50, 2))
    w = P.place(pts, base)
    pivot = w.mean(axis=0) + [13.0, -7.0]
    A = P.mat(17.5, 0.84, adj_mirror)
    two_step = (w - pivot) @ A.T + pivot + [40, -50]
    one = P.place(pts, P.compose(base, adj, pivot))
    assert np.allclose(one, two_step, atol=1e-6)


def test_the_identity_adjustment_changes_nothing():
    base = {"origin": [10.0, 20.0], "mirror": True, "scale": 1.03, "angle_deg": 359.5, "dx": 1e6, "dy": 5e5}
    got = P.compose(base, {"turn_deg": 0, "scale": 1, "mirror": False, "dx_m": 0, "dy_m": 0}, [3.0, 4.0])
    pts = np.array([[0, 0], [100, 50]])
    assert np.allclose(P.place(pts, got), P.place(pts, base), atol=1e-6)


def _enc(coords):
    out, px, py = [], 0, 0
    for x, y in coords:
        out += [x - px, y - py]
        px, py = x, y
    return out


def _page(fit=None):
    """A page data file: the chart's water a 100 m square (sheet frame, relative to its origin), the lake the same
    square in the lake frame; u = 1."""
    sq = [(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)]
    return {"id": "00000001", "u": 1.0, "origin": [500.0, 500.0], "shore": [_enc(sq)], "joins": [],
            "water": [_enc(sq)], "depth": [{"d": 2, "l": [_enc([(20, 20), (80, 20)])]}], "other": [],
            "lake": {"ref": [1_000_000, 500_000], "u": 1.0, "rings": [_enc(sq)]},
            "fit": fit or {"a": 0.0, "s": 1.0, "m": 0, "tx": 0.0, "ty": 0.0}}


def test_the_page_overlap_is_reproduced_on_a_synthetic_case():
    pc = P.PageChart(_page())
    assert pc.overlap(None) == pytest.approx(1.0, abs=0.02)
    # moved 50 m east: intersection 50 x 100 over union 150 x 100
    assert pc.overlap({"turn_deg": 0, "scale": 1, "mirror": False, "dx_m": 50, "dy_m": 0}) == pytest.approx(1 / 3, abs=0.02)
    # scaled 0.5 about the box centre (50, 50): a 50 m square inside the lake
    assert pc.overlap({"turn_deg": 0, "scale": 0.5, "mirror": False, "dx_m": 0, "dy_m": 0}) == pytest.approx(0.25, abs=0.02)
    # turned 45 degrees about the centre: the square and its diamond meet in an octagon of 2 (sqrt2 - 1) squares
    octagon = 2 * (math.sqrt(2) - 1)
    ov = pc.overlap({"turn_deg": 45, "scale": 1, "mirror": False, "dx_m": 0, "dy_m": 0})
    assert ov == pytest.approx(octagon / (2 - octagon), abs=0.02)


def test_the_pivot_is_the_fitter_placed_box_centre_not_the_origin():
    pc = P.PageChart(_page({"a": 90.0, "s": 1.0, "m": 0, "tx": 10.0, "ty": 20.0}))
    # box centre (50, 50) turned 90 deg -> (-50, 50), + (10, 20), + the lake ref
    assert np.allclose(pc.pivot_world(), [1_000_000 - 40, 500_000 + 70])


def test_the_composed_world_pose_draws_where_the_page_draws():
    fit = {"a": 30.0, "s": 1.0, "m": 0, "tx": 12.5, "ty": -8.0}
    pc = P.PageChart(_page(fit))
    origin = [500.0, 500.0]                                    # page coordinates are sheet - origin
    base = pc.world_pose(origin)
    adj = {"turn_deg": 2, "scale": 0.84, "mirror": False, "dx_m": 40, "dy_m": 50}
    pose = P.compose(base, adj, pc.pivot_world())
    rel = np.array([[0, 0], [100, 0], [37, 61]], float)
    # the page: lake frame = M2 . M1 (rel); world = lake frame + ref
    L1, t1 = pc.fit_matrix()
    c0 = pc.pivot_lake_frame()
    A = P.mat(2, 0.84, False)
    page = ((rel @ L1.T + t1) - c0) @ A.T + c0 + [40, 50] + pc.lake_ref
    assert np.allclose(P.place(rel + origin, pose), page, atol=1e-6)


def test_mutation_an_adjust_about_the_origin_misses_the_saved_overlap():
    """The guard that proves the maths: the same adjustment about the wrong pivot lands elsewhere, and the overlap
    the page saved is not reproduced."""
    pc = P.PageChart(_page())
    adj = {"turn_deg": 90, "scale": 1, "mirror": False, "dx_m": 0, "dy_m": 0}
    right = pc.overlap(adj)
    box = pc.box
    pc.box = (0.0, 0.0, 0.0, 0.0)                              # pivot at the sheet origin instead of the box centre
    wrong = pc.overlap(adj)
    pc.box = box
    assert abs(right - wrong) > P.OVERLAP_TOLERANCE


# ---------------------------------------------------------------------------------------------- the freeze

def _e00(values, words):
    """One line coverage: a 100 m square shore and one contour per value, its META carrying `words`."""
    arcs = [(1, [(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)])]
    for k, v in enumerate(values):
        a = 10 + 5 * k
        arcs.append((k + 2, [(a, a), (100 - a, a), (100 - a, 100 - a), (a, 100 - a), (a, a)]))
    L = ["EXP  0 /X/TEST.E00", "ARC  2"]
    for aid, pts in arcs:
        L.append(f"{aid:10d}{aid:10d}{1:10d}{1:10d}{1:10d}{2:10d}{len(pts):10d}")
        for i in range(0, len(pts), 2):
            L.append("".join(_f(c) for p in pts[i:i + 2] for c in p))
    L.append(f"{-1:10d}{0:10d}{0:10d}{0:10d}{0:10d}{0:10d}{0:10d}")
    L.append("IFO  2")
    rows = [(str(1), _f(400.0), "GA27110000", _f(0.0))]
    rows += [(str(k + 2), _f(100.0), "HA06200000", _f(-v)) for k, v in enumerate(values)]
    L += _info("TEST.AAT", [("FNODE#", 4, 50), ("LENGTH", 4, 60), ("FCODE", 10, 20), ("CONTOUR", 10, 40)], rows)
    L += _info("TEST.META", [("KEY", 16, 20), ("VALUE", 100, 20)], [("DESCRIPTION", words)])
    L += ["EOI", "EOS"]
    return "\n".join(L)


def _zip(d, name, values=(2.0, 4.0), words="lake contours, depths in metres"):
    p = d / name
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("test.e00", _e00(values, words))
    return p


def _row(sheet, conf, pose_dx=1e6, lake="wbk:1", state="fitted", refit=True):
    fit = {"angle_deg": 10.0, "dx": pose_dx, "dy": 5e5, "origin": [50.0, 50.0], "wbk": lake}
    r = {"zip": f"{sheet}.zip", "coverage": "test.e00", "state": state, "confidence": conf, "fit": fit,
         "grade": "strict", "units": "metres"}
    if refit:
        r["refit"] = {"origin": [50.0, 50.0], "after": {"fit": dict(fit, mirror=False, scale=1.0), "target": lake,
                                                         "grade": "strict"}}
    return r


class _Env:
    def __init__(self, tmp_path):
        self.dir = tmp_path / "z"
        self.dir.mkdir()
        self.tmp = tmp_path

    def zip_of(self, name):
        p = self.dir / name
        return p, hashlib.sha256(p.read_bytes()).hexdigest()


def _freeze(env, run_rows, frozen=None, marks=None, pages=(), units=None, items=None, meta=None):
    frozen = frozen if frozen is not None else P.empty_file()
    rep = P.freeze(frozen, run_rows=run_rows, run_label="v5", run_sha256="r5", marks=marks or {}, pages=list(pages),
                   units=units or {}, sheets_meta=meta or {}, items=items or {"wbk:1": ["wbk:1"], "wbk:2": ["wbk:2"]},
                   titles={}, zip_of=env.zip_of, today="2026-11-28", by="test",
                   marks_exported_at="2026-11-28 01:24 MST")
    return frozen, rep


def test_high_and_high_stretched_ship_review_does_not(tmp_path):
    env = _Env(tmp_path)
    for s in ("00000001", "00000002", "00000003"):
        _zip(env.dir, f"{s}.zip")
    rows = [_row("00000001", "high"), _row("00000002", "high_stretched", lake="wbk:2"),
            _row("00000003", "review", lake="wbk:2")]
    frozen, rep = _freeze(env, rows)
    assert [r["sheet"] for r in frozen["placings"]] == ["00000001", "00000002"]
    assert rep["held_out"]["not_accepted_review_unmarked"][0]["sheet"] == "00000003"
    r = frozen["placings"][0]
    assert r["accepted_as"] == "high" and r["lakes"] == [{"wbk": "wbk:1", "item": "wbk:1"}]
    assert r["pose"] == {"origin": [50.0, 50.0], "mirror": False, "scale": 1.0, "angle_deg": 10.0, "dx": 1e6, "dy": 5e5}
    assert r["zip_sha256"] == env.zip_of("00000001.zip")[1] and r["units"] == "metres"
    assert r["units_evidence"] == {"from": "vector file", "words": "depths in metres"}


@pytest.mark.parametrize("verdict", P.NEVER_MARKS)
def test_a_chart_marked_wrong_never_ships_even_when_high(tmp_path, verdict):
    env = _Env(tmp_path)
    _zip(env.dir, "00000001.zip")
    frozen, rep = _freeze(env, [_row("00000001", "high")], marks={"00000001": {"verdict": verdict}})
    assert frozen["placings"] == [] and rep["held_out"][f"owner_marked_{verdict}"][0]["sheet"] == "00000001"


def _write_page(env, sheet, dx_world, fit_a=10.0):
    """A page whose data file shows `sheet` at the pose with shift dx_world (origin 50, 50; ref 1e6, 5e5)."""
    data = env.tmp / "page"
    (data / "d").mkdir(parents=True, exist_ok=True)
    page = _page({"a": fit_a, "s": 1.0, "m": 0, "tx": 50.0 + dx_world - 1_000_000, "ty": 50.0 + 5e5 - 500_000})
    (data / "d" / f"{sheet}.json").write_text(json.dumps(page))
    return data


def _page_run(env, rows):
    p = env.tmp / "v2.json"
    p.write_text(json.dumps({"rows": rows}))
    return p


def test_a_right_mark_takes_the_pose_he_saw_and_the_run_s_disagreement_is_only_reported(tmp_path):
    env = _Env(tmp_path)
    _zip(env.dir, "00000001.zip")
    v2 = [_row("00000001", "review", pose_dx=1_000_000.0)]
    v5 = [_row("00000001", "review", pose_dx=1_000_300.0)]                # v5 moved it 300 m: not what he saw
    page = P.Page("v2", _write_page(env, "00000001", 1_000_000.0), _page_run(env, v2), "2026-11-28T06:01:00Z", "2026-11-28T08:30:00Z", True)
    marks = {"00000001": {"verdict": "right", "saved_at": "2026-11-28T07:00:00Z", "lake_after": "wbk:1"}}
    frozen, rep = _freeze(env, v5, marks=marks, pages=[page])
    r = frozen["placings"][0]
    assert r["accepted_as"] == "right" and r["pose"]["dx"] == 1_000_000.0 and r["fitter_run"]["label"] == "v2"
    assert rep["run_disagrees"][0]["sheet"] == "00000001" and rep["run_disagrees"][0]["max_shift_m"] == 300.0


def test_an_adjusted_mark_is_composed_on_its_own_page_s_pose_never_on_the_run_s(tmp_path):
    env = _Env(tmp_path)
    _zip(env.dir, "00000001.zip")
    v2 = [_row("00000001", "review", pose_dx=1_000_000.0, refit=False)]
    v5 = [_row("00000001", "review", pose_dx=1_000_300.0)]
    data = _write_page(env, "00000001", 1_000_000.0, fit_a=10.0)
    pc = P.read_page_chart(data, "00000001")
    adj = {"turn_deg": 2, "scale": 0.84, "mirror": False, "dx_m": 40, "dy_m": 50, "on_lake": "wbk:1"}
    adj["overlap"] = round(pc.overlap(adj), 3)
    page = P.Page("v2", data, _page_run(env, v2), "2026-11-28T06:01:00Z", "2026-11-28T08:30:00Z", True)
    marks = {"00000001": {"verdict": "right_adjusted", "adjusted": True, "adjust": adj,
                          "saved_at": "2026-11-28T08:21:54Z", "lake_after": "wbk:1"}}
    frozen, rep = _freeze(env, v5, marks=marks, pages=[page])
    r = frozen["placings"][0]
    base = P.pose_of_run_row(v2[0])
    assert r["adjust"]["relative_to"] == "v2" and r["adjust"]["base_pose"] == base
    assert r["adjust"]["as_saved"] == adj
    assert r["pose"] == P.compose(base, adj, pc.pivot_world())
    # never the v5 pose plus his adjustment
    assert r["pose"] != P.compose(P.pose_of_run_row(v5[0]), adj, pc.pivot_world())


def test_an_adjustment_whose_saved_overlap_is_not_reproduced_is_refused(tmp_path):
    env = _Env(tmp_path)
    _zip(env.dir, "00000001.zip")
    v2 = [_row("00000001", "review", refit=False)]
    data = _write_page(env, "00000001", 1e6)
    adj = {"turn_deg": 2, "scale": 0.84, "mirror": False, "dx_m": 40, "dy_m": 50, "on_lake": "wbk:1", "overlap": 0.99}
    marks = {"00000001": {"verdict": "right_adjusted", "adjusted": True, "adjust": adj, "saved_at": "2026-11-28T08:00Z"}}
    frozen, rep = _freeze(env, v2, marks=marks, pages=[P.Page("v2", data, _page_run(env, v2), "2026-11-28T06:01:00Z", "2026-11-28T08:30:00Z", True)])
    assert frozen["placings"] == [] and rep["held_out"]["adjust_not_reproduced"][0]["saved"] == 0.99


def test_a_mark_outside_every_page_window_is_refused_naming_it(tmp_path):
    env = _Env(tmp_path)
    _zip(env.dir, "00000001.zip")
    v2 = [_row("00000001", "review", refit=False)]
    page = P.Page("v2", _write_page(env, "00000001", 1e6), _page_run(env, v2), "2026-11-28T06:01:00Z",
                  "2026-11-28T09:00:00Z")
    marks = {"00000001": {"verdict": "right", "saved_at": "2026-11-28T10:00:00Z"}}
    frozen, rep = _freeze(env, v2, marks=marks, pages=[page])
    assert frozen["placings"] == []
    assert rep["held_out"]["mark_outside_page_windows"][0]["saved_at"] == "2026-11-28T10:00:00Z"
    assert P.page_for([page], "2026-11-28T08:59:59Z") is page
    assert P.page_for([page], "2026-11-28T06:00:59Z") is None and P.page_for([page], None) is None


def test_a_page_still_showing_must_cover_the_marks_export(tmp_path):
    env = _Env(tmp_path)
    v2 = [_row("00000001", "review", refit=False)]
    page = P.Page("v2", _write_page(env, "00000001", 1e6), _page_run(env, v2), "2026-11-28T06:01:00Z",
                  "2026-11-28 01:24 MST", True)
    P.check_pages([page], "2026-11-28 01:24 MST")
    with pytest.raises(ValueError, match="exported later"):
        P.check_pages([page], "2026-11-28 03:00 MST")
    with pytest.raises(ValueError, match="must say when"):
        P.check_pages([page], None)
    with pytest.raises(SystemExit, match="every page states its window"):
        P.Page.parse("v2,d,r")
    assert P.parse_time("2026-11-28 01:24 MST") == P.parse_time("2026-11-28T08:24:00Z")


def test_the_window_is_read_from_the_export_when_it_states_one(tmp_path):
    env = _Env(tmp_path)
    data = _write_page(env, "00000001", 1e6)
    refit = _page_run(env, [_row("00000001", "review", refit=False)])
    export = {"exported_at": "2026-11-28 03:10 MST",
              "poses_shown": [{"run": "v2", "from": "2026-11-28T06:01:00Z", "until": "2026-11-28T10:00:00Z"},
                              {"run": "v5", "from": "2026-11-28T10:00:00Z", "still_showing_at": "2026-11-28 03:10 MST"}]}
    v2 = P.page_from_spec(f"v2,{data},{refit}", export)
    v5 = P.page_from_spec(f"v5,{data},{refit}", export)
    assert P.page_for([v2, v5], "2026-11-28T09:59:59Z") is v2 and P.page_for([v2, v5], "2026-11-28T10:00:00Z") is v5
    with pytest.raises(SystemExit, match="no single window"):
        P.page_from_spec(f"v3,{data},{refit}", export)


def test_a_wrong_mark_after_the_freeze_withdraws_the_row_and_it_never_ships(tmp_path):
    env = _Env(tmp_path)
    _zip(env.dir, "00000001.zip")
    frozen, _ = _freeze(env, [_row("00000001", "high")])
    assert [r["sheet"] for r in P.shipping(frozen)] == ["00000001"]
    marks = {"00000001": {"verdict": "wrong_fit", "saved_at": "2026-11-29T01:00:00Z", "note": "off"}}
    frozen, rep = _freeze(env, [_row("00000001", "high")], frozen=frozen, marks=marks)
    assert P.shipping(frozen) == []
    row = frozen["placings"][0]
    assert row["status"] == "withdrawn" and row["withdrawn"]["reason"] == "owner_marked_wrong_fit"
    assert row["withdrawn"]["mark"]["saved_at"] == "2026-11-29T01:00:00Z"
    assert rep["WITHDRAWN"]["owner_marked_wrong_fit"][0]["sheet"] == "00000001"
    assert "owner_marked_wrong_fit" not in rep["held_out"]
    # a rerun with the same mark keeps it withdrawn; it is never re-accepted by its class
    frozen, rep = _freeze(env, [_row("00000001", "high")], frozen=frozen, marks=marks)
    assert P.shipping(frozen) == [] and "withdrawn_stays_withdrawn" in rep["held_out"]


def test_only_a_later_right_mark_brings_a_withdrawn_row_back_as_a_new_decision(tmp_path):
    env = _Env(tmp_path)
    _zip(env.dir, "00000001.zip")
    v2 = [_row("00000001", "high", refit=False)]
    frozen, _ = _freeze(env, v2)
    frozen, _ = _freeze(env, v2, frozen=frozen,
                        marks={"00000001": {"verdict": "unsure", "saved_at": "2026-11-28T07:00:00Z"}})
    page = P.Page("v2", _write_page(env, "00000001", 1e6), _page_run(env, v2), "2026-11-28T06:01:00Z",
                  "2026-11-28T09:00:00Z")
    later = {"00000001": {"verdict": "right", "saved_at": "2026-11-28T08:00:00Z", "lake_after": "wbk:1"}}
    frozen, rep = _freeze(env, v2, frozen=frozen, marks=later, pages=[page])
    row = frozen["placings"][0]
    assert rep["re_accepted"] == ["00000001"] and row["status"] == "accepted" and row["accepted_as"] == "right"
    assert row["previous"][0]["status"] == "withdrawn"


def test_a_newer_survey_accepted_later_withdraws_the_older_row(tmp_path):
    env = _Env(tmp_path)
    _zip(env.dir, "00000001.zip")
    _zip(env.dir, "00000002.zip")
    meta = {"00000001": {"draft_date": "1971-11-01Z"}, "00000002": {"draft_date": "1987-04-15Z"}}
    frozen, _ = _freeze(env, [_row("00000001", "high"), _row("00000002", "review")], meta=meta)
    frozen, rep = _freeze(env, [_row("00000001", "high"), _row("00000002", "high")], frozen=frozen, meta=meta)
    assert [r["sheet"] for r in P.shipping(frozen)] == ["00000002"]
    assert rep["WITHDRAWN"]["superseded_by_newer_survey"][0]["kept"] == "00000002"
    lakes = [lk["wbk"] for r in P.shipping(frozen) for lk in r["lakes"]]
    assert len(lakes) == len(set(lakes))                     # never two shipping rows for one lake


def test_a_bad_status_is_refused_on_load(tmp_path):
    p = tmp_path / "placings.json"
    p.write_text(json.dumps({"schema": P.SCHEMA, "placings": [{"sheet": "1", "status": "maybe"}]}))
    with pytest.raises(ValueError, match="status"):
        P.load(p)


def test_a_sheet_without_a_stated_unit_waits_for_the_printed_chart(tmp_path):
    env = _Env(tmp_path)
    _zip(env.dir, "00000001.zip", values=(10.0, 20.0), words="lake contours")
    rows = [_row("00000001", "high")]
    frozen, rep = _freeze(env, rows)
    assert frozen["placings"] == [] and rep["held_out"]["units_not_read"][0]["sheet"] == "00000001"
    units = {"00000001": {"sheet": "00000001", "unit": "feet", "words": "MAX. DEPTH 148'", "where": "statistics",
                          "page": 1, "pdf": "00000001.pdf"}}
    frozen, rep = _freeze(env, rows, units=units)
    r = frozen["placings"][0]
    assert r["units"] == "feet" and r["units_evidence"]["words"] == "MAX. DEPTH 148'"


def test_mutation_units_unstated_hold_holds_even_a_read_sheet(tmp_path, monkeypatch):
    env = _Env(tmp_path)
    _zip(env.dir, "00000001.zip", words="lake contours")
    monkeypatch.setattr(P, "UNITS_UNSTATED", "hold")
    units = {"00000001": {"sheet": "00000001", "unit": "feet", "words": "x", "where": "y", "page": 1, "pdf": "p"}}
    frozen, rep = _freeze(env, [_row("00000001", "high")], units=units)
    assert frozen["placings"] == [] and "units_unstated" in rep["held_out"]


def test_a_no_data_code_the_arcs_cannot_prove_holds_the_sheet_out(tmp_path):
    env = _Env(tmp_path)
    _zip(env.dir, "00000001.zip", values=(1.0, 999.0))
    frozen, rep = _freeze(env, [_row("00000001", "high")])
    assert frozen["placings"] == [] and rep["held_out"]["depth_code_unproven"][0]["codes"] == [999.0]


def test_two_surveys_of_one_lake_keep_the_newer(tmp_path):
    env = _Env(tmp_path)
    _zip(env.dir, "00000001.zip")
    _zip(env.dir, "00000002.zip")
    meta = {"00000001": {"draft_date": "1971-11-01Z"}, "00000002": {"draft_date": "1987-04-15Z"}}
    frozen, rep = _freeze(env, [_row("00000001", "high"), _row("00000002", "high_stretched")], meta=meta)
    assert [r["sheet"] for r in frozen["placings"]] == ["00000002"]
    assert rep["held_out"]["older_survey"][0] == {"sheet": "00000001", "lake": "wbk:1", "draft_date": "1971-11-01",
                                                  "kept": "00000002", "kept_draft_date": "1987-04-15"}


def test_a_two_lake_sheet_is_one_row_with_both_lakes(tmp_path):
    env = _Env(tmp_path)
    _zip(env.dir, "00000001.zip")
    frozen, _ = _freeze(env, [_row("00000001", "high", lake="wbk:1+wbk:2")])
    assert frozen["placings"][0]["lakes"] == [{"wbk": "wbk:1", "item": "wbk:1"}, {"wbk": "wbk:2", "item": "wbk:2"}]


def test_a_lake_with_no_single_registry_item_is_held_out(tmp_path):
    env = _Env(tmp_path)
    _zip(env.dir, "00000001.zip")
    frozen, rep = _freeze(env, [_row("00000001", "high", lake="wbk:9")])
    assert frozen["placings"] == [] and rep["held_out"]["no_single_registry_item"][0]["lake"] == "wbk:9"


def test_an_accepted_row_is_never_rewritten_by_a_rerun(tmp_path):
    env = _Env(tmp_path)
    _zip(env.dir, "00000001.zip")
    frozen, _ = _freeze(env, [_row("00000001", "high", pose_dx=1e6)])
    before = json.dumps(frozen, sort_keys=True)
    frozen, rep = _freeze(env, [_row("00000001", "high", pose_dx=1e6 + 50)], frozen=frozen)
    assert json.dumps(frozen, sort_keys=True) == before
    assert rep["rerun_disagrees"] == [{"sheet": "00000001", "differs": ["pose"]}] and rep["added"] == []


def test_load_raises_on_a_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError, match="frozen placings are missing"):
        P.load(tmp_path / "placings.json")


def test_the_committed_files_are_whole():
    cur = under_test.curated()
    frozen = P.load(cur.bathymetry.placings)
    assert frozen["schema"] == P.SCHEMA and frozen["_about"]
    units = P.load_units(cur.bathymetry.sheet_units)
    assert units and all(r["words"] and r["page"] == 1 and r["pdf"] == f"{s}.pdf" for s, r in units.items())
    # a scale bar is never evidence
    assert not [s for s, r in units.items() if "scale bar" in r["where"].lower()]
