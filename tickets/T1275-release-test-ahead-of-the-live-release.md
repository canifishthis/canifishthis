# T1275 — A release test that is ahead of the live release fails the local gate

Status: OPEN.

| id | title | status | commits | what's left |
|---|---|---|---|---|
| T1275 | A release test that is ahead of the live release fails the local gate | OPEN | — | a release-backed test names the release it expects, or skips with a printed reason when the release is older |

Source: a lane's run, 2026-11-28 (not reproduced here; the app suite was not re-run for this ticket).

## What
`app/tools/seo/t1140.release.test.ts`, block "(T1140) a part of a water of several is named, never numbered", fails on
any machine whose local live release is r-0aec88ed3edb (0.9.0, cut 2026-11-24): the same two failures on a clean
origin/main worktree holding that release. In CI and in a worktree with no local release the tests skip.
- Line 53, "the Squamish and the Gordon: their side channels named by the area they lie inside": expected "Squamish
  River inside Baynes Island Ecological Reserve" / "Inside Baynes Island Ecological Reserve" / the same / "Other parts
  of this water have different rules"; received "2 side channels, joining 11.6 km from the mouth" (twice), undefined,
  "Other parts of this water have different rules".
- Line 116, "the prerendered pages": expected [ 'gnis:25671', true, true, false ], received [ 'gnis:25671', false, true,
  false ] (the Squamish page body lacks "Inside Baynes Island Ecological Reserve").
- Cause: da141d1cf `fix(T1140): under the water's name a part named "<water> <words>" is shown by its words`
  (2026-11-25), after 82e6de1f4, both after the release was cut. The test is ahead of the release it reads.
- Effect: `scripts/before_pr.sh` fails its app suite in any checkout holding the live release (the main checkout does)
  until a release cut from current main exists; the 0.10.0 re-cut chat will meet it. It closes itself for T1140's case
  once the 0.10.0 release is the local release; the general hole stays.

## Work
Propose, do not build here. A release-backed test must either name the release it expects (a pin, like the other
release-backed pins) or skip with a plain printed reason when the local release predates the change it tests. It never
fails on a release that is merely older, and never passes silently.
1. Fit: `liveReleaseAt` (`app/conformance/src/fixtureRelease.ts:90`) already skips with a reason, never falls back to an
   older folder, and refuses a release whose section versions differ from `KNOWN_VERSIONS`; the T1140 file prints that
   reason (`t1140.release.test.ts:24`). Add the same kind of refusal for "older than the change": a test states the
   release (or deliver change) it needs, `liveReleaseAt` takes it, and the skip reason says which release it wants and
   which it found. `REGS_STORE_REQUIRED=1` stays a throw.
2. Apply it to `t1140.release.test.ts`, then look for other `*.release.test.ts` expectations changed after the live
   release was cut.

## Acceptance
On a checkout holding r-0aec88ed3edb the T1140 tests skip with the printed reason and `scripts/before_pr.sh` passes its
app suite; on a release that has the change they run and pass; a test that needs a newer release than the one it finds
cannot go green by skipping under `REGS_STORE_REQUIRED=1`.

Depends: none. Size: S. Owner: no. Default: n/a.
