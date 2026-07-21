import { useState, useRef, useEffect, useCallback } from "react"
import { useSearchParams } from "react-router-dom"
import { useMutation, useQuery } from "@tanstack/react-query"
import {
  Send, Sparkles, Loader2, CheckCircle2, AlertCircle,
  ThumbsUp, ThumbsDown, Database, Calendar, X,
  BarChart2, Info, Wifi, WifiOff,
} from "lucide-react"
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  LineChart, Line, ResponsiveContainer,
} from "recharts"
import { cn } from "@/lib/utils"
import { chatApi, type ChatResponse, type DataConfidence } from "@/lib/api"

// ── Types ─────────────────────────────────────────────────────────────────────

interface ActiveFund {
  schemecode: number
  name: string
  category: string
}

interface Message {
  id: string
  role: "user" | "assistant"
  content: string
  messageId?: number   // DB id — needed for feedback
  intent?: string
  toolCalls?: { tool: string; params: Record<string, unknown>; ok: boolean }[]
  resultType?: string
  tableColumns?: unknown[] | null
  tableRows?: unknown[][] | null
  chartType?: string | null
  chartData?: { name: string; value: number }[] | null
  sourceTables?: string[]
  confidence?: DataConfidence
  nextActions?: string[]
  llmAvailable?: boolean
  loading?: boolean
  fromPage?: string   // "fund_detail" | "compare" | "rankings" etc.
}

// ── Curated suggested queries ─────────────────────────────────────────────────

const SUGGESTED_QUERIES = [
  "Show top ranked funds in Equity — Large Cap",
  "What changed in mid cap rankings over 6 months?",
  "Explain the active scoring rule weights",
  "Search factsheets for large cap strategy mandate",
  "Compare top 2 large cap funds on IR and Sharpe",
  "Why is Mirae Asset ranked #3 in Large Cap?",
  "Show small cap funds with positive IR slope",
  "Which funds outperformed their benchmark 3 years in a row?",
]

// ── Structured result renderers ───────────────────────────────────────────────

