import { useState } from "react"
import { NavLink, Outlet, useNavigate } from "react-router-dom"
import {
  Home, BarChart2, TrendingUp, GitCompare,
  Sliders, Bell, ChevronDown, Sparkles,
  ChevronsLeft, ChevronsRight, Activity,
  MessageSquare, ShieldCheck, Database, BrainCircuit,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { Toaster } from "@/components/ui/toaster"
import { useQuery } from "@tanstack/react-query"
import { healthApi } from "@/lib/api"
import { queryKeys } from "@/lib/query-keys"

interface NavItem {
  to: string
  label: string
  icon: React.ComponentType<{ className?: string }>
  end?: boolean
}

const NAV: NavItem[] = [
  { to: "/", label: "Home", icon: Home, end: true },
  { to: "/rankings", label: "Category Rankings", icon: BarChart2 },
  { to: "/funds", label: "Fund Detail", icon: TrendingUp },
  { to: "/compare", label: "Fund Comparison", icon: GitCompare },
  { to: "/chat", label: "Research Chat", icon: MessageSquare },
  { to: "/workspace", label: "AI Workspace", icon: BrainCircuit },
  { to: "/rule-playground", label: "Rule Playground", icon: Sliders },
  { to: "/rule-approval", label: "Rule Approval", icon: ShieldCheck },
  { to: "/data-quality", label: "Data Quality", icon: Database },
]

export function Layout() {
  const [collapsed, setCollapsed] = useState(false)
  const navigate = useNavigate()

  const { data: health } = useQuery({
    queryKey: queryKeys.health,
    queryFn: healthApi.getHealth,
    refetchInterval: 30_000,
  })
  const apiOnline = health?.status === "ok"

  return (
    <div className="flex h-screen overflow-hidden bg-[#F5F4F1]">
      {/* ── Sidebar ── */}
      <aside
        className={cn(
          "flex flex-col bg-white border-r border-gray-200 transition-all duration-200 flex-shrink-0 z-20",
          collapsed ? "w-[52px]" : "w-[210px]",
        )}
      >
        {/* Logo */}
        <div
          className={cn(
            "flex items-center gap-2.5 px-3 py-4 border-b border-gray-100",
            collapsed && "justify-center px-0",
          )}
        >
          <div className="h-7 w-7 rounded-md bg-blue-600 flex items-center justify-center text-white font-bold text-[10px] flex-shrink-0">
            AS
          </div>
          {!collapsed && (
            <span className="font-semibold text-gray-900 text-sm tracking-tight">
              AltStreet
            </span>
          )}
        </div>

        {/* Nav items */}
        <nav className="flex-1 py-2 px-1.5 space-y-0.5 overflow-y-auto">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              title={collapsed ? label : undefined}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-sm font-medium transition-colors",
                  isActive
                    ? "bg-blue-50 text-blue-700"
                    : "text-gray-600 hover:bg-gray-50 hover:text-gray-900",
                  collapsed && "justify-center px-0",
                )
              }
            >
              <Icon className="h-[15px] w-[15px] flex-shrink-0" />
              {!collapsed && <span className="truncate">{label}</span>}
            </NavLink>
          ))}
        </nav>

        {/* AI Engine status */}
        <div className="px-3 py-3 border-t border-gray-100">
          {!collapsed ? (
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <span
                  className={cn(
                    "h-2 w-2 rounded-full flex-shrink-0",
                    apiOnline ? "bg-green-500" : "bg-amber-400",
                  )}
                />
                <span className="text-[11px] text-gray-500 leading-tight">
                  AltStreet AI Engine
                </span>
              </div>
              <button
                onClick={() => setCollapsed(true)}
                className="text-gray-400 hover:text-gray-600"
              >
                <ChevronsLeft className="h-3.5 w-3.5" />
              </button>
            </div>
          ) : (
            <div className="flex flex-col items-center gap-1.5">
              <span
                className={cn(
                  "h-2 w-2 rounded-full",
                  apiOnline ? "bg-green-500" : "bg-amber-400",
                )}
              />
              <button
                onClick={() => setCollapsed(false)}
                className="text-gray-400 hover:text-gray-600"
              >
                <ChevronsRight className="h-3.5 w-3.5" />
              </button>
            </div>
          )}
        </div>
      </aside>

      {/* ── Main ── */}
      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        {/* Topbar */}
        <header className="h-[52px] bg-white border-b border-gray-200 flex items-center px-4 gap-4 flex-shrink-0">
          {/* Team selector */}
          <button className="flex items-center gap-2 bg-blue-50 text-blue-700 rounded-lg px-3 py-1.5 text-xs font-medium hover:bg-blue-100 transition-colors flex-shrink-0">
            <Activity className="h-3.5 w-3.5" />
            <span>Investment Team</span>
            <ChevronDown className="h-3 w-3 opacity-60" />
          </button>

          {/* Global search / command bar */}
          <button
            className="flex-1 max-w-[480px] flex items-center gap-2 bg-gray-50 border border-gray-200 rounded-lg px-3 py-2 text-left hover:border-blue-300 hover:bg-blue-50/30 transition-colors"
            onClick={() => navigate("/")}
          >
            <Sparkles className="h-3.5 w-3.5 text-purple-500 flex-shrink-0" />
            <span className="text-xs text-gray-400 flex-1">
              Search or ask AltStreet…
            </span>
            <kbd className="text-[10px] text-gray-400 font-mono bg-white border border-gray-200 rounded px-1.5 py-0.5">
              ⌘ K
            </kbd>
          </button>

          <div className="ml-auto flex items-center gap-3">
            {/* Notifications */}
            <button className="relative text-gray-500 hover:text-gray-700">
              <Bell className="h-[18px] w-[18px]" />
              <span className="absolute -top-1 -right-1 h-[14px] w-[14px] bg-red-500 rounded-full text-white text-[9px] font-semibold flex items-center justify-center">
                2
              </span>
            </button>

            {/* Avatar */}
            <div className="h-7 w-7 rounded-full bg-blue-600 flex items-center justify-center text-white text-[11px] font-semibold cursor-pointer select-none">
              SC
            </div>
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>

      <Toaster />
    </div>
  )
}
