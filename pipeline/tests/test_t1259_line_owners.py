"""T1259 (owner 2026-11-27): "thos e braids should be added as name variants of the stream and be moved to the stream
instead of being part of the skeena all the way dopwn to the build step? "; his pick: "B: the braids become Kitsumkalum
water". `waters/line_owners.json` gives FWA blue lines to another water by the name-variant mechanism (the water's own
name tuple, carrying its gnis, `graph.names.apply_line_owners`), validated, and checked after the registry
(`check_line_owners`). No data needed: a hand-built graph."""
from __future__ import annotations

import json
from pathlib import Path

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
    # (review L3) a line given back to its own water, and a blue line key that is not one
    with pytest.raises(ValueError, match="`water` and `from` are both gnis:2936"):
        load({"_about": "x", "owners": _owners(water=f"gnis:{SK}")})
    with pytest.raises(ValueError, match="blue line '36022x' is not a blue line key"):
        load({"_about": "x", "owners": _owners(blks=["36022x"])})


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
    # (review L3) an override name of the `from` water's OWN gnis passes the "belongs to" question and is the case
    # that reaches "would move it elsewhere"
    g = _graph()
    n = g.nodes["360222215:0"]
    g.nodes["360222215:0"] = replace(n, name_tuples=(NameTuple("Skeena River", NameSource.override, gnis_id=SK),
                                                     *n.name_tuples))
    with pytest.raises(ValueError, match="blue line 360222215 carries an override name of gnis:2936 .* would move it "
                                         "elsewhere"):
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


def _registry(g):
    """The registry's grouping and ids (`registry.build.item_id`, `_ref_ids`) without its data reads (the drainage
    areas need the FWA GeoPackage)."""
    from collections import defaultdict
    from pipeline.atlas.registry.build import _ref_ids
    from pipeline.common.models import RegistryItem
    groups = defaultdict(list)
    for nid, n in g.nodes.items():
        groups[_item_of(g, nid)].append(n)
    return {i: RegistryItem(id=i, name=i, kind="stream", section_ids=tuple(n.node_id for n in ns), ref_ids=_ref_ids(ns))
            for i, ns in groups.items()}


def test_the_lines_bring_their_geometry_not_the_old_waters_ids():
    # (T1259, coordinator 2026-11-28) the measured B build gave the Kitsumkalum the Skeena's gnis:2936 and its wsc root
    # through the braids' inherited side-channel name: resolved to the Skeena only by first-writer order. The new
    # water's ids are its baseline ids plus the lines' own blk ids; the old water's lose only those blk ids
    base = _registry(_graph())
    g = _graph()
    N.apply_line_owners(g, _owners())
    reg = _registry(g)
    assert "gnis:2936" in reg[f"gnis:{KI}"].ref_ids                          # what the registry alone gives
    with pytest.raises(ValueError, match="both answer to"):
        N.check_line_owners(reg, _owners(), g)                               # refused before the scrub
    assert N.scrub_line_owner_refs(reg, _owners(), g) == [f"gnis:{KI} gnis:{SK}", f"gnis:{KI} wsc:{WSC_SK}"]
    blks = {"blk:360222215", "blk:360222216"}
    assert set(reg[f"gnis:{KI}"].ref_ids) == set(base[f"gnis:{KI}"].ref_ids) | blks
    assert set(reg[f"gnis:{SK}"].ref_ids) == set(base[f"gnis:{SK}"].ref_ids) - blks
    N.check_line_owners(reg, _owners(), g)                                   # and then it passes


@pytest.mark.needs_bundle
def test_the_creek_and_its_feeder_are_kitsumkalum_tributaries(request):
    """(T1259, owner 2026-11-28, his pick: "Kitsumkalum tributary") on the bundle under test: the braids are the
    Kitsumkalum River's sections, and the creek that joins them (360792160, 2.03 km) and its feeder (360464409, 0.54 km)
    take the Kitsumkalum's rows as its tributaries (its Sunday closure to non-guided non-resident aliens, r2, and its bait
    ban, r5), as the Kitsumkalum's own lines do (the Skeena's rows reach both as the Skeena's tributaries, as before). A
    change that drops them back to the Skeena alone is seen here (the bundle without the line owners fails it)."""
    import sqlite3
    from pipeline.tests import under_test as U
    db = sqlite3.connect(str(U.bundle(request)))
    try:
        def rules(blk):
            return {e + " " + r for e, r in db.execute(
                "SELECT DISTINCT rs.entry_id, rs.rule_id FROM section_measure m JOIN section_ruleset s ON s.sid = m.sid "
                "JOIN ruleset rs ON rs.set_id = s.set_id WHERE m.blk = ?", (blk,))}
        owner = {b: {i for (i,) in db.execute("SELECT DISTINCT i.item_id FROM section_measure m JOIN item_section s "
                                              "ON s.sid = m.sid JOIN item i ON i.ord = s.ord WHERE m.blk = ?", (b,))}
                 for b in (360222216, 360222215)}
        assert owner == {360222216: {"gnis:3942"}, 360222215: {"gnis:3942"}}
        for blk in (360792160, 360464409):
            got = rules(blk)
            assert got, f"blue line {blk} has no sections in this bundle"
            assert {"r6:kitsumkalum_kalum_river@6-15 kitsumkalum_river.r2",
                    "r6:kitsumkalum_kalum_river@6-15 kitsumkalum_river.r5"} <= got, blk
    finally:
        db.close()