function ResultTable({ columns, rows }: { columns: unknown[]; rows: unknown[][] }) {
  if (!columns.length) return null
  return (
    <div className="mt-2 overflow-x-auto rounded-lg border border-gray-200">
      <table className="text-[11px] w-full border-collapse">
        <thead>
          <tr className="bg-gray-50 border-b border-gray-200">
            {columns.map((col, i) => (
              <th key={i} className="px-3 py-2 text-left font-semibold text-gray-600 whitespace-nowrap">
                {String(col)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, ri) => (
            <tr key={ri} className={cn("border-b border-gray-100", ri % 2 === 0 ? "bg-white" : "bg-gray-50/50")}>
              {row.map((cell, ci) => (
                <td key={ci} className="px-3 py-1.5 text-gray-700 whitespace-nowrap">
                  {cell === null || cell === undefined ? "—" : String(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ResultChart({ chartType, data }: { chartType: string; data: { name: string; value: number }[] }) {
  if (!data?.length) return null
  return (
    <div className="mt-2 border border-gray-200 rounded-lg bg-gray-50 p-3">
      <div className="flex items-center gap-1.5 mb-2">
        <BarChart2 className="h-3 w-3 text-gray-400" />
        <span className="text-[10px] text-gray-400">From backend tool results</span>
      </div>
      <ResponsiveContainer width="100%" height={120}>
        {chartType === "line" ? (
          <LineChart data={data} margin={{ top: 2, right: 5, bottom: 2, left: -20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" vertical={false} />
            <XAxis dataKey="name" tick={{ fontSize: 9, fill: "#9CA3AF" }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fontSize: 9, fill: "#9CA3AF" }} axisLine={false} tickLine={false} />
            <Tooltip contentStyle={{ fontSize: 10, borderRadius: 6 }} />
            <Line type="monotone" dataKey="value" stroke="#2563EB" strokeWidth={2} dot={false} />
          </LineChart>
        ) : (
          <BarChart data={data} margin={{ top: 2, right: 5, bottom: 2, left: -20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" vertical={false} />
            <XAxis dataKey="name" tick={{ fontSize: 9, fill: "#9CA3AF" }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fontSize: 9, fill: "#9CA3AF" }} axisLine={false} tickLine={false} />
            <Tooltip contentStyle={{ fontSize: 10, borderRadius: 6, border: "1px solid #E5E7EB" }} cursor={{ fill: "#EFF6FF" }} />
            <Bar dataKey="value" fill="#2563EB" radius={[3, 3, 0, 0]} opacity={0.8} />
          </BarChart>
        )}
      </ResponsiveContainer>
    </div>
  )
}

// ── Tool call chips ───────────────────────────────────────────────────────────

function ToolChip({ call }: { call: { tool: string; ok: boolean } }) {
  return (
    <span className={cn(
      "inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full border font-medium",
      call.ok ? "bg-green-50 text-green-700 border-green-200" : "bg-red-50 text-red-600 border-red-200",
    )}>
      {call.ok ? <CheckCircle2 className="h-2.5 w-2.5" /> : <AlertCircle className="h-2.5 w-2.5" />}
      {call.tool.replace(/_/g, " ")}
    </span>
  )
}

// ── Feedback buttons ──────────────────────────────────────────────────────────

function FeedbackBar({ messageId, onFeedback }: { messageId?: number; onFeedback?: (score: 1 | -1) => void }) {
  const [voted, setVoted] = useState<1 | -1 | null>(null)
  if (!messageId) return null
  const vote = (score: 1 | -1) => {
    setVoted(score)
    chatApi.recordFeedback(messageId, score).catch(() => undefined)
    onFeedback?.(score)
  }
  return (
    <div className="flex items-center gap-1.5 mt-2">
      <span className="text-[10px] text-gray-400">Was this helpful?</span>
      <button onClick={() => vote(1)} disabled={voted !== null}
        className={cn("p-1 rounded transition-colors", voted === 1 ? "text-green-600" : "text-gray-400 hover:text-green-600 hover:bg-green-50")}>
        <ThumbsUp className="h-3 w-3" />
      </button>
      <button onClick={() => vote(-1)} disabled={voted !== null}
        className={cn("p-1 rounded transition-colors", voted === -1 ? "text-red-500" : "text-gray-400 hover:text-red-500 hover:bg-red-50")}>
        <ThumbsDown className="h-3 w-3" />
      </button>
    </div>
  )
}

// ── Message cards ─────────────────────────────────────────────────────────────

function UserMessage({ msg }: { msg: Message }) {
  return (
    <div className="flex items-start gap-3 justify-end">
      <div className="bg-blue-600 text-white rounded-xl px-4 py-2.5 text-sm max-w-[80%] leading-relaxed">
        {msg.content}
        {msg.fromPage && (
          <div className="text-[10px] text-blue-200 mt-1">
            From {msg.fromPage.replace(/_/g, " ")}
          </div>
        )}
      </div>
      <div className="h-7 w-7 rounded-full bg-blue-600 flex items-center justify-center flex-shrink-0 mt-0.5 text-white text-[11px] font-semibold">
        U
      </div>
    </div>
  )
}

function AssistantMessage({ msg, onSuggestClick }: { msg: Message; onSuggestClick: (q: string) => void }) {
  const isReframe = msg.intent === "recommendation_request"

  return (
    <div className="flex items-start gap-3">
      <div className={cn(
        "h-7 w-7 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5",
        isReframe ? "bg-amber-500" : "bg-purple-600"
      )}>
        <Sparkles className="h-3.5 w-3.5 text-white" />
      </div>
      <div className="flex-1 min-w-0">
        {msg.loading ? (
          <div className="flex items-center gap-2 text-gray-400 py-2">
            <Loader2 className="h-4 w-4 animate-spin" />
            <span className="text-sm">Researching…</span>
          </div>
        ) : (
          <>
            {/* LLM unavailable warning */}
            {msg.llmAvailable === false && (
              <div className="flex items-center gap-1.5 text-[10px] text-amber-600 bg-amber-50 border border-amber-200 rounded-lg px-2.5 py-1.5 mb-2">
                <WifiOff className="h-3 w-3 flex-shrink-0" />
                AI answers not available — showing template response from backend data
              </div>
            )}

            {/* Compliance reframe badge */}
            {isReframe && (
              <div className="flex items-center gap-1.5 text-[10px] text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-2.5 py-1.5 mb-2">
                <Info className="h-3 w-3 flex-shrink-0" />
                Investment advice is outside scope — showing what AltStreet can help with
              </div>
            )}

            {/* Tool call chips */}
            {msg.toolCalls && msg.toolCalls.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mb-2">
                {msg.toolCalls.map((tc, i) => <ToolChip key={i} call={tc} />)}
              </div>
            )}

            {/* Answer prose */}
            <div className={cn(
              "border rounded-xl p-3.5 text-sm leading-relaxed whitespace-pre-line",
              isReframe
                ? "bg-amber-50 border-amber-200 text-amber-900"
                : "bg-white border-gray-200 text-gray-700"
            )}>
              {msg.content}
            </div>

            {/* Structured result */}
            {msg.resultType === "table" && msg.tableColumns && msg.tableRows && (
              <ResultTable columns={msg.tableColumns} rows={msg.tableRows} />
            )}
            {msg.resultType === "chart" && msg.chartData && (
              <ResultChart chartType={msg.chartType ?? "bar"} data={msg.chartData} />
            )}

            {/* Sources */}
            {msg.sourceTables && msg.sourceTables.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mt-2 items-center">
                <Database className="h-3 w-3 text-gray-400" />
                {msg.sourceTables.map(s => (
                  <span key={s} className="text-[10px] bg-gray-50 border border-gray-200 px-2 py-0.5 rounded text-gray-500 font-mono">
                    {s}
                  </span>
                ))}
              </div>
            )}

            {/* Confidence + Feedback row */}
            <div className="flex items-center justify-between mt-2">
              {msg.confidence && (
                <span className={cn(
                  "text-[10px] px-2 py-0.5 rounded-full border font-medium",
                  msg.confidence.level === "high" ? "bg-green-50 text-green-700 border-green-200"
                    : msg.confidence.level === "medium" ? "bg-amber-50 text-amber-700 border-amber-200"
                    : "bg-red-50 text-red-600 border-red-200"
                )}>
                  {msg.confidence.level} confidence
                  {msg.confidence.recency !== "N/A" && ` · ${msg.confidence.recency}`}
                </span>
              )}
              <FeedbackBar messageId={msg.messageId} />
            </div>

            {/* Next action buttons */}
            {msg.nextActions && msg.nextActions.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mt-2">
                {msg.nextActions.slice(0, 3).map(q => (
                  <button key={q} onClick={() => onSuggestClick(q)}
                    className="text-[11px] text-blue-600 bg-blue-50 border border-blue-100 rounded-full px-2.5 py-1 hover:bg-blue-100 transition-colors">
                    {q}
                  </button>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

// ── Left context panel ────────────────────────────────────────────────────────

function ContextPanel({
  activeFunds,
  onRemoveFund,
  sourceTables,
  latestDate,
  llmAvailable,
  onSuggestClick,
}: {
  activeFunds: ActiveFund[]
  onRemoveFund: (sc: number) => void
  sourceTables: string[]
  latestDate: string | null
  llmAvailable: boolean | null
  onSuggestClick: (q: string) => void
}) {
  return (
    <div className="w-[220px] flex-shrink-0 border-r border-gray-200 bg-white overflow-y-auto p-4 space-y-5 text-[11px]">
      {/* LLM status */}
      <div className="flex items-center gap-1.5">
        {llmAvailable === true ? (
          <>
            <Wifi className="h-3 w-3 text-green-500 flex-shrink-0" />
            <span className="text-green-700 font-medium">AI answers active</span>
          </>
        ) : llmAvailable === false ? (
          <>
            <WifiOff className="h-3 w-3 text-amber-500 flex-shrink-0" />
            <span className="text-amber-700 font-medium">Template mode</span>
          </>
        ) : (
          <span className="text-gray-400">No queries yet</span>
        )}
      </div>

      {/* Active funds */}
      {activeFunds.length > 0 && (
        <div>
          <div className="font-semibold text-gray-500 uppercase tracking-wide mb-2">Active Fund(s)</div>
          <div className="space-y-1">
            {activeFunds.map(f => (
              <div key={f.schemecode} className="flex items-center gap-1 bg-blue-50 border border-blue-200 rounded-lg px-2 py-1.5">
                <span className="flex-1 text-blue-800 truncate" title={f.name}>{f.name}</span>
                <button onClick={() => onRemoveFund(f.schemecode)} className="text-blue-400 hover:text-blue-700 flex-shrink-0">
                  <X className="h-3 w-3" />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Data sources from last response */}
      {sourceTables.length > 0 && (
        <div>
          <div className="font-semibold text-gray-500 uppercase tracking-wide mb-2">Data Sources</div>
          <div className="space-y-1">
            {sourceTables.map(t => (
              <div key={t} className="flex items-center gap-1.5 text-gray-600">
                <Database className="h-2.5 w-2.5 text-gray-400 flex-shrink-0" />
                <span className="font-mono text-[10px] truncate">{t}</span>
              </div>
            ))}
            {latestDate && (
              <div className="flex items-center gap-1.5 text-gray-500 mt-1">
                <Calendar className="h-2.5 w-2.5 text-gray-400 flex-shrink-0" />
                <span>As of {latestDate}</span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Suggested queries */}
      <div>
        <div className="font-semibold text-gray-500 uppercase tracking-wide mb-2">Suggested Queries</div>
        <div className="space-y-1">
          {SUGGESTED_QUERIES.map(q => (
            <button key={q} onClick={() => onSuggestClick(q)}
              className="w-full text-left text-gray-600 hover:text-blue-600 hover:bg-blue-50 rounded-lg px-2 py-1.5 flex items-start gap-1.5 transition-colors">
              <span className="text-blue-400 mt-0.5 flex-shrink-0">↗</span>
              <span className="leading-relaxed">{q}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function ChatPage() {
  const [searchParams] = useSearchParams()

  // Context from Fund Detail / Compare / Rankings / Home / InsightCard (query string)
  const fromPage      = searchParams.get("from") ?? undefined
  const ctxSchemecode = searchParams.get("schemecode")
  const ctxName       = searchParams.get("fund_name")
  const ctxCategory   = searchParams.get("category")
  const initialQuery  = searchParams.get("q") ?? undefined
  const threadParam   = searchParams.get("thread") ?? undefined
  // Canonical follow-up payload (2026-07-18) from a compact insight card's
  // follow-up button — takes priority over the looser selected_entities
  // context below, since it already carries allowed_conclusion for the
  // LLM constraint.
  const followUpContext = (() => {
    const raw = searchParams.get("context")
    if (!raw) return null
    try { return JSON.parse(raw) as Record<string, unknown> } catch { return null }
  })()

  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput]       = useState("")
  const [threadId, setThreadId] = useState<string | undefined>()
  const [activeFunds, setActiveFunds] = useState<ActiveFund[]>(() => {
    if (ctxSchemecode && ctxName) {
      return [{ schemecode: Number(ctxSchemecode), name: decodeURIComponent(ctxName), category: ctxCategory ?? "" }]
    }
    return []
  })
  const [lastSourceTables, setLastSourceTables] = useState<string[]>([])
  const [lastDate, setLastDate] = useState<string | null>(null)
  const [llmAvailable, setLlmAvailable] = useState<boolean | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  // Load an existing thread's messages when arriving via Home's "Recent Chats" (?thread=<id>)
  const threadQuery = useQuery({
    queryKey: ["chat", "thread", threadParam],
    queryFn: () => chatApi.getThreadMessages(threadParam!),
    enabled: !!threadParam,
  })

  useEffect(() => {
    if (!threadQuery.data) return
    setThreadId(threadQuery.data.thread_id)
    setMessages(threadQuery.data.messages.map((m): Message => ({
      id: String(m.id),
      role: m.role,
      content: m.content,
      messageId: m.id,
      intent: m.intent ?? undefined,
      resultType: m.result_component_type ?? undefined,
      tableColumns: m.table_columns,
      tableRows: m.table_rows,
      chartType: m.chart_type as "bar" | "line" | null,
      chartData: m.chart_data as { name: string; value: number }[] | null,
      sourceTables: m.source_tables ?? undefined,
      confidence: m.data_confidence ?? undefined,
      nextActions: m.suggested_next_actions ?? undefined,
    })))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [threadQuery.data])

  const sendMutation = useMutation({
    mutationFn: (message: string) => {
      let ctx: Record<string, unknown> = {}
      if (followUpContext) {
        ctx = followUpContext
      } else if (activeFunds.length > 0) {
        ctx.selected_entities = activeFunds.map(f => f.schemecode)
        ctx.primary_schemecode = activeFunds[0].schemecode
        ctx.source_page = fromPage ?? "chat"
      }
      return chatApi.query({ message, thread_id: threadId, context: Object.keys(ctx).length ? ctx : undefined })
    },

    onMutate: (message) => {
      const userMsg: Message = { id: Date.now().toString(), role: "user", content: message, fromPage: fromPage && messages.length === 0 ? fromPage : undefined }
      const loadingMsg: Message = { id: `loading-${Date.now()}`, role: "assistant", content: "", loading: true }
      setMessages(prev => [...prev, userMsg, loadingMsg])
    },

    onSuccess: (data: ChatResponse) => {
      setThreadId(data.thread_id)
      setLlmAvailable(data.llm_available)

      // Update context panel state from latest response
      if (data.source_tables?.length) setLastSourceTables(data.source_tables)
      if (data.data_confidence?.recency && data.data_confidence.recency !== "N/A") {
        setLastDate(data.data_confidence.recency)
      }

      setMessages(prev => [
        ...prev.filter(m => !m.loading),
        {
          id: String(data.message_id),
          role: "assistant",
          content: data.answer,
          messageId: data.message_id,
          intent: data.intent,
          toolCalls: data.tool_calls,
          resultType: data.result_component_type,
          tableColumns: data.table_columns,
          tableRows: data.table_rows,
          chartType: data.chart_type,
          chartData: data.chart_data,
          sourceTables: data.source_tables,
          confidence: data.data_confidence,
          nextActions: data.suggested_next_actions,
          llmAvailable: data.llm_available,
        },
      ])
    },

    onError: () => {
      setMessages(prev => [
        ...prev.filter(m => !m.loading),
        {
          id: `err-${Date.now()}`,
          role: "assistant",
          content: "Failed to get a response. Please check that the backend is running and the database has been seeded.",
        },
      ])
    },
  })

  const submit = useCallback((text?: string) => {
    const query = (text ?? input).trim()
    if (!query || sendMutation.isPending) return
    sendMutation.mutate(query)
    setInput("")
  }, [input, sendMutation])

  // Auto-submit a query carried in via ?q= (e.g. Home's command bar) — fire once.
  const autoSubmitted = useRef(false)
  useEffect(() => {
    if (initialQuery && !autoSubmitted.current) {
      autoSubmitted.current = true
      submit(initialQuery)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialQuery])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  // If arriving from Fund Detail / Compare with context, show a banner on first render
  const contextBanner = fromPage && messages.length === 0 && ctxName ? (
    <div className="mx-4 mt-4 flex items-center gap-2 bg-blue-50 border border-blue-200 rounded-xl px-4 py-2.5 text-[11px] text-blue-800">
      <Info className="h-3.5 w-3.5 flex-shrink-0 text-blue-500" />
      <span>
        Asked from <strong>{fromPage.replace(/_/g, " ")}</strong> — active fund:&nbsp;
        <strong>{decodeURIComponent(ctxName)}</strong>
      </span>
      <button className="ml-auto text-blue-400 hover:text-blue-700" onClick={() => setActiveFunds([])}>
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  ) : null

  return (
    <div className="flex h-full overflow-hidden">
      {/* ── Left context panel ── */}
      <ContextPanel
        activeFunds={activeFunds}
        onRemoveFund={sc => setActiveFunds(prev => prev.filter(f => f.schemecode !== sc))}
        sourceTables={lastSourceTables}
        latestDate={lastDate}
        llmAvailable={llmAvailable}
        onSuggestClick={submit}
      />

      {/* ── Chat area ── */}
      <div className="flex-1 flex flex-col overflow-hidden min-w-0">
        {/* Header */}
        <div className="px-6 py-4 border-b border-gray-200 bg-white flex-shrink-0">
          <h1 className="text-lg font-semibold text-gray-900">Research Chat</h1>
          <p className="text-xs text-gray-500 mt-0.5">
            Ask sourced questions about funds, rankings, rules, and data.
            AI explains pre-computed results — it never calculates metrics or gives investment advice.
          </p>
        </div>

        {/* Context banner (from Fund Detail / Compare) */}
        {contextBanner}

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          {messages.length === 0 && (
            <div className="text-center py-12">
              <div className="h-12 w-12 rounded-full bg-purple-100 flex items-center justify-center mx-auto mb-3">
                <Sparkles className="h-6 w-6 text-purple-500" />
              </div>
              <h2 className="text-base font-semibold text-gray-700 mb-1">
                Ask AltStreet anything about the fund universe
              </h2>
              <p className="text-sm text-gray-400 mb-6">
                AI explains pre-computed rankings and metrics — it does not provide investment advice.
              </p>
              <div className="flex flex-wrap gap-2 justify-center max-w-2xl mx-auto">
                {SUGGESTED_QUERIES.slice(0, 6).map(q => (
                  <button key={q} onClick={() => submit(q)}
                    className="text-xs bg-blue-50 text-blue-700 border border-blue-200 rounded-full px-3 py-1.5 hover:bg-blue-100 transition-colors">
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map(msg =>
            msg.role === "user"
              ? <UserMessage key={msg.id} msg={msg} />
              : <AssistantMessage key={msg.id} msg={msg} onSuggestClick={submit} />
          )}
          <div ref={bottomRef} />
        </div>

        {/* Input bar */}
        <div className="px-6 py-4 border-t border-gray-200 bg-white flex-shrink-0">
          <div className="flex items-center gap-3 bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus-within:border-blue-400 focus-within:bg-white transition-colors">
            <Sparkles className="h-4 w-4 text-purple-400 flex-shrink-0" />
            <input
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => e.key === "Enter" && !e.shiftKey && submit()}
              placeholder="Ask about funds, rankings, rules, or documents…"
              className="flex-1 bg-transparent outline-none text-sm text-gray-700 placeholder:text-gray-400"
            />
            <button onClick={() => submit()} disabled={!input.trim() || sendMutation.isPending}
              className={cn(
                "h-7 w-7 rounded-lg flex items-center justify-center transition-colors flex-shrink-0",
                input.trim() && !sendMutation.isPending
                  ? "bg-blue-600 text-white hover:bg-blue-700"
                  : "bg-gray-200 text-gray-400 cursor-not-allowed",
              )}>
              {sendMutation.isPending
                ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                : <Send className="h-3.5 w-3.5" />}
            </button>
          </div>
          <p className="text-[10px] text-gray-400 mt-1.5 text-center">
            AltStreet Research Chat uses pre-computed data only. All answers cite internal validated snapshots.
          </p>
        </div>
      </div>
    </div>
  )
}
