import { describe, it, expect } from "vitest"
import {
  formatAxisDate, computeBoundaryDates, computeSectorData, computeAnnualSegments,
  filterHoldingsByName,
} from "./utils"

// Real holdings for schemecode 19619 (PGIM India Large Cap Fund - Direct
// Plan - Dividend), fetched from GET /schemes/19619/holdings?limit=50 —
// "Dr Reddys Laboratories" is its real 11th-ranked holding by weight,
// outside the default top-10 view (see backend/tests/test_fund_detail.py's
// test_search_beyond_top_10_finds_real_holding for the backend side of
// this same fixture).
const REAL_HOLDINGS_19619 = [
  { company_name: "Coal India Ltd", weight_pct: 10.222 },
  { company_name: "NTPC Ltd", weight_pct: 7.9667 },
  { company_name: "ICICI Bank Ltd", weight_pct: 7.8626 },
  { company_name: "Tata Consultancy Services Ltd", weight_pct: 6.6959 },
  { company_name: "Power Grid Corporation", weight_pct: 5.9634 },
  { company_name: "HCL Technologies Ltd", weight_pct: 4.8961 },
  { company_name: "Tata Steel Ltd", weight_pct: 4.4934 },
  { company_name: "Wipro Ltd", weight_pct: 4.4414 },
  { company_name: "Infosys Ltd", weight_pct: 4.0532 },
  { company_name: "Bharti Airtel Ltd", weight_pct: 4.0168 },
  { company_name: "Dr Reddys Laboratories", weight_pct: 3.5551 },
  { company_name: "Sun Pharmaceutical Industries", weight_pct: 3.2312 },
]

describe("filterHoldingsByName", () => {
  it("finds a real holding ranked outside the top 10 by a company-name substring", () => {
    const top10 = REAL_HOLDINGS_19619.slice(0, 10)
    expect(top10.some(h => h.company_name === "Dr Reddys Laboratories")).toBe(false)

    const results = filterHoldingsByName(REAL_HOLDINGS_19619, "dr reddys")
    expect(results).toHaveLength(1)
    expect(results[0].company_name).toBe("Dr Reddys Laboratories")
    expect(results[0].weight_pct).toBeCloseTo(3.5551, 3)
  })

  it("is case-insensitive and matches substrings anywhere in the name", () => {
    expect(filterHoldingsByName(REAL_HOLDINGS_19619, "TATA").map(h => h.company_name)).toEqual([
      "Tata Consultancy Services Ltd", "Tata Steel Ltd",
    ])
  })

  it("returns the full list unfiltered when the query is empty or whitespace", () => {
    expect(filterHoldingsByName(REAL_HOLDINGS_19619, "")).toHaveLength(REAL_HOLDINGS_19619.length)
    expect(filterHoldingsByName(REAL_HOLDINGS_19619, "   ")).toHaveLength(REAL_HOLDINGS_19619.length)
  })

  it("returns an empty list when nothing matches", () => {
    expect(filterHoldingsByName(REAL_HOLDINGS_19619, "nonexistent company xyz")).toEqual([])
  })
})

describe("formatAxisDate", () => {
  it("produces day-level labels for a 1M-style short period", () => {
    expect(formatAxisDate("2026-06-03", true)).toBe("03 Jun")
    expect(formatAxisDate("2026-06-17", true)).toBe("17 Jun")
    expect(formatAxisDate("2026-07-01", true)).toBe("01 Jul")
  })

  it("produces month-level labels for a 3Y-style long period", () => {
    expect(formatAxisDate("2023-06-03", false)).toBe("Jun 2023")
    expect(formatAxisDate("2024-11-17", false)).toBe("Nov 2024")
    expect(formatAxisDate("2026-01-01", false)).toBe("Jan 2026")
  })

  it("never collapses distinct dates to the same short-period label (the original 1M bug)", () => {
    const dates = ["2026-06-01", "2026-06-08", "2026-06-15", "2026-06-22", "2026-06-29"]
    const labels = dates.map(d => formatAxisDate(d, true))
    expect(new Set(labels).size).toBe(dates.length)
  })
})

describe("computeBoundaryDates", () => {
  it("marks month boundaries for a short (1M/6M) period", () => {
    const dates = ["2026-05-29", "2026-06-01", "2026-06-15", "2026-07-01", "2026-07-15"]
    expect(computeBoundaryDates(dates, true)).toEqual(["2026-06-01", "2026-07-01"])
  })

  it("marks year boundaries for a long (1Y/3Y/5Y/Max) period", () => {
    const dates = ["2023-12-29", "2024-01-15", "2024-12-20", "2025-01-10", "2025-06-01"]
    expect(computeBoundaryDates(dates, false)).toEqual(["2024-01-15", "2025-01-10"])
  })
})

