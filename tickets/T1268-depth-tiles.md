# T1268 — Depth: the placed depth lines and the tiles' depth_contour layer

Status: IN PROGRESS — depth data lane of the 0.10.0 finish-up chat (branch feat/T1268-depth-tiles, stacked on T1267).

| id | title | status | commits | what's left |
|---|---|---|---|---|
| T1268 | Depth: the placed depth lines and the tiles' depth_contour layer | IN PROGRESS | — | code + tests on the branch; the side tiles build on the baseline atlas (size, parity, pictures); second review, before_pr, PR after T1267 |

Source: owner 2026-11-28, "we want the vector maps in for it" (0.10.0). Parent T201; the frozen placings are T1267; the
app's look, labels and key are T1269, the credit T1270. Plan: planning notes `T1188/DEPTH-IN-0100-SCOPE.md` W3 + W4.
Contract with the app lane: the depth lane's `CONTRACT.md` (night notes 2026-11-28 finish-up).

## Work
1. **W3** `pipeline/bathymetry/placed_contours.py`, the one producer: for each frozen placing only, the zip
   (hash-checked) -> depth arcs -> metres -> the frozen pose (his adjustment already composed) -> cut at each of the
   row's lakes' FWA shoreline (a two-lake sheet's pieces go to the lake they lie in) -> pieces under `MIN_PIECE_M`
   dropped -> sorted output under `GENERATED.bathymetry/placed/`: `contours.geojsonl`, `lake_facts.json` (per lake:
   deepest line, draft year, sheet, units + evidence; for T1269's lake card), `report.json` (inputs, clip shares,
   every lake over `CLIP_REPORT_PCT`, the size gate `MAX_VERTICES`).
2. **W4** the tiles read it: the layer `contour` is RETIRED and `depth_contour` declared (a new name, so 0.9.0 apps,
   whose style names `contour`, draw no depth lines with no numbers and no credit); `export_contours` reads only the
   placed lines and RAISES when the frozen file has rows and they are missing or made from other inputs (it used to
   skip a missing gpkg layer in silence); the tiles stage key gains the frozen placings (by content) and the zips'
   hash list; a size line per layer; a fast-fail `data:` step. The app style's existing depth layer is re-pointed to
   `depth_contour` here (minimal), so each PR is green in the merge order T1267 -> T1268 -> T1269 -> T1270.
3. The release slot: no new artifact and no manifest change (the lines ride inside the atlas); measured on one side
   tiles build (size before / after, parity of every other layer, pictures of five lakes).

## Defaults (named constants, flippable)
- `MIN_PIECE_M = 15` (a piece shorter than this after the shoreline cut is dropped).
- D7 `CLIP_REPORT_PCT = 5`: cut at the shoreline, list every lake over 5 % clipped.
- `MAX_VERTICES = 4,000,000` (the size gate; the producer refuses above it).
- Zoom ladder per sheet (`ladder.sheet_ladder`; the planning chat's pick "A", 2026-11-28, from B / A picture sheets):
  from the sheet's own levels in its native unit, the smallest nice step (1, 2, 5 x 10^k) leaving `INDEX_LINES_MIN` 2
  to `INDEX_LINES_MAX` 4 index lines (z11); the next finer nice step at z12 only when it adds at most
  `MIDDLE_LINES_FACTOR` 3 x the index lines; the rest z13; one level = its index. Over the 322 frozen lakes: every lake
  has 1-4 index lines (1: 92, 2: 95, 3: 65, 4: 70); pieces z11 / z12 / z13 37,992 / 39,702 / 94,187.

## Acceptance
`pipeline/tests/test_bathymetry_t1268.py` (synthetic sheets: pose, feet, clip, split, adjust, stubs, determinism,
staleness, the export's raise and its layer), the key tests, `app/tools/tile-contract.test.ts` and the style golden;
the side build's numbers and pictures in the lane report.
Depends: T1267. Size: M. Owner: no new ask.
