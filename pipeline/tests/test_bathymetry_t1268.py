"""T1268: the placed depth contours and the tiles' `depth_contour` layer.

What must never happen: a line drawn where its frozen pose does not put it; feet shipped as metres; a line on land; a
two-lake sheet's lines on the wrong lake; an adjustment lost; old lines shipped after a new freeze; the map shipping
without depth while saying nothing. Synthetic sheets only.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import LineString, box

from pipeline.bathymetry import placed_contours as PC
from pipeline.bathymetry import placings as P
from pipeline.bathymetry.refit import Pose, apply
from pipeline.deliver.tiles import export, ladder
from pipeline.deliver.tiles.layers import BY_NAME, contract


def _row(sheet="00000001", units="metres", lakes=(("wbk:1", 1),), pose=None):
    return {"sheet": sheet, "zip": f"{sheet}.zip", "zip_sha256": "x", "coverage": "t.e00", "title": "TEST LAKE",
            "lakes": [{"wbk": f"wbk:{w}", "item": item} for item, w in lakes],
            "pose": pose or {"origin": [0.0, 0.0], "mirror": False, "scale": 1.0, "angle_deg": 0.0, "dx": 0.0, "dy": 0.0},
            "units": units, "units_evidence": {"from": "vector file", "words": f"depths in {units}"},
            "accepted_as": "high", "draft_date": "1977-06-08"}


SQUARE = [(10, 10), (90, 10), (90, 90), (10, 90), (10, 10)]


def test_a_line_lands_where_its_frozen_pose_puts_it():
    pose = {"origin": [50.0, 50.0], "mirror": True, "scale": 1.03, "angle_deg": 33.0, "dx": 1000.0, "dy": 2000.0}
    want = apply(LineString(SQUARE), Pose(True, 1.03, 33.0, 1000.0, 2000.0), (50.0, 50.0))
    outline = want.buffer(500)
    pieces, _ = PC.place_sheet(_row(pose=pose), [(-4.0, "HA", SQUARE)], {1: outline})
    assert len(pieces) == 1
    assert np.allclose(pieces[0]["coords"], [(round(x, 2), round(y, 2)) for x, y in want.coords])


def test_the_owner_s_adjustment_is_drawn_as_the_page_drew_it():
    base = {"origin": [50.0, 50.0], "mirror": False, "scale": 1.0, "angle_deg": 10.0, "dx": 1000.0, "dy": 2000.0}
    adj = {"turn_deg": 2, "scale": 0.84, "mirror": False, "dx_m": 40, "dy_m": 50}
    pivot = [1050.0, 2050.0]
    pose = P.compose(base, adj, pivot)
    pieces, _ = PC.place_sheet(_row(pose=pose), [(-4.0, "HA", SQUARE)], {1: box(-1e4, -1e4, 1e4, 1e4)})
    w = P.place(np.array(SQUARE, float), base)
    page = (w - pivot) @ P.mat(2, 0.84, False).T + pivot + [40, 50]
    assert np.allclose(pieces[0]["coords"], page, atol=0.01)


def test_feet_are_converted_exactly_and_a_short_sheet_s_lines_are_all_index_lines():
    lines = [(-10.0, "HA", SQUARE), (-30.0, "HA", SQUARE)]
    ft, _ = PC.place_sheet(_row(units="feet"), lines, {1: box(-1e3, -1e3, 1e3, 1e3)})
    assert [(p["depth_m"], p["native"], p["index"], p["minzoom"]) for p in ft] == [(3.048, 10.0, True, 11),
                                                                                    (9.144, 30.0, True, 11)]
    m, _ = PC.place_sheet(_row(units="metres"), [(-5.0, "HA", SQUARE), (-20.0, "HA", SQUARE)], {1: box(-1e3, -1e3, 1e3, 1e3)})
    assert [(p["depth_m"], p["index"]) for p in m] == [(5.0, True), (20.0, True)]
    with pytest.raises(ValueError, match="only feet or metres"):
        PC.depth_m(3.0, "not stated")


def test_a_line_on_land_is_cut_at_the_shoreline_and_its_share_recorded():
    line = [(0, 50), (200, 50)]                       # 200 m; the lake holds x < 100
    pieces, st = PC.place_sheet(_row(), [(-2.0, "HA", line)], {1: box(-10, 0, 100, 100)})
    assert len(pieces) == 1 and pieces[0]["coords"][0] == (0.0, 50.0) and pieces[0]["coords"][-1] == (100.0, 50.0)
    s = st["wbk:1"]
    assert s["total_m"] == pytest.approx(200) and s["kept_m"] == pytest.approx(100)


def test_a_piece_under_the_minimum_is_dropped_and_counted():
    line = [(10, 50), (200, 50)]
    # the lake is two shores: a 90 m piece in the first, a piece of half the minimum in the second
    lake = box(0, 0, 100, 100).union(box(105, 0, 105 + PC.MIN_PIECE_M / 2, 100))
    pieces, st = PC.place_sheet(_row(), [(-2.0, "HA", line)], {1: lake})
    assert len(pieces) == 1 and pieces[0]["coords"][-1] == (100.0, 50.0)
    assert st["wbk:1"]["stubs"] == 1 and st["wbk:1"]["stub_m"] == pytest.approx(PC.MIN_PIECE_M / 2)


def test_a_two_lake_sheet_s_lines_go_to_the_lake_each_piece_lies_in():
    rows = _row(lakes=(("wbk:1", 1), ("wbk:2", 2)))
    line = [(10, 50), (190, 50)]
    outlines = {1: box(0, 0, 90, 100), 2: box(110, 0, 200, 100)}
    pieces, st = PC.place_sheet(rows, [(-3.0, "HA", line)], outlines)
    assert sorted((p["item"], p["coords"][0], p["coords"][-1]) for p in pieces) == [
        ("wbk:1", (10.0, 50.0), (90.0, 50.0)), ("wbk:2", (110.0, 50.0), (190.0, 50.0))]
    assert sum(s["total_m"] for s in st.values()) == pytest.approx(180)


def test_a_two_lake_stub_counts_for_the_lake_it_lies_in():
    rows = _row(lakes=(("wbk:1", 1), ("wbk:2", 2)))
    line = [(10, 50), (100 + PC.MIN_PIECE_M / 2, 50)]          # 90 m in lake 1, a stub in lake 2
    outlines = {1: box(0, 0, 90, 100), 2: box(100, 0, 200, 100)}
    _pieces, st = PC.place_sheet(rows, [(-3.0, "HA", line)], outlines)
    assert st["wbk:2"]["stubs"] == 1 and st["wbk:2"]["total_m"] == pytest.approx(PC.MIN_PIECE_M / 2)
    assert st["wbk:1"]["total_m"] == pytest.approx(100 + PC.MIN_PIECE_M / 2 - 10 - PC.MIN_PIECE_M / 2)


def test_a_lake_with_no_outline_raises():
    with pytest.raises(ValueError, match="no FWA outline"):
        PC.place_sheet(_row(), [(-2.0, "HA", SQUARE)], {})


def _frozen(rows):
    return {"schema": P.SCHEMA, "placings": rows}


def _build(rows, outlines, inputs=None):
    return PC.build(_frozen(rows), read_contours=lambda r: [(-2.0, "HA", SQUARE), (-10.0, "HA", SQUARE)],
                    outlines=outlines, inputs=inputs or {"placings_sha256": "p", "vectors_sha256": "v", "version": 1})


def test_the_output_is_sorted_and_the_same_twice_and_the_facts_follow_it(tmp_path):
    rows = [_row("00000002", lakes=(("wbk:2", 2),)), _row("00000001")]
    outlines = {1: box(-1e3, -1e3, 1e3, 1e3), 2: box(-1e3, -1e3, 1e3, 1e3)}
    a, b = tmp_path / "a", tmp_path / "b"
    PC.write(a, *_build(rows, outlines))
    PC.write(b, *_build(list(reversed(rows)), outlines))
    for f in ("contours.geojsonl", "lake_facts.json", "report.json"):
        assert (a / f).read_bytes() == (b / f).read_bytes(), f
    facts = json.loads((a / "lake_facts.json").read_text())
    assert [(x["item"], x["deepest_m"], x["survey_year"], x["sheet"], x["contours"]) for x in facts["lakes"]] == [
        ("wbk:1", 10.0, 1977, "00000001", 2), ("wbk:2", 10.0, 1977, "00000002", 2)]


def test_mutation_the_size_gate_refuses_before_anything_is_written(monkeypatch):
    monkeypatch.setattr(PC, "MAX_VERTICES", 3)
    with pytest.raises(RuntimeError, match="MAX_VERTICES"):
        _build([_row()], {1: box(-1e3, -1e3, 1e3, 1e3)})


def test_a_lake_clipped_over_the_line_is_listed():
    pieces, facts, rep = PC.build(_frozen([_row()]), read_contours=lambda r: [(-2.0, "HA", [(0, 50), (200, 50)])],
                                  outlines={1: box(-10, 0, 100, 100)}, inputs={"placings_sha256": "p"})
    assert rep["clipped_over_pct"] == [{"item": "wbk:1", "clipped_pct": 50.0, "sheet": "00000001", "title": "TEST LAKE"}]


def test_a_withdrawn_row_draws_nothing(tmp_path):
    keep, gone = _row("00000001"), dict(_row("00000002", lakes=(("wbk:2", 2),)), status="withdrawn",
                                        withdrawn={"reason": "owner_marked_wrong_fit"})
    pieces, facts, rep = _build([keep, gone], {1: box(-1e3, -1e3, 1e3, 1e3), 2: box(-1e3, -1e3, 1e3, 1e3)})
    assert {p["sheet"] for p in pieces} == {"00000001"} and [f["item"] for f in facts["lakes"]] == ["wbk:1"]
    assert rep["rows"] == 1 and rep["withdrawn_not_drawn"] == 1


def test_only_withdrawn_rows_draw_an_empty_layer_without_a_placed_set(tmp_path):
    out = tmp_path / "layers"
    out.mkdir()
    gone = dict(_row(), status="withdrawn", withdrawn={"reason": "owner_marked_unsure"})
    assert export.export_contours(out, _reg(tmp_path), placings=_placings_file(tmp_path, [gone]), placed=tmp_path / "nowhere") == \
        {"depth_contour": 0}


def test_old_lines_are_refused_after_a_new_freeze(tmp_path):
    with pytest.raises(PC.StalePlacedContours, match="no placed depth contours"):
        PC.require_current(tmp_path, inputs={"placings_sha256": "p"})
    PC.write(tmp_path, *_build([_row()], {1: box(-1e3, -1e3, 1e3, 1e3)},
                               inputs={"placings_sha256": "old", "vectors_sha256": "v", "version": 1}))
    with pytest.raises(PC.StalePlacedContours, match="other inputs"):
        PC.require_current(tmp_path, inputs={"placings_sha256": "new", "vectors_sha256": "v", "version": 1})
    assert PC.require_current(tmp_path, inputs={"placings_sha256": "old", "vectors_sha256": "v", "version": 1}) \
        == tmp_path / "contours.geojsonl"


# ---------------------------------------------------------------------------------------------- the tiles read it

def _reg(tmp_path, ids=("wbk:1", "wbk:2")):
    d = tmp_path / "atlas"
    d.mkdir(exist_ok=True)
    (d / "registry.json").write_text(json.dumps({"items": [{"id": i} for i in ids]}))
    return d


def test_a_lake_item_the_new_atlas_does_not_hold_is_refused_naming_the_row(tmp_path):
    with pytest.raises(PC.UnknownLakeItem, match=r"00000001 wbk:1 item wbk:1"):
        PC.require_items([_row()], PC.registry_ids(_reg(tmp_path, ids=("wbk:2",))), tmp_path / "atlas")
    PC.require_items([_row()], PC.registry_ids(_reg(tmp_path)), tmp_path / "atlas")
    with pytest.raises(FileNotFoundError, match="no registry"):
        PC.registry_ids(tmp_path / "nowhere")


def test_the_tiles_refuse_lines_whose_lake_left_the_atlas(tmp_path, monkeypatch):
    inputs = {"placings_sha256": "p", "vectors_sha256": "v", "version": 1}
    placed = tmp_path / "placed"
    PC.write(placed, *_build([_row()], {1: box(-1e3, -1e3, 1e3, 1e3)}, inputs=inputs))
    monkeypatch.setattr(PC, "inputs_now", lambda *a, **k: inputs)
    out = tmp_path / "layers"
    out.mkdir()
    with pytest.raises(PC.UnknownLakeItem, match="placed_contours"):
        export.export_contours(out, _reg(tmp_path, ids=("wbk:2",)), placings=_placings_file(tmp_path, [_row()]),
                               placed=placed)


def _placings_file(tmp_path, rows):
    p = tmp_path / "placings.json"
    p.write_text(json.dumps(_frozen(rows)))
    return p


def test_no_frozen_row_draws_an_empty_layer(tmp_path):
    out = tmp_path / "layers"
    out.mkdir()
    assert export.export_contours(out, _reg(tmp_path), placings=_placings_file(tmp_path, []), placed=tmp_path / "nowhere") == \
        {"depth_contour": 0}


def _fake_make(tmp_path, calls):
    """The producer as the tiles call it, on synthetic lines (no zips): the SHIPPING rows' lines only."""
    def make(frozen, *, build_dir, out=None, gpkg=None, inputs=None):
        calls.append([r["sheet"] for r in P.shipping(frozen)])
        outlines = {int(lk["wbk"].split(":")[1]): box(-1e7, -1e7, 1e7, 1e7) for r in frozen["placings"] for lk in r["lakes"]}
        PC.write(out, *PC.build(frozen, read_contours=lambda r: [(-2.0, "HA", SQUARE)], outlines=outlines, inputs=inputs))
    return make


