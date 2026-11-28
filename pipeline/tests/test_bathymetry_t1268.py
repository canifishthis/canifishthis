"""T1268: the placed depth contours and the tiles' `depth_contour` layer.

What must never happen: a line drawn where its frozen pose does not put it; feet shipped as metres; a line on land; a
two-lake sheet's lines on the wrong lake; an adjustment lost; old lines shipped after a new freeze; the map shipping
without depth while saying nothing. Synthetic sheets only.
"""
from __future__ import annotations

import json

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


def test_feet_are_converted_and_index_lines_are_every_10_m():
    lines = [(-10.0, "HA", SQUARE), (-30.0, "HA", SQUARE)]
    ft, _ = PC.place_sheet(_row(units="feet"), lines, {1: box(-1e3, -1e3, 1e3, 1e3)})
    assert [(p["depth_m"], p["native"], p["index"]) for p in ft] == [(3.0, 10.0, False), (9.1, 30.0, False)]
    m, _ = PC.place_sheet(_row(units="metres"), [(-5.0, "HA", SQUARE), (-20.0, "HA", SQUARE)], {1: box(-1e3, -1e3, 1e3, 1e3)})
    assert [(p["depth_m"], p["index"]) for p in m] == [(5.0, False), (20.0, True)]
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

def _placings_file(tmp_path, rows):
    p = tmp_path / "placings.json"
    p.write_text(json.dumps(_frozen(rows)))
    return p


def test_no_frozen_row_draws_an_empty_layer(tmp_path):
    out = tmp_path / "layers"
    out.mkdir()
    assert export.export_contours(out, placings=_placings_file(tmp_path, []), placed=tmp_path / "nowhere") == \
        {"depth_contour": 0}


def test_frozen_rows_with_no_placed_set_raise_never_skip(tmp_path, monkeypatch):
    out = tmp_path / "layers"
    out.mkdir()
    monkeypatch.setattr(PC, "inputs_now", lambda *a, **k: {"placings_sha256": "p", "vectors_sha256": "v", "version": 1})
    with pytest.raises(PC.StalePlacedContours, match="placed_contours"):
        export.export_contours(out, placings=_placings_file(tmp_path, [_row()]), placed=tmp_path / "nowhere")


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
    assert export.export_contours(out, placings=_placings_file(tmp_path, rows), placed=placed) == {"depth_contour": 2}
    feats = [json.loads(l) for l in (out / "depth_contour.geojsonl").read_text().splitlines()]
    got = sorted((f["properties"].get("depth_m"), f["properties"].get("index"), f["tippecanoe"]["minzoom"],
                  f["properties"]["item"]) for f in feats)
    assert got == [(5.0, None, 12, "wbk:1"), (10.0, 1, 11, "wbk:1")]          # index: 1 or absent, never 0
    assert set(feats[0]["properties"]) <= set(BY_NAME["depth_contour"].attrs)


def test_index_lines_z11_five_metre_lines_z12_the_rest_z13():
    assert ladder.zoom_for_contour(20.0, index=True) == 11
    assert ladder.zoom_for_contour(5.0) == 12 and ladder.zoom_for_contour(3.0) == 13 and ladder.zoom_for_contour(9.1) == 13


def test_the_contract_names_depth_contour_and_no_longer_contour():
    c = contract()["layers"]
    assert "contour" not in c
    assert c["depth_contour"]["attrs"] == ["item", "depth_m", "index"] and c["depth_contour"]["featureId"] == "item"
    assert c["depth_contour"]["minzoom"] == 11 and c["depth_contour"]["geometry"] == "line"