def test_the_loop_pass_keeps_every_assigned_line():
    """(T1259 x T1242) an assigned line is its new water's: the creek-less loop pass keeps it (`waters/line_owners.json`
    is one of `loop_keep_inputs`' files, every blue line it names a keep), so a loop pass can never quietly take the
    braids; were it to remove one anyway, `check_line_owners` stops the build ("was removed before the registry",
    above). The two braids are loops with a creek and stay in any case."""
    from types import SimpleNamespace
    from pipeline.atlas import build as AB
    from pipeline.atlas.graph.prune import loop_keeps
    from pipeline.common.curated import CURATED
    b = SimpleNamespace(splits=None, _mined=None)
    ex, files, sets = AB.loop_keep_inputs(b, None)
    assert files.get("a line owner") == CURATED.waters.line_owners
    mini = Path(__file__).parent / "fixtures" / "mini" / "curated" / "waters" / "loop_exemptions.json"
    keeps = loop_keeps(mini, {"a line owner": files["a line owner"]}, {})
    assert keeps["360222216"] == ["a line owner"] and keeps["360222215"] == ["a line owner"]


# ---- (review M1) A STREAM IS NOT A TRIBUTARY OF ITSELF: the assigned line's old water is never its new water's tributary

def _assigned_world():
    """The worst case for the walk: the braid B (assigned to the Kitsumkalum) is drawn at the SKEENA's order (7) and
    carries the Skeena's code, so neither the parent rule (its code is one of the reach's) nor the order guard (not
    bigger) would stop a climb into the Skeena. Flow: the Skeena above (SU) splits into the braid at its top and its
    main line (SM); the Kitsumkalum (K, order 5) and a creek (C, the Skeena's code extended) join the braid; a Skeena
    creek (ST) joins the Skeena above; a Kitsumkalum creek (KT) joins the Kitsumkalum.

        ST:0 -> SU:0 -> B:0 -> SM:0          K:0 -> B:0        C:0 -> B:0        KT:0 -> K:0
                SU:0 ------------> SM:0
    """
    import dataclasses
    from pipeline.tests.test_reach_tributaries import _g, _w
    mark = (NameTuple("Kitsumkalum River", NameSource.gazette, gnis_id=KI, note=f"{N.LINE_OWNER_NOTE}; x"),)
    nodes = [_w("SU:0", order=7, wsc=WSC_SK), _w("SM:0", order=7, wsc=WSC_SK),
             dataclasses.replace(_w("B:0", order=7, wsc=WSC_SK), name_tuples=mark),
             _w("K:0", order=5, wsc=WSC_KI), _w("KT:0", order=1, wsc=WSC_KI + "-111111"),
             _w("C:0", order=1, wsc=WSC_SK + "-100000"), _w("ST:0", order=2, wsc=WSC_SK + "-200000")]
    edges = [("ST:0", "SU:0", "confluence"), ("SU:0", "B:0", "confluence"), ("SU:0", "SM:0", "continuation"),
             ("B:0", "SM:0", "confluence"), ("K:0", "B:0", "confluence"), ("C:0", "B:0", "confluence"),
             ("KT:0", "K:0", "confluence")]
    return _g(nodes, edges)


def test_the_new_waters_walk_never_climbs_its_assigned_lines_old_water():
    """The Kitsumkalum's walk (its line and the braid) takes its creek and the creek on the braid, never the Skeena
    above the braid or the Skeena's creek, though the braid is at the Skeena's order. The Skeena's own walk is as
    before: the braid and all that joins it are its tributaries."""
    from pipeline.atlas.graph import tributaries as T
    g = _assigned_world()
    assert N.is_assigned_line(g.nodes["B:0"]) and not N.is_assigned_line(g.nodes["SU:0"])
    assert T.tributaries_of_reach(g, {"K:0", "B:0"}) == {"KT:0", "C:0"}
    assert T._reach_codes(g, {"K:0", "B:0"}) == frozenset({WSC_KI})         # the braid's (the Skeena's) code is not one
    assert T._refusal(g, "SU:0", "B:0", frozenset({WSC_KI})) == T.RECEIVING_RIVER
    assert T._refusal(g, "C:0", "B:0", frozenset({WSC_KI})) is None
    assert T.tributaries_of_reach(g, {"SU:0", "SM:0"}) == {"ST:0", "B:0", "K:0", "KT:0", "C:0"}


