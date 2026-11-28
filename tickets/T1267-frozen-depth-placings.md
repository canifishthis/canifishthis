# T1267 — Depth: the vector zips into SOURCE, hash-checked; the frozen accepted placings file

Status: IN PROGRESS — depth data lane of the 0.10.0 finish-up chat (branch feat/T1267-frozen-depth-placings); the freeze waits for v5 on main.

| id | title | status | commits | what's left |
|---|---|---|---|---|
| T1267 | Depth: the vector zips into SOURCE, hash-checked; the frozen accepted placings file | IN PROGRESS | — | code + tests + units read on the branch; second review, before_pr, PR; then the freeze from the v5 refit.json once v5 is on main (the planning chat says when) |

Source: owner 2026-11-28, "we want the vector maps in for it" (0.10.0); his rule: nothing of a lake's depth ships without
its placing in the frozen curated file. Which placings, his words: "every high one plus all the ones i review. in the
end it should be all of them" and "Ship them with the high ones". Parent T201 (the order, the licence); the fitter is
T1188 (its v5 run is the run of record). Plan: planning notes `T1188/DEPTH-IN-0100-SCOPE.md` W1 + W2. The tiles side is
T1268; the lake card facts and `lakes/1` are T1269.

## Work
1. **W2, the zips as a source.** `SOURCE.bathymetry_vectors` (git-ignored like `bathymetry_pdfs/`), the committed
   sha256 list `data/source/bathymetry_vectors.sha256.json` (510 zips), `fetch_vectors` writing there and checking
   (`--check`, `--write-hashes` for a deliberate new fetch), and the ONE reader `pipeline/bathymetry/vectors.py`
   (`zip_path`): raises on a missing folder, a missing or unlisted zip, or a different hash, naming the file and the
   command. 510 zips for 512 sheets: 00153501 and 00153701 each hold a second line coverage repeating the first.
2. **W1, the frozen file.** `CURATED.bathymetry.placings` (`bathy-placings/1`), one writer
   `python -m pipeline.bathymetry.placings --freeze` through `curated_write`; accepted = the run of record's `high` +
   `high_stretched`, plus every chart marked `right` / `right_adjusted`; never one marked wrong_lake / wrong_fit /
   unsure. A marked row takes the pose the review page SHOWED (its run, kept in the row), plus his adjustment exactly
   as saved (`compose`: the page's own maths, `review-page/v3/script.js` `mapM`), proved by recomputing the overlap the
   mark saved (`OVERLAP_TOLERANCE`); the run of record's pose for it is reported, never applied. Every `--page` states
   its window (from, until or "still showing at" a time the marks export may not pass; or the export's `poses_shown`);
   a mark saved in no window is refused, named. An accepted row is never rewritten; a rerun reports what it would
   change. A row is WITHDRAWN (kept as a record, out of the shipping view `placings.shipping()`) by his later wrong /
   unsure mark or by a newer survey of its lake accepted later; only his later `right` brings it back, as a new row.
3. **Units (D2).** `CURATED.bathymetry.sheet_units` (`bathy-sheet-units/1`): the 63 trusted sheets whose vector file
   states no unit, read off their printed charts (title block "DEPTHS IN ..." 7, the statistics block's MAX. / MEAN
   DEPTH with its unit 55, the contour labels' foot marks 1): 53 feet, 10 metres. Each row keeps the words, where, the
   page and the vector file's deepest contour (it sits at or under the stated maximum on all 63).

## Defaults (each a named constant in `pipeline/bathymetry/placings.py`, flippable)
- D1 `ACCEPT_CLASSES` = high, high_stretched; `ACCEPT_MARKS` = right, right_adjusted; `NEVER_MARKS` = wrong_lake,
  wrong_fit, unsure (the owner's words, 2026-11-28).
- D2 `UNITS_UNSTATED = "read"`: a sheet with no stated unit ships only with its printed chart's words ("hold": never;
  "feet": without reading).
- `NO_DATA_DEPTHS = (999,)`: Albert Head Lagoon (00019301) carries 14 arcs at 999 beside its 1 m line where the chart
  prints 0.5 and 1.5 m lines; the arcs cannot prove a no-data code, so the sheet is held out.
- D9 `SURVEYS_PER_LAKE = "newest"`: Murphy Lake keeps 1987 (00191301), drops 1971 (00191501); Carp Lake keeps 1977
  (00287001), drops 1971 (00287101).
- Held out, for the owner: a lake with no single registry item. Today 5 charts, named on the chart but with no FWA
  name, hence no registry item: Beaver 00020301 (high_stretched), Robinson 00163001, Sawmill 00205501, Summit
  00235601, Campbell 00305501 (high).

## Acceptance
`pipeline/tests/test_bathymetry_t1267.py` (synthetic: the hash guard, the page's maths on a synthetic page, the
policy, never-rewrite, the mutation pins); the curated-path pins; the dry-run freeze numbers in the lane report;
Abruzzi's saved overlap 0.88 reproduced from the v2 pose + his adjustment (0.8795).
Depends: T1188 v5 on main (for the freeze only). Size: M. Owner: no new ask (the defaults above are the planning
chat's to put to him).
