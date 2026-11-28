# T1273 — 19 rules say "Covers X and its tributary streams" though their own line has no tributaries

Status: OPEN.

| id | title | status | commits | what's left |
|---|---|---|---|---|
| T1273 | 19 rules say "Covers X and its tributary streams" though their own line has no tributaries | OPEN | — | owner: 0.10.0 or after (## Owner); then the export carries a rule's own false flag, re-cut, pins |

Source: lane T679-#12, 2026-11-28 (found while making the bundle carry each rule's tributary scope); measured on the
baseline side build r-5e5e0369ce6d (origin/main a18c6168b + the T1199 fix).

## What is wrong
A rule whose OWN `includes_tributaries` is `false`, under a row that includes tributaries (✱), gets the T1053 sentence
on its `applies` line as if it walked: Goat River r1 "Trout/char catch and release (mainstem only)" reads "Covers the
part of Goat River it names and the tributary streams joining that part (✱, p.4)."; Alouette River r3 "no powered
boats on mainstem" reads "Covers Alouette River and its tributary streams (✱, p.4).". 19 rules, 10 waters (Regions 1,
2, 4, 5, 6): Tlell r5; White r1; Alouette r3; Hatzic Lake r2, r3; Nicomekl r5; Pitt r4; Findlay Creek r1; Goat r1;
Skookumchuck Creek r1; Bella Coola r5, r6, r7, r8, r11; Mitchell r3x; Fulton r3; Kitimat r1, r2. Every card line, as
today and after, is in the night notes `night-notes-2026-11-28-finish-up/T1273/` (CSV + PNG), read from the
baseline's answers (`sections.display.rules[ix].applies`), not guessed. Two more (Pitt r2, Powell Lake r2) are
undrawn-part notes and already say nothing.

## Where the words are made, and why only the words are wrong
- The sentence: `pipeline/deliver/answers/display/decided.py::covers_tributaries`, called by `applies_here`. It reads
  the rule's own flag from the export's `fields.includes_tributaries`, else its row's (AGENTS 9). The function is
  right: `test_t1053_sources_words.py::test_the_rules_own_false_beats_the_rows_true` passes because it HANDS it `false`.
- The data never carries the false: `pipeline/deliver/bundle/rules/row.py::_rule_row` builds `rule.conditions`
  without any false value ("No flag in the model means something when False, so False is dropped"). The export's
  `fields` come from `conditions` (`export/read.py::_rule_record`), so a rule's own "no" arrives as "unset" and
  inherits the row's yes.
- The walk is right: the reach reads the curated rule (`reach.classify.wants_tributaries`, three-valued). On the
  baseline bundle the 19 rules have 0 `ruleset` rows with `via = 'trib'`; the Goat row's other rules do walk. No
  section's answer, colour or open/closed changes; only this sentence.

## Work (the fix as seen; nothing built)
1. Make the export carry a rule's own `includes_tributaries: false`. Either (a) `row.py` keeps `false` for that one
   flag in `conditions` (it is three-valued, AGENTS 9), or (b) once T679 #12 is merged, `export/read.py` takes it from
   the bundle's `rule_tributary` table. (a) is one Python line and reaches every reader of `conditions` the same way;
   (b) keeps `conditions` as it is. Either way the export's `fields` gain `includes_tributaries: false` on the rules
   whose own flag is false (43 in the corpus); check the codec (AGENTS 58) takes a false value for that key.
2. Rebuild the export and answers. Expected diff: the 19 `applies` strings lose their "Covers …" sentence and
   nothing else (answers_diff: "wording only"). Re-cut the mini release (`python -m pipeline.tools.mini_release
   --write`) and the app fixtures if any holds one of the 19 rules (`node app/tools/regs-recut/sync.mjs`).
3. Pins: in `test_t1053_sources_words.py`, a test that goes THROUGH the bundle row and the export record (a rule with
   own `false` under a ✱ row has `fields.includes_tributaries is False` and no "Covers" sentence; MUTATION: drop the
   flag in `row.py` → red), and a built-data test on Goat River r1 and Alouette River r3.

## Acceptance
answers_diff against the release before: exactly the 19 `applies` lines change, "wording only", no answer; the two pins
above red under their mutation; export diff = the `fields` key on the 43 rules + the 19 sentences.

Severity: low to medium. Wording only, but it can mislead toward STRICTER: a tributary of the White River's
"No fishing" part or of the Bella Coola's quota rules reads as covered when it is not. Never more open. Size: S.
Depends: none (option b depends on T679 #12). Owner: yes (when). Default: after 0.10.0.

## Owner
- [ ] 2026-11-28 — 19 rules (Goat River "catch and release, mainstem only", Alouette "no powered boats on mainstem",
  Kitimat "no fishing" by the hatchery, …) wrongly add "Covers X and its tributary streams" to the card; the map and
  the answers are right. Fix it in 0.10.0 (a small wording change, a re-cut, the 19 sentences shown before/after) or
  after 0.10.0 (Default: after)?
