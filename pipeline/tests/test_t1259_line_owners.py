"""T1259 (owner 2026-11-27): "thos e braids should be added as name variants of the stream and be moved to the stream
instead of being part of the skeena all the way dopwn to the build step? "; his pick: "B: the braids become Kitsumkalum
water". `waters/line_owners.json` gives FWA blue lines to another water by the name-variant mechanism (the water's own
name tuple, carrying its gnis, `graph.names.apply_line_owners`), validated, and checked after the registry
(`check_line_owners`). No data needed: a hand-built graph."""
from __future__ import annotations

import json

import pytest

from pipeline.atlas.graph import names as N
from pipeline.atlas.registry.build import _effective_gnis, _wsc_gnis_map, item_id
from pipeline.common.models import NameSource, NameTuple, NodeKind, StreamGraph, StreamNode

SK, KI = "2936", "3942"
WSC_SK, WSC_KI = "400-431358", "400-431358-585806"


def _graph():
    """The Skeena's main line (blk 1, gnis 2936), two braids beside it (blks 360222216, 360222215: no gnis, the
    Skeena's code, an inherited side-channel name), the Kitsumkalum (blk 2, gnis 3942), and a creek that joins the
    larger braid (blk 3, no name)."""
    g = StreamGraph()
    def s(nid, blk, wsc, gnis="", tuples=(), disp=""):
        g.nodes[nid] = StreamNode(node_id=nid, kind=NodeKind.stream, blk=blk, wsc=wsc, gnis_id=gnis,
                                  display_name=disp, name_tuples=tuple(tuples), stream_magnitude=100 if gnis else 1)
    s("1:0", "1", WSC_SK, SK, [NameTuple("Skeena River", NameSource.gazette, gnis_id=SK)], "Skeena River")
    inherit = [NameTuple("Skeena River", NameSource.side_channel, gnis_id=SK)]
    s("360222216:0", "360222216", WSC_SK, tuples=inherit, disp="Skeena River")
    s("360222215:0", "360222215", WSC_SK, tuples=inherit, disp="Skeena River")
    s("2:0", "2", WSC_KI, KI, [NameTuple("Kitsumkalum River", NameSource.gazette, gnis_id=KI)], "Kitsumkalum River")
    s("3:0", "3", WSC_SK + "-100000")
    return g


def _owners(**kw):
    e = {"blks": ["360222216", "360222215"], "water": f"gnis:{KI}", "from": f"gnis:{SK}", "name": "Kitsumkalum River",
         "words": {"dfo": "The mouth of the Kitsumkalum River is designated by fishing boundary signs ...",
                   "owner_pick": "B: the braids become Kitsumkalum water"}}
    e.update(kw)
    return [e]


def _item_of(g, nid):
    return item_id(g.nodes[nid], _wsc_gnis_map(g))


def test_the_braids_become_kitsumkalum_water_and_the_skeena_keeps_its_main_line():
    g = _graph()
    assert _item_of(g, "360222216:0") == f"gnis:{SK}"                # FWA's code: the Skeena's
    assert N.apply_line_owners(g, _owners()) == 2
    assert {_item_of(g, n) for n in ("360222216:0", "360222215:0")} == {f"gnis:{KI}"}
    assert g.nodes["360222216:0"].display_name == "Kitsumkalum River"
    assert _item_of(g, "1:0") == f"gnis:{SK}" and _item_of(g, "2:0") == f"gnis:{KI}"   # the main lines stay
    # the creek joining the larger braid keeps its own code's owner: it is not named or moved by the entry
    assert _item_of(g, "3:0") == f"wsc:{WSC_SK}-100000" and not g.nodes["3:0"].name_tuples


def test_mutation_pin_without_the_entry_the_braids_stay_the_skeenas():
    g = _graph()
    assert N.apply_line_owners(g, []) == 0
    assert {_item_of(g, n) for n in ("360222216:0", "360222215:0")} == {f"gnis:{SK}"}


