// Pure helper functions extracted from Category Rankings' history charts so
// they can be unit tested without rendering the full page (no React Query,
// no API calls, no DOM needed) — same pattern as features/funds/utils.ts.

/** Real span (in days) between the first and last snapshot date. Returns 0
 *  when there are fewer than 2 dates — there's no real span to report. */
export function historySpanDays(dates: string[]): number {
  if (dates.length < 2) return 0
  const first = new Date(`${dates[0]}T00:00:00`)
  const last = new Date(`${dates[dates.length - 1]}T00:00:00`)
  return Math.round((last.getTime() - first.getTime()) / 86_400_000)
}

/**
 * Honest label for whatever real history window actually exists — NEVER a
 * hardcoded "6 months"/"2Y" claim. Mirrors the backend's
 * _score_change_window_label (rankings.py) so the Δ Score column and these
 * history charts describe the same real span the same way.
 */
export function historySpanLabel(dates: string[]): string {
  if (dates.length === 0) return "no data"
  if (dates.length === 1) return "1 snapshot"
  const days = historySpanDays(dates)
  if (days < 45) return `${days}d`
  if (days < 335) return `${Math.round(days / 30.44)}mo`
  return `${(days / 365.25).toFixed(1)}y`
}

/** Score History's fund count is a real top-N union across snapshots, not
 *  fixed at 10 — it can exceed the fixed palette below, so indices past it
 *  fall back to a procedurally spread HSL colour rather than silently
 *  repeating (which would make two different funds look like the same line). */
export const LINE_COLORS = [
  "#6366f1", "#10b981", "#f59e0b", "#ef4444", "#3b82f6",
  "#8b5cf6", "#06b6d4", "#f97316", "#ec4899", "#84cc16",
]

export function lineColor(i: number): string {
  if (i < LINE_COLORS.length) return LINE_COLORS[i]
  return `hsl(${(i * 47) % 360}, 65%, 45%)`
}

export const shortFundName = (name: string) => name.split(" ").slice(0, 3).join(" ")

export interface HistorySeriesPointLike {
  date: string
  composite_score: number | null
}

export interface HistorySeriesLike {
  schemecode: number
  fund_name: string
  data: HistorySeriesPointLike[]
}

/**
 * Reshape per-fund series into Recharts' wide row-per-date format. A fund
 * missing a real snapshot on some date gets `null` for that date (a real
 * gap) — never fabricated/interpolated. Recharts draws a visual break
 * across a null point as long as the Line does NOT set connectNulls.
 */
export function toScoreChartRows(
  dates: string[],
  series: HistorySeriesLike[],
): Record<string, string | number | null>[] {
  return dates.map((dt) => {
    const point: Record<string, string | number | null> = { date: dt.slice(0, 10) }
    series.forEach((s) => {
      const dp = s.data.find((d) => d.date === dt)
      point[s.fund_name] = dp?.composite_score ?? null
    })
    return point
  })
}
