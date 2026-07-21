// Single reusable fund-selection widget: top 10 ranked funds in a category
// by default, with a search box that reaches beyond the top 10 into the
// full category (or all categories, via "ALL") using the existing
// /rankings/category search+pagination machinery — no new backend endpoint.
// Used by both Compare's "+ Add fund" picker and Fund Detail's empty state.

import { useState, useEffect, useRef } from "react"
import { useQuery } from "@tanstack/react-query"
import { Search, Loader2, X } from "lucide-react"
import { rankingsV2Api } from "@/lib/api"
import { queryKeys } from "@/lib/query-keys"

const TOP_N_DEFAULT = 10
const SEARCH_PAGE_SIZE = 50

export interface FundPickerProps {
  /** Category dropdown options. Omit to fetch the full real taxonomy (used
   *  when the caller has no natural category context, e.g. a global picker). */
  categories?: readonly string[]
  /** Initial selected category. Defaults to the first of `categories`, or
   *  "ALL" when `categories` is omitted. */
  defaultCategory?: string
  /** Schemecodes to hide from results (e.g. funds already selected elsewhere). */
  excludeCodes?: number[]
  onSelect: (schemecode: number, fundName: string) => void
  onClose?: () => void
  className?: string
}

export default function FundPicker({
  categories, defaultCategory, excludeCodes = [], onSelect, onClose, className,
}: FundPickerProps) {
  const ref = useRef<HTMLDivElement>(null)

  const categoriesQ = useQuery({
    queryKey: queryKeys.rankings.categoryOptions,
    queryFn: () => rankingsV2Api.getCategories(),
    enabled: !categories,
    staleTime: 10 * 60_000,
  })

  const categoryOptions: string[] = categories
    ? [...categories]
    : (categoriesQ.data?.categories.map(c => c.key) ?? ["ALL"])

  const [category, setCategory] = useState<string>(defaultCategory ?? categories?.[0] ?? "ALL")
  const [search, setSearch] = useState("")

  // Once the real taxonomy loads (when no fixed `categories` prop was given),
  // adopt it as the default rather than staying stuck on the "ALL" fallback.
  useEffect(() => {
    if (!categories && !defaultCategory && categoriesQ.data && !categoryOptions.includes(category)) {
      setCategory(categoryOptions[0] ?? "ALL")
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [categoriesQ.data])

  useEffect(() => {
    if (!onClose) return
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose()
    }
    document.addEventListener("mousedown", handler)
    return () => document.removeEventListener("mousedown", handler)
  }, [onClose])

  const resultsQ = useQuery({
    queryKey: queryKeys.rankings.v2Category(category, undefined, search.trim() || undefined),
    queryFn: () => rankingsV2Api.getCategory({
      category,
      search: search.trim() || undefined,
      pageSize: search.trim() ? SEARCH_PAGE_SIZE : TOP_N_DEFAULT,
    }),
    staleTime: 60_000,
  })

  const available = (resultsQ.data?.results ?? []).filter(
    r => !excludeCodes.includes(r.schemecode),
  )

  return (
    <div ref={ref} className={className ?? "bg-white border border-gray-200 rounded-xl shadow-xl w-[380px] p-3"}>
      <div className="flex items-center gap-2 mb-2">
        <select
          value={category}
          onChange={e => { setCategory(e.target.value); setSearch("") }}
          className="text-xs border border-gray-200 rounded-lg px-2 py-1 flex-1 bg-white focus:outline-none focus:ring-1 focus:ring-blue-500"
        >
          {categoryOptions.map(c => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
        {onClose && (
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="h-4 w-4" />
          </button>
        )}
      </div>
      <div className="relative mb-2">
        <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-gray-400" />
        <input
          autoFocus={!!onClose}
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search fund name…"
          className="w-full text-xs border border-gray-200 rounded-lg pl-6 pr-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-500"
        />
      </div>
      {!search.trim() && (
        <p className="text-[10px] text-gray-400 mb-1.5 px-0.5">Top {TOP_N_DEFAULT} by rank — search to find any other ranked fund</p>
      )}
      <div className="max-h-56 overflow-y-auto divide-y divide-gray-50">
        {resultsQ.isLoading && (
          <div className="py-5 flex justify-center"><Loader2 className="h-4 w-4 animate-spin text-gray-300" /></div>
        )}
        {!resultsQ.isLoading && available.length === 0 && (
          <p className="py-4 text-xs text-gray-400 text-center">No ranked funds found</p>
        )}
        {available.map(r => (
          <button
            key={r.schemecode}
            onClick={() => { onSelect(r.schemecode, r.fund_name); onClose?.() }}
            className="w-full text-left px-2 py-2 hover:bg-blue-50 group transition-colors"
          >
            <div className="text-xs font-medium text-gray-800 group-hover:text-blue-700 truncate">{r.fund_name}</div>
            <div className="text-[10px] text-gray-400">
              {r.amc_name} · Rank #{r.rank} · Score {r.composite_score.toFixed(1)}
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}
