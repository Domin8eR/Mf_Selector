// Pure helper functions extracted from Fund Detail's presentation logic so
// they can be unit tested without rendering the full page (no React Query,
// no API calls, no DOM needed).

export function formatAxisDate(dateStr: string, isShortPeriod: boolean): string {
  const d = new Date(`${dateStr}T00:00:00`)
  return isShortPeriod
    ? d.toLocaleDateString("en-IN", { day: "2-digit", month: "short" })
    : d.toLocaleDateString("en-IN", { month: "short", year: "numeric" })
}

export function formatTooltipDate(dateStr: string): string {
  const d = new Date(`${dateStr}T00:00:00`)
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" })
}

/**
 * Gridline positions at month boundaries (short periods: 1M/6M) or year
 * boundaries (longer periods: 1Y/3Y/5Y/Max) — snapped to the nearest real
 * data point on/after each boundary. `dates` must be chronologically sorted
 * full ISO (YYYY-MM-DD) date strings.
 */
export function computeBoundaryDates(dates: string[], isShortPeriod: boolean): string[] {
  const boundaries: string[] = []
  let lastKey = ""
  for (const date of dates) {
    const key = isShortPeriod ? date.slice(0, 7) : date.slice(0, 4)
    if (key !== lastKey) {
      if (lastKey !== "") boundaries.push(date)
      lastKey = key
    }
  }
  return boundaries
}

export interface SectorHolding {
  sector: string | null
  weight_pct: number
}

export interface SectorDatum {
  name: string
  value: number
  pct: number
}

/** Aggregates holdings into per-sector weight + percentage-of-total. */
export function computeSectorData(holdings: SectorHolding[]): SectorDatum[] {
  const sectorMap: Record<string, number> = {}
  for (const h of holdings) {
    const s = h.sector ?? "Other"
    sectorMap[s] = (sectorMap[s] ?? 0) + h.weight_pct
  }
  const total = Object.values(sectorMap).reduce((a, b) => a + b, 0)
  return Object.entries(sectorMap)
    .sort((a, b) => b[1] - a[1])
    .map(([name, value]) => ({
      name,
      value: Math.round(value * 10) / 10,
      pct: total > 0 ? Math.round((value / total) * 1000) / 10 : 0,
    }))
}

export interface HoldingLite {
  company_name: string
  weight_pct: number
}

/**
 * Case-insensitive substring match against company name, run against the
 * FULL holdings list (not just the visible top-10) so a search can surface
 * a holding ranked well outside the default view.
 */
export function filterHoldingsByName<T extends HoldingLite>(holdings: T[], query: string): T[] {
  const q = query.trim().toLowerCase()
  if (!q) return holdings
  return holdings.filter(h => h.company_name.toLowerCase().includes(q))
}

export interface HeatmapCellForSegments {
  year: number
  month: number
  ir: number
  resolution: string
}

export interface AnnualSegment {
  label: string
  ir: number
  months: number
}

/**
 * Groups "annual_anchor" cells into contiguous same-IR runs (one real NAV-
 * anchor segment each), labeled by the year MOST of that segment's months
 * actually fall in — not the segment's last cell's year, which can be
 * misleading when the most recent segment is truncated by real monthly
 * data taking over its final months (e.g. a Jul-2025→Jan-2026 segment is
 * mostly a "2025" year, not "2026").
 */
export function computeAnnualSegments(cells: HeatmapCellForSegments[]): AnnualSegment[] {
  const chron = cells
    .filter(c => c.resolution === "annual_anchor")
    .sort((a, b) => a.year - b.year || a.month - b.month)

  const rawSegments: Array<{ ir: number; years: number[] }> = []
  for (const c of chron) {
    const last = rawSegments[rawSegments.length - 1]
    if (last && Math.abs(last.ir - c.ir) < 1e-6) {
      last.years.push(c.year)
    } else {
      rawSegments.push({ ir: c.ir, years: [c.year] })
    }
  }

  return rawSegments.map(seg => {
    const counts = new Map<number, number>()
    for (const y of seg.years) counts.set(y, (counts.get(y) ?? 0) + 1)
    const modeYear = [...counts.entries()].sort((a, b) => b[1] - a[1])[0][0]
    return { label: String(modeYear), ir: seg.ir, months: seg.years.length }
  })
}