def test_the_loader_refuses_by_name(tmp_path):
    def load(doc):
        p = tmp_path / "line_owners.json"
        p.write_text(json.dumps(doc))
        return N.load_line_owners(p)
    ok = {"_about": "x", "owners": _owners()}
    assert load(ok)[0]["water"] == f"gnis:{KI}"
    with pytest.raises(ValueError, match="unknown keys"):
        load({"_about": "x", "owners": [{**_owners()[0], "reach": {}}]})
    with pytest.raises(ValueError, match="empty"):
        load({"_about": "x", "owners": [{**_owners()[0], "words": {}}]})
    with pytest.raises(ValueError, match="gnis water id"):
        load({"_about": "x", "owners": _owners(water="wsc:400")})
    with pytest.raises(ValueError, match="in entries 0 and 1"):
        load({"_about": "x", "owners": _owners() + _owners(name="Other")})
    with pytest.raises(ValueError, match="`_about` and `owners`"):
        load({"owners": []})


def test_the_graph_step_refuses_by_line():
    with pytest.raises(ValueError, match="blue line 999 .* does not exist"):
        N.apply_line_owners(_graph(), _owners(blks=["999"]))
    with pytest.raises(ValueError, match="belongs to gnis:3942, not to gnis:2936"):
        N.apply_line_owners(_graph(), _owners(blks=["2"]))                 # a third water's line
    with pytest.raises(ValueError, match="water gnis:1 .* is not in the graph"):
        N.apply_line_owners(_graph(), _owners(water="gnis:1"))
    with pytest.raises(ValueError, match="also named by name_variants"):
        N.apply_line_owners(_graph(), _owners(), [{"target": {"blks": ["360222215"]}, "names": [{"name": "X"}]}])
    g = _graph()
    n = g.nodes["360222215:0"]
    from dataclasses import replace
    g.nodes["360222215:0"] = replace(n, name_tuples=(NameTuple("Elsewhere", NameSource.override, gnis_id="7"),
                                                     *n.name_tuples))
    with pytest.raises(ValueError, match="(would move it elsewhere|belongs to gnis:7)"):
        N.apply_line_owners(g, _owners())


def test_the_registry_check_stops_a_line_that_did_not_land():
    from types import SimpleNamespace
    g = _graph()
    N.apply_line_owners(g, _owners())
    reg = {f"gnis:{KI}": SimpleNamespace(section_ids=("2:0", "360222216:0", "360222215:0")),
           f"gnis:{SK}": SimpleNamespace(section_ids=("1:0",))}
    N.check_line_owners(reg, _owners(), g)                                  # landed: passes
    with pytest.raises(ValueError, match="not in gnis:3942's item"):
        N.check_line_owners({**reg, f"gnis:{KI}": SimpleNamespace(section_ids=("2:0", "360222216:0"))}, _owners(), g)
    del g.nodes["360222215:0"]
    with pytest.raises(ValueError, match="was removed before the registry"):
        N.check_line_owners(reg, _owners(), g)


def test_the_curated_file_holds_the_kitsumkalum_braids_with_his_words():
    from pipeline.common.curated import CURATED
    [e] = N.load_line_owners(CURATED.waters.line_owners)
    assert (e["blks"], e["water"], e["from"]) == (["360222216", "360222215"], "gnis:3942", "gnis:2936")
    assert "approx. 1.25 km downstream of the CNR bridge" in e["words"]["dfo"]
    assert e["words"]["owner_pick"] == "B: the braids become Kitsumkalum water"
    assert "only the sidechannel braiding there" in e["words"]["owner_reading"]


def test_the_braids_carry_the_waters_own_name_so_its_page_keeps_the_official_source():
    # (T1259, measured 2026-11-27) with an override tuple the Kitsumkalum's name record read "Project curation (owner
    # decision)", not the gazette's: the water's page changes. The braids carry the water's OWN best tuple of the name
    from pipeline.atlas.registry.build import name_records
    g = _graph()
    N.apply_line_owners(g, _owners())
    t = g.nodes["360222216:0"].name_tuples[0]
    assert (t.name, t.source, t.gnis_id) == ("Kitsumkalum River", NameSource.gazette, KI)
    assert "line_owners.json (T1259)" in t.note
    rec = name_records(["Kitsumkalum River"], [x for n in ("2:0", "360222216:0", "360222215:0")
                                               for x in g.nodes[n].name_tuples])[0]
    assert (rec.source, rec.official) == ("gazette", True)


def test_a_name_the_water_does_not_go_by_is_refused():
    with pytest.raises(ValueError, match="goes by no name 'Kalum River'"):
        N.apply_line_owners(_graph(), _owners(name="Kalum River"))
