# T1277 — Side channels beside a river in an uncut park do not take the park's rule (Strathcona: five rivers show two parts)

Status: OPEN — a future release, not 0.10.0; owner: see ## Owner

| id | title | status | commits | what's left |
|---|---|---|---|---|
| T1277 | Side channels beside a river in an uncut park do not take the park's rule (Strathcona: five rivers show two parts) | OPEN — future release | — | owner picks A (channels take the rule) or stay, and Westmin yes/no; nothing built |

Source: finish-up chat (T1240 lane), 2026-11-28, and the owner's rulings of that morning (below). Write-up:
`night-notes-2026-11-28-finish-up/T1240/STRATHCONA-NONCUT.md`; picture: `T1277-shots/STRATHCONA-noncut-burman.png`.
Related: T1240, T1199, T1149.

## What anglers see

Provincial parks are `cut: false`: a park rule binds every whole section that touches the park. Strathcona's only
rule is Region 1 "No powered boats on any water within Strathcona Park except Gold, Upper Campbell and Buttle lakes".
It never opens or closes fishing. 349 stream sections straddle the park edge, so 448.7 km outside the park carry the
rule.

Burman, Bedwell, Rees, Comox and Thelwood each show two parts (the river, and "N side channels") with "Other parts of
this water have different rules". The only difference is the boat line: the river's straddling main-line section is in
the park, its side channels lie outside the polygon and are not.

## Measured (finish-up chat, on main of 2026-11-28)

The channel km are INFERRED from the bundle's touches, not from a build: there is no flow direction, so a loop and a
dead-end spur are not told apart; a true count needs graph.pkl. Baseline was main plus the T1199 fix (release
r-5e5e0369ce6d), per the write-up. No figure in the brief contradicted the write-up.

- Proposal looked at and NOT built: a channel that leaves and rejoins its river takes the park of the river pieces it
  touches (extend `border.A_CHANNEL_TAKES_ITS_RIVERS_UNITS` to uncut areas). Strathcona: 18 channel groups, 12.16 km
  (Burman 4.96, Bedwell 3.28, Ash 1.31, Thelwood 0.94, Rees 0.76, Salmon 0.71, Comox 0.21). All five rivers fold only
  if short dead-end spurs count too (Bedwell 341 m, Thelwood 197 m); loops only would leave Bedwell and Thelwood split.
- Made general for every uncut area: 2,141.7 km in 302 areas; only three change an answer:
  - Strathcona Park, 12.16 km: "no powered boats" (a restriction).
  - Bowron Lake Park, Cariboo River 0.42 km: stricter (trout/char 1, bait ban, single barbless hook, no powered boats).
  - Creston Valley WMA, Goat River 8.45 km: a LOOSENING ("bass and yellow perch, no limit"; lifts Region 4's bass
    limits there). The T1149 Creston problem in a new place; see T1149.
  - No "No Fishing" closure is gained anywhere.
- Strathcona-Westmin: the owner earlier said "Yes, treat it as Strathcona Park". Not on main. It would add the rule to
  32 lakes (Arnica + 31 unnamed, Buttle excepted) and 53 creek sections (4.71 km whole length), needs only the rule's
  second extent in region-1.json (independent of areas.json), and would fold Thelwood.
- A clean cut at the park edge was built on the unmerged branch `fix/T1240-strathcona-clean-cut` and dropped.

## Owner rulings, 2026-11-28 morning, verbatim, in order

Shown three options (A: uncut + channels take the rule; B: leave as today; C: cut at the edge): "Okay A works", then
"Or actually B", then "Leave it how it is". Told that B keeps the two-part look on the five rivers and that Westmin was
open: "Add as a future ticket to look into on a future release and leave as is".

Planning chat's reading (a reading, not his words): nothing changes in 0.10.0, Westmin included.

## Work

1. Decide A or stay (owner). If A: extend the channel rule to uncut areas, loops and short spurs both (the five rivers
   need the spurs), and gate it so the Creston Goat River loosening (8.45 km) is not gained without his yes.
2. Decide Westmin yes/no (owner). If yes: add the second `within` extent to the rule in region-1.json.
3. Re-measure from a build (graph.pkl) before building; the 12.16 km is inferred.

## Acceptance

The five rivers show one part each, or the owner has said stay. No area closure or loosening changes without his
yes. Pins on the Strathcona rule, the Bowron and Creston answers.

Depends: T1240, T1199, T1149. Size: M. Owner: yes (A or stay; Westmin yes/no). Default: leave as is (B), Westmin
not added.

## Owner

- [ ] 2026-11-28 — When this ticket is picked up: decide A (uncut park, channels take the rule) or stay as is, and
  decide Strathcona-Westmin yes/no. Default we build with: stay as is, no Westmin.