describe("computeSectorData", () => {
  it("produces percentages that sum to ~100% when holdings fully cover the total", () => {
    const holdings = [
      { sector: "Financials", weight_pct: 30 },
      { sector: "IT", weight_pct: 25 },
      { sector: "Energy", weight_pct: 20 },
      { sector: "Healthcare", weight_pct: 15 },
      { sector: "Other", weight_pct: 10 },
    ]
    const data = computeSectorData(holdings)
    const totalPct = data.reduce((a, d) => a + d.pct, 0)
    expect(totalPct).toBeCloseTo(100, 1)
  })

  it("reflects the real gap when holdings don't cover full AUM (percentages still sum to 100 of the covered slice)", () => {
    // Holdings here only account for 60% of AUM (the remaining 40% isn't in
    // the top-N holdings list) — pct is always relative to what's actually
    // covered, not fabricated against the full AUM.
    const holdings = [
      { sector: "Financials", weight_pct: 36 },
      { sector: "IT", weight_pct: 24 },
    ]
    const data = computeSectorData(holdings)
    const totalPct = data.reduce((a, d) => a + d.pct, 0)
    expect(totalPct).toBeCloseTo(100, 1)
    expect(data.find(d => d.name === "Financials")?.pct).toBeCloseTo(60, 1)
  })

  it("groups holdings with a null sector under Other", () => {
    const data = computeSectorData([
      { sector: "IT", weight_pct: 50 },
      { sector: null, weight_pct: 50 },
    ])
    expect(data.find(d => d.name === "Other")?.pct).toBeCloseTo(50, 1)
  })
})

describe("computeAnnualSegments", () => {
  it("labels each real year present in the data, not hardcoded years", () => {
    const cells = [
      { year: 2023, month: 3, ir: 0.25, resolution: "annual_anchor" },
      { year: 2023, month: 6, ir: 0.25, resolution: "annual_anchor" },
      { year: 2024, month: 3, ir: 0.40, resolution: "annual_anchor" },
      { year: 2024, month: 6, ir: 0.40, resolution: "annual_anchor" },
      { year: 2025, month: 3, ir: 0.10, resolution: "annual_anchor" },
    ]
    const segments = computeAnnualSegments(cells)
    expect(segments.map(s => s.label)).toEqual(["2023", "2024", "2025"])
  })

  it("labels a segment by its mode year, not its last cell's year, when truncated by real monthly data (regression: previously produced 2023, 2024, 2026 with 2025 missing)", () => {
    const cells = [
      { year: 2023, month: 1, ir: 0.20, resolution: "annual_anchor" },
      { year: 2023, month: 6, ir: 0.20, resolution: "annual_anchor" },
      { year: 2024, month: 1, ir: 0.35, resolution: "annual_anchor" },
      { year: 2024, month: 6, ir: 0.35, resolution: "annual_anchor" },
      // This segment's real months are mostly 2025 (Jul-Dec) but the run of
      // "annual_anchor" cells with the same IR value trails one cell into
      // Jan 2026 before the real monthly "snapshot" strip takes over —
      // the segment must still be labeled "2025", not "2026".
      { year: 2025, month: 7, ir: 0.15, resolution: "annual_anchor" },
      { year: 2025, month: 8, ir: 0.15, resolution: "annual_anchor" },
      { year: 2025, month: 9, ir: 0.15, resolution: "annual_anchor" },
      { year: 2025, month: 10, ir: 0.15, resolution: "annual_anchor" },
      { year: 2025, month: 11, ir: 0.15, resolution: "annual_anchor" },
      { year: 2025, month: 12, ir: 0.15, resolution: "annual_anchor" },
      { year: 2026, month: 1, ir: 0.15, resolution: "annual_anchor" },
    ]
    const segments = computeAnnualSegments(cells)
    expect(segments.map(s => s.label)).toEqual(["2023", "2024", "2025"])
    expect(segments.map(s => s.label)).not.toContain("2026")
  })

  it("ignores synthetic (fabricated) cells entirely", () => {
    const cells = [
      { year: 2023, month: 3, ir: 0.25, resolution: "annual_anchor" },
      { year: 2022, month: 1, ir: 0.99, resolution: "synthetic" },
    ]
    const segments = computeAnnualSegments(cells)
    expect(segments).toHaveLength(1)
    expect(segments[0].label).toBe("2023")
  })
})