def test_the_tiles_make_a_missing_placed_set_through_the_one_producer(tmp_path, monkeypatch):
    inputs = {"placings_sha256": "p", "vectors_sha256": "v", "version": PC.VERSION}
    monkeypatch.setattr(PC, "inputs_now", lambda *a, **k: inputs)
    calls = []
    monkeypatch.setattr(PC, "make", _fake_make(tmp_path, calls))
    out = tmp_path / "layers"
    out.mkdir()
    got = export.export_contours(out, _reg(tmp_path), placings=_placings_file(tmp_path, [_row()]),
                                 placed=tmp_path / "placed")
    assert calls == [["00000001"]] and got == {"depth_contour": 1}


def test_a_producer_that_fails_stops_the_tiles(tmp_path, monkeypatch):
    monkeypatch.setattr(PC, "inputs_now", lambda *a, **k: {"placings_sha256": "p"})
    def boom(*a, **k):
        raise RuntimeError("placed depth contours: 9 vertices, over the gate")
    monkeypatch.setattr(PC, "make", boom)
    out = tmp_path / "layers"
    out.mkdir()
    with pytest.raises(RuntimeError, match="over the gate"):
        export.export_contours(out, _reg(tmp_path), placings=_placings_file(tmp_path, [_row()]), placed=tmp_path / "p")


