# T1278 — The gauge feed's per-day forecast percentile flips from day to day (one hourly step, ranked as a daily mean)

Status: IN PROGRESS — lane fix/T1278-forecast-percentile-from-the-days-mean; second review, then before_pr and PR.

| id | title | status | commits | what's left |
|---|---|---|---|---|
| T1278 | The gauge feed's per-day forecast percentile flips from day to day (one hourly step, ranked as a daily mean) | IN PROGRESS | — | second review, before_pr, PR; the owner question below is for a later release |

Source: the T1189 feed check, 2026-11-28 (Elk River above Campbell Lake, 08HD018, days 5 to 7 read .95 .05 .95).

## The defect, in plain words
`stations[id].ahead["1".."10"]` (the per-day forecast percentile) was read from ONE hourly value, the model step nearest
now + N x 24 h, i.e. the clock hour of the day's first run, and ranked against record bands built from DAILY means. On a
coastal water with forecast rain pulses that single hour is a peak one day and a trough the next, so the percentile of
neighbouring days flips (08HD018 days 5-7: .95 .05 .95; the same days as daily means read about .62 .63 .78). 23 of 330
stations swing like this; ranking the day's mean fixes 11 of them. `aheadDays` (the strip) already ranked daily means, so
the two disagreed about the same day.

## The fix
Each day's `ahead[N]` is ranked from that day's MEAN, from the same function as `aheadDays[N-1]`: `day_picks` (python,
`change.py`) / `dayPicks` (worker, `change.ts`): Centre-day N after today (the Centre's PST wall clock), every fresh
run's daily mean (an hourly run needs DAY_COVER of its steps that day; a daily model's one step) times the gauge scale
(COFFEE onto the gauge by observed / its own today), joined by `combine_day` (CLEVER+COFFEE geometric mean). Both
publishers (python spec, TS worker) changed; the parity test pins they agree. Not changed: `aheadDays`, the hydrograph
series, the clamps, the bands, the app. A day an hourly run only half covers (its last, a morning) is now absent in
`ahead`, as it already was in `aheadDays`.

## Owner
- [ ] 2026-11-28 — For a LATER release (not built now): the genuine upstream pulses, 12 stations on days 4-10 where the Centre's CLEVER model is the only one and starts 6-8 times below the observed flow. Options: (A, recommended to decide after seeing the 12) mark such days low-confidence in the feed and the app; (B) scale CLEVER onto the gauge like COFFEE, so the day reads on the observed level; (C) leave as is (the day is the model's honest word, however odd).
