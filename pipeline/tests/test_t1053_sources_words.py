"""T1053 part 1 (PROPOSAL, the owner's wording pick is open): a rule that reaches its water's tributaries says so on its
`applies` line, whole string — its own `includes_tributaries`, else its row's (AGENTS 9: three-valued), or
`tributaries_only`. Eagle Creek's sheet said only "This water's own row …: Eagle Creek." (report 3eaf5ac25fc39d73)."""

from __future__ import annotations

import pytest

from pipeline.deliver.answers.display.decided import BOOK_TITLE, applies_here, covers_tributaries

EAGLE = {"kind": "water", "name": "Eagle Creek", "symbols": ["Incl. Tribs"], "includes_tributaries": True,
         "pages": [23]}


def _rule(**fields):
    return {"id": "r2:eagle_creek@2-8::eagle_creek.r1", "entry_id": "r2:eagle_creek@2-8",
            "provenance": {"rank": 1}, "fields": {"extents": [{"op": "whole"}], **fields}}


def _doc(entry):
    return {"entries": {"r2:eagle_creek@2-8": entry}, "rules": {}, "waters": {}}


def test_eagle_creeks_own_sheet_says_it_covers_its_tributary_streams():
    say, trib = applies_here(_rule(), _doc(EAGLE))
    assert say == (f"This water’s own row in the {BOOK_TITLE}: Eagle Creek. "
                   "Covers Eagle Creek and its tributary streams (✱, p.4).")
    assert trib == "Inherited from Eagle Creek: its row covers its tributaries."


def test_the_rules_own_false_beats_the_rows_true():
    """AGENTS 9: a rule's own flag wins over its row's; false here means its water alone."""
    say, _ = applies_here(_rule(includes_tributaries=False), _doc(EAGLE))
    assert say == f"This water’s own row in the {BOOK_TITLE}: Eagle Creek."


def test_a_rules_own_true_on_a_row_that_says_nothing():
    row = {**EAGLE, "symbols": [], "includes_tributaries": None}
    assert covers_tributaries(_rule(includes_tributaries=True), row, "Eagle Creek") == \
        "Covers Eagle Creek and its tributary streams."      # no ✱ printed on the row: no key cited


def test_a_row_without_the_flag_says_nothing():
    row = {k: v for k, v in EAGLE.items() if k not in ("includes_tributaries", "symbols")}
    assert covers_tributaries(_rule(), row, "Eagle Creek") is None


def test_a_stretch_says_the_streams_joining_that_part():
    x = _rule(extents=[{"op": "downstream_of", "splits": ["x"]}])
    assert covers_tributaries(x, EAGLE, "Eagle Creek") == \
        "Covers the part of Eagle Creek it names and the tributary streams joining that part (✱, p.4)."


@pytest.mark.parametrize("extents, words", [
    ([{"op": "whole"}], "Covers only the tributary streams, not Eagle Creek itself (✱, p.4)."),
    ([{"op": "upstream_of", "splits": ["x"]}],
     "Covers only the tributary streams of the part it names, not Eagle Creek itself (✱, p.4)."),
])
def test_tributaries_only_says_not_the_water_itself(extents, words):
    assert covers_tributaries(_rule(tributaries_only=True, extents=extents), {**EAGLE, "includes_tributaries": None},
                              "Eagle Creek") == words


def test_an_undrawn_part_never_walks_and_says_nothing():
    """RULINGS T10: a rule held as a note on an undrawn part does not walk its row's tributaries."""
    assert covers_tributaries(_rule(undrawn_part="500 m below the dam"), EAGLE, "Eagle Creek") is None


# ---------------------------------------------------------------------------------------------
# T1273: a rule's OWN "no tributaries" must reach the words. The function above was right; the data never carried the
# false (the bundle's `rule.conditions` dropped every false flag), so 19 rules under a ✱ row said "Covers … and its
# tributary streams", 4 of them lifts, permissions or keeps (Mitchell r3x, Fulton r3, Bella Coola r5, r6). These go
# THROUGH the bundle row and the export record, as the answers read a rule.
# ---------------------------------------------------------------------------------------------
GOAT_ROW = {"kind": "water", "name": "Goat River", "symbols": ["Incl. Tribs"], "includes_tributaries": True,
            "pages": [39]}


def _through_bundle_and_export(entry_id: str, raw: dict) -> dict:
    """catalogue rule -> bundle `rule` row (`bundle.rules._rule_row`) -> export record (`export.read._rule_record`)."""
    import re
    from pathlib import Path
    import pipeline.deliver.bundle.rules as rules_mod
    from pipeline.deliver.bundle.rules import _rule_row
    from pipeline.deliver.export.read import _rule_record
    src = Path(rules_mod.tables.__file__).read_text()
    cols = [c.strip() for c in re.sub(r'"\s*"', "", re.search(r'INSERT INTO rule \((.*?)\)\s*"\s*"VALUES', src,
                                                              re.S).group(1)).split(",")]
    row = dict(zip(cols, _rule_row(entry_id, raw, uncertain=False)))
    return _rule_record(row, "Goat River")


def _applies(raw: dict, entry_id: str = "r4:goat_river@4-6", row: dict = GOAT_ROW) -> str:
    x = _through_bundle_and_export(entry_id, raw)
    return applies_here(x, {"entries": {entry_id: row}, "rules": {}, "waters": {}})[0]


def test_t1273_a_loosening_rule_whose_own_line_has_no_tributaries_says_nothing_of_them():
    """Bella Coola r5's shape: a keep on the mainstem only (its own `includes_tributaries: false`) under a ✱ row.
    MUTATION: `row.py` drops the false flag again -> the sentence "Covers Goat River and its tributary streams" is back."""
    keep = {"rule_id": "goat_river.r9", "type": "retention_limit", "species": ["RB"], "take": 2,
            "verbatim": "on the MAINSTEM ONLY, trout daily quota = 2", "extents": [{"op": "whole"}],
            "includes_tributaries": False}
    assert _through_bundle_and_export("r4:goat_river@4-6", keep)["fields"]["includes_tributaries"] is False
    assert _applies(keep) == f"This water’s own row in the {BOOK_TITLE}: Goat River."


def test_t1273_a_tightening_rule_whose_own_line_has_no_tributaries_says_nothing_of_them():
    """Goat River r1: "Trout/char catch and release (mainstem only)"."""
    release = {"rule_id": "goat_river.r1", "type": "retention_limit", "species": ["RB"], "take": 0,
               "may_target": True, "verbatim": "Trout/char catch and release (mainstem only)",
               "extents": [{"op": "whole"}], "includes_tributaries": False}
    assert _applies(release) == f"This water’s own row in the {BOOK_TITLE}: Goat River."


def test_t1273_a_rule_that_inherits_the_rows_star_still_covers_its_tributaries():
    """Unchanged: a rule with no flag of its own under a ✱ row covers the river and its tributary streams, and the
    bundle row carries no flag for it (absent = inherit, AGENTS 9)."""
    ban = {"rule_id": "goat_river.r2", "type": "retention_limit", "species": ["RB"], "take": 1,
           "verbatim": "Trout daily quota = 1", "extents": [{"op": "whole"}]}
    assert "includes_tributaries" not in _through_bundle_and_export("r4:goat_river@4-6", ban)["fields"]
    assert _applies(ban) == (f"This water’s own row in the {BOOK_TITLE}: Goat River. "
                             "Covers Goat River and its tributary streams (✱, p.4).")
