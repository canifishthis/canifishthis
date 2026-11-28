# T1266 — Web: the map ignores a first tap for about 12 s on a slow line

Status: OPEN.

| id | title | status | commits | what's left |
|---|---|---|---|---|
| T1266 | Web: the map ignores a first tap for about 12 s on a slow line | OPEN | — | find why taps made after "map usable" do nothing for ~12 s on slow 4G; then fix and pin it |

Source: found by the T737 speed lane (2026-11-28) while measuring the first tap; not a tester report (no feedback-log row: that log is for outside feedback, this was found by Claude's own measurement).

## What was measured
- Local web builds of origin/main (a18c6168b) and the T737 branch, both against release r-71d09ad82e81 served locally, Chromium via Playwright, slow 4G (1.6 Mbps down, 750 kbps up, 150 ms, CPU 4x), phone viewport 390x844, fresh profile.
- The first tap is made 3 s after "map usable" (first `map-day` control visible and the tiles quiet) on an unnamed stream (projected from a real vertex, `tools/map-tap.mjs`). With nothing else in the way (the in-season sheet closed first) it does nothing: no pointer cue, no card, no download of its own (no sql-wasm, no water slice). A tap repeated every ~4.5 s lands on the third try: about 12.0-12.1 s after the first (3 of 3 runs, both builds, identical to 0.1 s). Unthrottled, and on good 4G / wifi, the first tap lands at once (landing took 2.7 s / 1.8 s of harness waits, i.e. the first try).
- A slow tap-before-ready cannot be told from a stuck one by the reader: nothing on screen says the map is not ready (the map controls are up).

## Not known
- The cause. Candidates only: the tap handler waits for something (pairing / status paint / sql-wasm / the held pane) that finishes ~15 s after "map usable"; or the map is busy on the main thread under CPU 4x. Not the T737 start gate (same before and after).
- Whether the production site or a real phone shows it (production and devices not measured). The staging site's older app answered a tap at "usable + 3 s" in the T737 notes' runs, so it may be new in main.

## Reproduce
- Harness and raw runs (durable): ~/.claude/projects/-Users-dawson-horvath-dev-personal-BC-freshwater-fishing-regulations/night-notes-2026-11-28-finish-up/T737/ — `measure.py` (env SITE, TAG, KINDS=river, LOWDATA), `serve.mjs`, raw runs in `raw/`, `REPORT.md`; per run the first tap's `attempts` and `landed_after_ms`.
- Build: `EXPO_PUBLIC_DATA_BASE=http://localhost:39499 npx expo export --platform web --output-dir ../../dist/web-local` in app/apps/mobile, then `node ../../tools/web-shell.mjs ../../dist/web-local`; data: `RELEASE=r-71d09ad82e81 TILE_PORT=39499 node app/tools/serve-tiles.mjs` from a checkout with data/; serve the export with `node serve.mjs <dist> 8801`; `TAG=x SITE=http://127.0.0.1:8801/ KINDS=river python3 measure.py slow4g 1`.

## Work
1. Instrument when the tap handler becomes live (what it waits for) on the slow profile; find the ~12 s.
2. Fix it so the first tap lands as soon as the map is shown, or the map says it is not ready (no silent ignore).
3. A pin: a tap made at map-usable on the throttled profile reaches its answer path (smoke `--only firsttap` or the bad-net walk).

## Acceptance
Slow 4G, tap 3 s after map usable: the pointer cue / card paints on the first tap (attempts = 1), same harness; no change on good 4G / wifi.

Severity: medium (a first tap that does nothing reads as a broken app on a rural line; no wrong answer is shown). Depends: none. Size: S to M (finding it is the work). Owner: no.