def test_the_export_writes_the_whole_layer_each_run_so_a_withdrawn_lake_s_lines_go(tmp_path, monkeypatch):
    """P1 of the review: the tiles read any non-empty layer file, so the export owns it: 2 rows -> both drawn; one
    withdrawn -> only the other; all withdrawn -> the file is there and EMPTY."""
    monkeypatch.setattr(PC, "inputs_now", lambda path, *a, **k: {"placings_sha256": Path(path).read_text()})
    monkeypatch.setattr(PC, "make", _fake_make(tmp_path, []))
    out = tmp_path / "layers"
    out.mkdir()
    one, two = _row("00000001"), _row("00000002", lakes=(("wbk:2", 2),))
    def run(rows):
        export.export_contours(out, _reg(tmp_path), placings=_placings_file(tmp_path, rows), placed=tmp_path / "placed")
        f = out / "depth_contour.geojsonl"
        return sorted({json.loads(l)["properties"]["item"] for l in f.read_text().splitlines()}), f.stat().st_size
    assert run([one, two])[0] == ["wbk:1", "wbk:2"]
    gone = {"status": "withdrawn", "withdrawn": {"reason": "owner_marked_wrong_fit"}}
    assert run([one, dict(two, **gone)])[0] == ["wbk:1"]
    assert run([dict(one, **gone), dict(two, **gone)]) == ([], 0)


