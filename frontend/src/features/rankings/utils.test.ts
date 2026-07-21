import { describe, it, expect } from "vitest"
import {
  historySpanDays, historySpanLabel, lineColor, LINE_COLORS, toScoreChartRows,
  type HistorySeriesLike,
} from "./utils"

// Real snapshot dates for Large Cap under the current RULE_ENGINE_V1 formula
// (GET /rankings/history?category=Large Cap&top_n=5) — 7 real monthly
// snapshots, 2026-02-09 through 2026-07-19 (~160 real days), confirmed live
// during the ranking-formula-unification + history-graph sessions.
const REAL_LARGE_CAP_DATES = [
  "2026-02-09", "2026-03-09", "2026-04-09", "2026-05-09",
  "2026-06-09", "2026-07-09", "2026-07-19",
]

// Real single-snapshot category (Index Funds only exists under the new
// taxonomy naming, introduced 2026-07-19 — genuinely zero prior history).
const REAL_INDEX_FUNDS_DATES = ["2026-07-19"]

describe("historySpanDays", () => {
  it("computes the real span for Large Cap's 7 real snapshots", () => {
    expect(historySpanDays(REAL_LARGE_CAP_DATES)).toBe(160)
  })

  it("returns 0 for a single real snapshot (Index Funds) — no span to report", () => {
    expect(historySpanDays(REAL_INDEX_FUNDS_DATES)).toBe(0)
  })

  it("returns 0 for zero dates", () => {
    expect(historySpanDays([])).toBe(0)
  })
})

describe("historySpanLabel", () => {
  it("labels Large Cap's real ~160-day span as months, not a fabricated year", () => {
    expect(historySpanLabel(REAL_LARGE_CAP_DATES)).toBe("5mo")
  })

  it("never claims '1Y'/'2Y' history for a single real snapshot", () => {
    expect(historySpanLabel(REAL_INDEX_FUNDS_DATES)).toBe("1 snapshot")
  })

  it("reports 'no data' for zero dates rather than an empty/misleading label", () => {
    expect(historySpanLabel([])).toBe("no data")
  })

  it("switches from month-level to year-level labelling once the real span grows", () => {
    // Same monthly cadence extended out past a year — same logic pattern as
    // computeBoundaryDates' short/long period switch in features/funds/utils.
    const twoYearsOfMonthlySnapshots = Array.from({ length: 25 }, (_, i) => {
      const d = new Date(Date.UTC(2026, 1, 9))
      d.setUTCMonth(d.getUTCMonth() + i)
      return d.toISOString().slice(0, 10)
    })
    expect(historySpanLabel(twoYearsOfMonthlySnapshots)).toMatch(/y$/)
  })
})

describe("lineColor", () => {
  it("uses the fixed palette for the first 10 funds", () => {
    for (let i = 0; i < LINE_COLORS.length; i++) {
      expect(lineColor(i)).toBe(LINE_COLORS[i])
    }
  })

  it("generates a distinct procedural colour past the fixed palette (real Large Cap union has 16 funds)", () => {
    const beyondPalette = lineColor(15)
    expect(LINE_COLORS).not.toContain(beyondPalette)
    expect(beyondPalette).toMatch(/^hsl\(/)
  })

  it("never repeats a colour across the real 16-fund Large Cap union set", () => {
    const colors = Array.from({ length: 16 }, (_, i) => lineColor(i))
    expect(new Set(colors).size).toBe(16)
  })
})

describe("toScoreChartRows", () => {
  // Real shape from mode=union: PGIM India Large Cap Fund - Growth
  // (schemecode 758, Regular plan) only entered the top-10 union at rank 8
  // on the latest snapshot in this trimmed fixture — its earlier dates are
  // a real gap (fund existed and was scored, just outside top-10 then),
  // matching how selfmade_ranking_snapshot rows are actually structured.
  const series: HistorySeriesLike[] = [
    {
      schemecode: 19619,
      fund_name: "PGIM India Large Cap Fund - Direct Plan - Dividend",
      data: [
        { date: "2026-02-09", composite_score: 83.65 },
        { date: "2026-07-19", composite_score: 83.85 },
      ],
    },
    {
      schemecode: 758,
      fund_name: "PGIM India Large Cap Fund - Growth",
      data: [
        { date: "2026-07-19", composite_score: 80.44 },
      ],
    },
  ]

  it("produces one row per real date, keyed by fund_name", () => {
    const rows = toScoreChartRows(["2026-02-09", "2026-07-19"], series)
    expect(rows).toHaveLength(2)
    expect(rows[0].date).toBe("2026-02-09")
    expect(rows[1].date).toBe("2026-07-19")
  })

  it("leaves a real null gap for a fund with no snapshot on that date — never fabricates/interpolates a value", () => {
    const rows = toScoreChartRows(["2026-02-09", "2026-07-19"], series)
    // Fund 758 has no real row for 2026-02-09 (wasn't top-10 that month)
    expect(rows[0]["PGIM India Large Cap Fund - Growth"]).toBeNull()
    // But it has a real value on 2026-07-19
    expect(rows[1]["PGIM India Large Cap Fund - Growth"]).toBe(80.44)
  })

  it("carries the real composite_score through unchanged for a fund present at every date", () => {
    const rows = toScoreChartRows(["2026-02-09", "2026-07-19"], series)
    expect(rows[0]["PGIM India Large Cap Fund - Direct Plan - Dividend"]).toBe(83.65)
    expect(rows[1]["PGIM India Large Cap Fund - Direct Plan - Dividend"]).toBe(83.85)
  })
})
