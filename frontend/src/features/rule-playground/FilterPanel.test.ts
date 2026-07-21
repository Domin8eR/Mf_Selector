import { describe, it, expect } from "vitest"
import { EMPTY_FILTERS, toEligibilityFilters } from "./FilterPanel"

describe("toEligibilityFilters", () => {
  it("converts an all-empty FilterValues to an all-undefined payload (no filters applied)", () => {
    const payload = toEligibilityFilters(EMPTY_FILTERS)
    expect(payload.aum_min_cr).toBeUndefined()
    expect(payload.aum_max_cr).toBeUndefined()
    expect(payload.expense_ratio_max).toBeUndefined()
    expect(payload.ir_slope_min).toBeUndefined()
    expect(payload.sortino_min).toBeUndefined()
    expect(payload.bucket_36s).toBeUndefined()
    expect(payload.amc_codes).toBeUndefined()
    expect(payload.sector_exposure).toBeUndefined()
    expect(payload.company_include).toBeUndefined()
    // Booleans keep their real default (exclude_merged defaults true, not
    // "disabled" — it's a real toggle with a real default value).
    expect(payload.exclude_merged).toBe(true)
    expect(payload.status).toBe("Active")
  })

  it("parses a real AUM range into numbers, never NaN or 0-as-empty", () => {
    const payload = toEligibilityFilters({
      ...EMPTY_FILTERS,
      aum_min_cr: "1000",
      aum_max_cr: "5000",
    })
    expect(payload.aum_min_cr).toBe(1000)
    expect(payload.aum_max_cr).toBe(5000)
  })

  it("treats an explicit 0 as a real filter value, not as empty/disabled", () => {
    // e.g. ir_slope_min = 0 means "must be flat or improving" — a real,
    // meaningful threshold distinct from "no filter applied".
    const payload = toEligibilityFilters({ ...EMPTY_FILTERS, ir_slope_min: "0" })
    expect(payload.ir_slope_min).toBe(0)
  })

  it("builds sector_exposure only from selected sectors, each at the real 0.01% inclusion threshold", () => {
    const payload = toEligibilityFilters({
      ...EMPTY_FILTERS,
      sector_names: ["Financials", "Information Technology"],
    })
    expect(payload.sector_exposure).toEqual({
      Financials: 0.01,
      "Information Technology": 0.01,
    })
  })

  it("converts a single bucket_36 selection into the multi-select array shape the API expects", () => {
    const payload = toEligibilityFilters({ ...EMPTY_FILTERS, bucket_36: "Large Cap" })
    expect(payload.bucket_36s).toEqual(["Large Cap"])
  })

  it("trims company include/exclude text and drops it entirely when blank", () => {
    const withValue = toEligibilityFilters({ ...EMPTY_FILTERS, company_include: "  HDFC Bank  " })
    expect(withValue.company_include).toBe("HDFC Bank")

    const blank = toEligibilityFilters({ ...EMPTY_FILTERS, company_include: "   " })
    expect(blank.company_include).toBeUndefined()
  })

  it("passes through AMC include/exclude lists only when non-empty", () => {
    const empty = toEligibilityFilters(EMPTY_FILTERS)
    expect(empty.amc_codes).toBeUndefined()

    const withAmcs = toEligibilityFilters({ ...EMPTY_FILTERS, amc_codes: [12, 34] })
    expect(withAmcs.amc_codes).toEqual([12, 34])
  })
})