def test_every_constant_that_shapes_the_lines_is_in_the_policy_digest(monkeypatch):
    """Like POLICY_VERSION (AGENTS 20): a constant of the producer or of the depth ladder left out of `policy()` could
    change the lines while `require_current` still passed the old set."""
    from pipeline.deliver.tiles import ladder as L
    consts = {k for k, v in vars(PC).items() if k.isupper() and isinstance(v, (int, float, tuple)) and k != "COMMAND"}
    consts |= {"NICE_STEPS", "INDEX_LINES_MIN", "INDEX_LINES_MAX", "MIDDLE_LINES_FACTOR"}
    assert consts <= set(PC.policy()), sorted(consts - set(PC.policy()))
    before = PC.policy_digest()
    monkeypatch.setattr(PC, "MIN_PIECE_M", PC.MIN_PIECE_M + 1)
    assert PC.policy_digest() != before
    monkeypatch.setattr(PC, "MIN_PIECE_M", PC.MIN_PIECE_M - 1)
    monkeypatch.setattr(L, "INDEX_LINES_MAX", L.INDEX_LINES_MAX + 1)
    assert PC.policy_digest() != before


def test_the_layer_carries_item_depth_and_index_and_the_ladder(tmp_path, monkeypatch):
    inputs = {"placings_sha256": "p", "vectors_sha256": "v", "version": 1}
    placed = tmp_path / "placed"
    # a lake in BC Albers near Kamloops, so the 4326 transform is a real one
    pose = {"origin": [50.0, 50.0], "mirror": False, "scale": 1.0, "angle_deg": 0.0, "dx": 1_400_000.0, "dy": 700_000.0}
    rows = [_row(pose=pose)]
    outline = apply(box(0, 0, 100, 100), Pose(), (50.0, 50.0))
    from shapely import affinity
    outline = affinity.translate(outline, 1_400_000, 700_000)
    PC.write(placed, *PC.build(_frozen(rows), read_contours=lambda r: [(-5.0, "HA", SQUARE), (-10.0, "HA", SQUARE)],
                               outlines={1: outline}, inputs=inputs))
    monkeypatch.setattr(PC, "inputs_now", lambda *a, **k: inputs)
    out = tmp_path / "layers"
    out.mkdir()
    assert export.export_contours(out, _reg(tmp_path), placings=_placings_file(tmp_path, rows), placed=placed) == {"depth_contour": 2}
    feats = [json.loads(l) for l in (out / "depth_contour.geojsonl").read_text().splitlines()]
    got = sorted((f["properties"].get("depth_m"), f["properties"].get("index"), f["tippecanoe"]["minzoom"],
                  f["properties"]["item"]) for f in feats)
    assert got == [(5.0, 1, 11, "wbk:1"), (10.0, 1, 11, "wbk:1")]          # index: 1 or absent, never 0
    assert set(feats[0]["properties"]) <= set(BY_NAME["depth_contour"].attrs)