def test_mutation_pin_without_the_policy_the_kitsumkalum_climbs_the_skeena(monkeypatch):
    """MUTATION (`AN_ASSIGNED_LINE_NEVER_LEADS_INTO_ITS_OLD_WATER` off): the braid's code is the reach's again and the
    order guard does not stop a same-order step, so the Kitsumkalum's walk takes the Skeena above and its creek."""
    from pipeline.atlas.graph import tributaries as T
    monkeypatch.setattr(T, "AN_ASSIGNED_LINE_NEVER_LEADS_INTO_ITS_OLD_WATER", False)
    assert T.tributaries_of_reach(_assigned_world(), {"K:0", "B:0"}) >= {"SU:0", "ST:0"}


def test_the_reach_gate_refuses_the_old_water_as_a_tributary_by_name():
    """(review M1 b) `reach.build.line_owner_gate`: a binding of an entry matching the new water whose tributary
    sections hold the old water (any piece of the assigned line's code outside the new water's item), or a DFO place
    of the new water with such a section, stops the reach run by name; the sound case passes."""
    from types import SimpleNamespace as NS
    from pipeline.atlas.reach.build import LineOwnerGateError, line_owner_gate
    g = _assigned_world()
    reg = {f"gnis:{KI}": NS(section_ids=("K:0", "B:0"), name="Kitsumkalum River")}
    ents = {"r6:kit": {"matched": [f"gnis:{KI}"]}, "r6:sk": {"matched": [f"gnis:{SK}"]}}
    ok = [NS(entry_id="r6:kit", rule_id="kit.r5", via_tributary=("KT:0", "C:0")),
          NS(entry_id="r6:sk", rule_id="sk.r1", via_tributary=("SU:0", "B:0", "K:0"))]    # the Skeena's own: fine
    line_owner_gate(g, reg, ents, ok, [{"location_id": "6:kitsumkalum-river:whole", "sections": ["K:0", "B:0"]},
                                       {"location_id": "6:skeena-river:whole", "sections": ["SU:0", "K:0"]}])
    bad = ok + [NS(entry_id="r6:kit", rule_id="kit.r2", via_tributary=("KT:0", "SU:0"))]
    with pytest.raises(LineOwnerGateError, match=r"r6:kit kit\.r2: 1 section\(s\) of gnis:3942's .*SU:0"):
        line_owner_gate(g, reg, ents, bad)
    with pytest.raises(LineOwnerGateError, match=r"dfo 6:kitsumkalum-river:whole: 1 section.*SM:0"):
        line_owner_gate(g, reg, ents, ok, [{"location_id": "6:kitsumkalum-river:whole", "sections": ["K:0", "SM:0"]}])
    with pytest.raises(LineOwnerGateError, match="has assigned lines but no registry item"):
        line_owner_gate(g, {}, ents, ok)


@pytest.mark.needs_bundle
def test_no_skeena_section_takes_a_kitsumkalum_row_or_place(request):
    """(review M1 c) on the bundle under test: no section of the Skeena River (gnis:2936) carries a Kitsumkalum River
    row (r6:kitsumkalum_kalum_river) or lists a DFO place of the Kitsumkalum River, while the Kitsumkalum's own sections
    carry both (so the queries see what they look for)."""
    import sqlite3
    from pipeline.deliver import salmon as SAL
    from pipeline.tests import under_test as U
    db = sqlite3.connect(str(U.bundle(request)))
    try:
        def of(item):
            sids = {s for (s,) in db.execute("SELECT s.sid FROM item i JOIN item_section s ON i.ord = s.ord "
                                             "WHERE i.item_id = ?", (item,))}
            assert sids, f"{item} has no sections in this bundle"
            rows = {e for (e,) in db.execute(
                "SELECT DISTINCT rs.entry_id FROM item i JOIN item_section s ON i.ord = s.ord JOIN section_ruleset sr "
                "ON sr.sid = s.sid JOIN ruleset rs ON rs.set_id = sr.set_id WHERE i.item_id = ?", (item,))}
            places = {l for s, c in secs if s in sids for l in payload["chains"][c]["l"]}
            return ({e for e in rows if e.startswith("r6:kitsumkalum_kalum_river")},
                    {l for l in places if (payload["p"].get(l) or {}).get("water") == "Kitsumkalum River"})
        payload, secs = SAL.read_bundle(db)
        sk_rows, sk_places = of(f"gnis:{SK}")
        ki_rows, ki_places = of(f"gnis:{KI}")
        assert ki_rows and ki_places
        assert (sk_rows, sk_places) == (set(), set())
    finally:
        db.close()
