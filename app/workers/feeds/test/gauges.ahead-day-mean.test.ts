// T1278: `ahead[N]` (the per-day forecast percentile) ranks the Centre day's MEAN, the same value as `aheadDays[N-1]`,
// never the one hourly step nearest the run's clock hour (which flipped a rain-pulse water's days: .95 .05 .95).
// The fixture is the real recording: Elk River above Campbell Lake (08HD018), the Centre's CLEVER (hourly) and COFFEE
// (daily) CSVs of 2026-11-27, the station's discharge record bands, the reading of 2026-11-28 (22.5 m3/s).
import { describe, expect, it } from "vitest";
import { forecastDays } from "../src/gauges/change";
import { parseSeries } from "../src/gauges/forecast";
import { bandFor, forecastPercentiles, percentileOf } from "../src/gauges/publish";
import { addDays, dayMs } from "../src/gauges/time";
import fx from "./fixtures/t1278-elk-08HD018.json";

const runs = () => Object.fromEntries(Object.entries(fx.runs).map(([m, r]) => [m, { model: m, issuedAt: r.issuedAt, series: parseSeries(r.csv, m)! }]));
const BANDS = { discharge: fx.discharge } as Record<string, any>;
const OBS = { discharge: fx.observed, level: null };
const at0805 = Date.parse("2026-11-28T08:05:00Z");   // 00:05 on the Centre's clock
const at1505 = Date.parse("2026-11-28T15:05:00Z");   // 07:05 on the Centre's clock
const dis = (a: Record<string, any>, from = 1, to = 8) => Array.from({ length: to - from + 1 }, (_, i) => Math.round(a[String(from + i)].discharge * 100) / 100);

describe("T1278: a forecast day is ranked from its mean", () => {
  it("Elk above Campbell Lake, days 5-7 read .63 .78 .77 (the days' means), not .95 .05 .95 (one hour's step)", () => {
    const a = forecastPercentiles(runs(), BANDS, at0805, OBS);
    expect(dis(a, 5, 7)).toEqual([0.63, 0.78, 0.77]);
    expect(dis(a, 1, 8)).toEqual([0.14, 0.73, 0.57, 0.62, 0.63, 0.78, 0.77, 0.51]);
  });

  it("`ahead[N]` is `aheadDays[N-1]`: one function, every day", () => {
    const rank = (v: number, d: string) => percentileOf(v, bandFor(BANDS.discharge, dayMs(d)! + 12 * 3600_000));
    const days = forecastDays(runs(), at0805, fx.observed, rank)!;
    const a = forecastPercentiles(runs(), BANDS, at0805, OBS);
    for (let n = 1; n <= 10; n++) {
      const d = days.discharge[n - 1];
      if (d === null) expect(a[String(n)]).toBeUndefined();
      else {
        expect(a[String(n)].discharge).toBeCloseTo(d, 4);
        expect(a[String(n)].model).toBe(days.model[n - 1]);
      }
    }
  });

  it("the result does not depend on the run's clock hour (00:05 and 07:05 on the Centre's day)", () => {
    expect(addDays("2026-11-28", 1)).toBe("2026-11-29");
    expect(forecastPercentiles(runs(), BANDS, at1505, OBS)).toEqual(forecastPercentiles(runs(), BANDS, at0805, OBS));
  });
});