def test_a_feet_sheet_s_layer_takes_its_zooms_and_index_from_feet(tmp_path, monkeypatch):
    inputs = {"placings_sha256": "p", "vectors_sha256": "v", "version": PC.VERSION}
    placed = tmp_path / "placed"
    pose = {"origin": [50.0, 50.0], "mirror": False, "scale": 1.0, "angle_deg": 0.0, "dx": 1_400_000.0, "dy": 700_000.0}
    rows = [_row(pose=pose, units="feet")]
    from shapely import affinity
    outline = affinity.translate(box(0, 0, 100, 100), 1_400_000, 700_000)
    charlotte = [20.0, 50.0, 75.0, 100.0, 125.0, 150.0, 200.0, 250.0, 300.0, 325.0]     # Charlotte Lake's levels (ft)
    lines = [(-v, "HA", SQUARE) for v in charlotte]
    PC.write(placed, *PC.build(_frozen(rows), read_contours=lambda r: lines, outlines={1: outline}, inputs=inputs))
    monkeypatch.setattr(PC, "inputs_now", lambda *a, **k: inputs)
    out = tmp_path / "layers"
    out.mkdir()
    export.export_contours(out, _reg(tmp_path), placings=_placings_file(tmp_path, rows), placed=placed)
    feats = [json.loads(l) for l in (out / "depth_contour.geojsonl").read_text().splitlines()]
    got = {round(f["properties"]["depth_m"] / PC.FEET): (f["properties"].get("index"), f["tippecanoe"]["minzoom"])
           for f in feats}
    assert {ft for ft, (i, z) in got.items() if i == 1 and z == 11} == {20, 100, 200, 300}
    assert {ft for ft, (i, z) in got.items() if z == 12} == {50, 150, 250}
    assert {ft for ft, (i, z) in got.items() if z == 13} == {75, 125, 325}


def test_the_ladder_is_per_sheet_on_its_own_levels():
    """The smallest nice step leaving INDEX_LINES_MIN..MAX index levels; the next finer nice step for z12 when it adds
    at most MIDDLE_LINES_FACTOR x the index lines (the planning chat's pick A, 2026-11-28)."""
    assert (ladder.INDEX_LINES_MIN, ladder.INDEX_LINES_MAX, ladder.MIDDLE_LINES_FACTOR) == (2, 4, 3)
    assert ladder.sheet_ladder([1, 2, 3, 4, 5, 6, 7]) == (2, 1)                    # Abruzzi, metres: 2, 4, 6 labelled
    assert ladder.sheet_ladder(range(10, 130, 10)) == (50, 20)                     # a deep 10-step sheet: 50, 100
    # Cowichan's 24 m steps: no nice step leaves 2-4 levels; 120 m alone is its index; the 2 m middle would be 6x: none
    assert ladder.sheet_ladder([24, 48, 72, 96, 120, 144]) == (5, None)
    for few in ([5, 10, 15], [20, 40, 60], [1, 2, 3, 4]):                          # Chief, Heffley: every line labelled
        steps = ladder.sheet_ladder(few)
        assert all(ladder.depth_line_zoom(v, steps) == (11, True) for v in few)
    assert ladder.sheet_ladder([7]) == (7.0, None) and ladder.depth_line_zoom(7, (7.0, None)) == (11, True)
    assert ladder.depth_line_zoom(48, (5, None)) == (13, False)
    with pytest.raises(ValueError, match="no depth level"):
        ladder.sheet_ladder([])


def test_every_sheet_gets_an_index_line_and_none_is_flooded():
    for levels in ([1, 2, 3], range(1, 40), range(5, 700, 5), [20, 50, 51, 99, 100, 150, 200, 250, 300], [8, 10, 20, 30]):
        steps = ladder.sheet_ladder(levels)
        n = sum(ladder.depth_line_zoom(v, steps)[1] for v in set(levels))
        assert 1 <= n <= ladder.INDEX_LINES_MAX, (list(levels)[:5], steps, n)


def test_mutation_a_metres_rule_on_converted_feet_draws_nothing_below_z13():
    """The measured failure: Charlotte Lake's 20-325 ft lines, converted to metres, hit no 5 m or 10 m multiple."""
    ft = [20.0, 50.0, 75.0, 100.0, 125.0, 150.0, 200.0, 250.0, 300.0, 325.0]
    as_metres = [ladder.depth_line_zoom(PC.depth_m(v, "feet"), (10.0, 5.0))[0] for v in ft]
    native = [ladder.depth_line_zoom(v, ladder.sheet_ladder(ft))[0] for v in ft]
    assert min(as_metres) == 13 and min(native) == 11


def test_a_feet_depth_reads_back_as_printed():
    for ft in (1.0, 5.0, 10.0, 25.0, 325.0, 684.0):
        d = PC.depth_m(ft, "feet")
        assert round(d / PC.FEET, 6) == ft


def test_the_contract_names_depth_contour_and_no_longer_contour():
    c = contract()["layers"]
    assert "contour" not in c
    assert c["depth_contour"]["attrs"] == ["item", "depth_m", "index"] and c["depth_contour"]["featureId"] == "item"
    assert c["depth_contour"]["minzoom"] == 11 and c["depth_contour"]["geometry"] == "line"
