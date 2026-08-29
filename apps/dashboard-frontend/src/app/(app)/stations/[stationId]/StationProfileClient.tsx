"use client"

import { useRef, useEffect, useState, useMemo } from "react"
import { useRouter, useParams } from "next/navigation"
import { useQuery } from "@tanstack/react-query"
import { ArrowLeft, MapPin, TrendingUp, TrendingDown, Minus } from "lucide-react"
import { OverviewPanel } from "@/components/stations/panels/OverviewPanel"
import { UptimePanel } from "@/components/stations/panels/UptimePanel"
import { DiurnalPanel } from "@/components/stations/panels/DiurnalPanel"
import { EpisodesPanel } from "@/components/stations/panels/EpisodesPanel"

const API_BASE = "https://hawanama-152782825429.asia-south1.run.app"

// ── Types ──

interface StationOverview {
  station: {
    station_id: string
    name: string
    provider: string
    source_station_id: string | null
    country: string | null
    state: string | null
    city: string | null
    lat: number | null
    lon: number | null
    site_type: string | null
    indoor_outdoor: string | null
    height_m: number | null
    distance_to_road_m: number | null
    timezone: string | null
    metadata: Record<string, unknown>
  }
  data_availability: {
    first_obs: string | null
    last_obs: string | null
    total_days_with_any_data: number | null
    coverage_last_365d_pct: number | null
    hours_total: number | null
    hours_with_data: number | null
    hours_qc_ok: number | null
  }
  pollutant_summary: {
    last_value: number | null
    last_value_ts: string | null
    rolling_means: { "24h": number | null; "7d": number | null; "30d": number | null } | null
  } | null
}

interface HistoryPoint {
  timestamp_utc: string
  timestamp_pk?: string
  pm25?: number | null
  aqi_us?: number | null
}

// ── Helpers ──

function pm25Band(v: number): { label: string; color: string; bg: string } {
  if (v <= 12) return { label: "Good", color: "#16a34a", bg: "#dcfce7" }
  if (v <= 35) return { label: "Moderate", color: "#ca8a04", bg: "#fef9c3" }
  if (v <= 55) return { label: "USG", color: "#ea580c", bg: "#ffedd5" }
  if (v <= 150) return { label: "Unhealthy", color: "#dc2626", bg: "#fee2e2" }
  if (v <= 250) return { label: "Very Unhealthy", color: "#7c3aed", bg: "#ede9fe" }
  return { label: "Hazardous", color: "#991b1b", bg: "#fecaca" }
}

function timeAgo(ts: string): string {
  const diff = Date.now() - new Date(ts).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  return `${days}d ago`
}

function statusBadge(lastObs: string | null): { label: string; color: string } {
  if (!lastObs) return { label: "Unknown", color: "#6b7280" }
  const hrs = (Date.now() - new Date(lastObs).getTime()) / 3600000
  if (hrs < 3) return { label: "Online", color: "#16a34a" }
  if (hrs < 24) return { label: "Delayed", color: "#ca8a04" }
  return { label: "Offline", color: "#dc2626" }
}

// ── API ──

async function fetchOverview(id: string): Promise<StationOverview> {
  const res = await fetch(`${API_BASE}/api/v1/internal/stations/${id}/overview`)
  if (!res.ok) throw new Error("Failed to load station overview")
  return res.json()
}

async function fetchHistory(id: string, hours: number): Promise<HistoryPoint[]> {
  const res = await fetch(`${API_BASE}/api/v1/dashboard/stations/${id}/history/pm25?hours=${hours}`)
  if (!res.ok) throw new Error("Failed to load history")
  return res.json()
}

// ── 24h Chart (canvas-based, no deps) ──

function PM25Chart({ data, hours }: { data: HistoryPoint[]; hours: number }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || !data.length) return
    const ctx = canvas.getContext("2d")
    if (!ctx) return

    const dpr = window.devicePixelRatio || 1
    const W = canvas.clientWidth
    const H = canvas.clientHeight
    canvas.width = W * dpr
    canvas.height = H * dpr
    ctx.scale(dpr, dpr)

    const pad = { top: 20, right: 16, bottom: 32, left: 44 }
    const w = W - pad.left - pad.right
    const h = H - pad.top - pad.bottom

    const points = data.map(d => ({
      ts: new Date(d.timestamp_utc).getTime(),
      val: d.pm25 ?? null,
    }))

    const validVals = points.filter(p => p.val !== null).map(p => p.val!)
    if (!validVals.length) {
      ctx.fillStyle = "#94a3b8"
      ctx.font = "13px system-ui"
      ctx.textAlign = "center"
      ctx.fillText("No data available", W / 2, H / 2)
      return
    }

    const minTs = points[0].ts
    const maxTs = points[points.length - 1].ts
    const maxVal = Math.max(...validVals, 50)
    const minVal = 0

    const xScale = (ts: number) => pad.left + ((ts - minTs) / (maxTs - minTs)) * w
    const yScale = (v: number) => pad.top + h - ((v - minVal) / (maxVal - minVal)) * h

    // Background bands
    const bands = [
      { max: 12, color: "rgba(22,163,106,0.06)" },
      { max: 35, color: "rgba(202,138,4,0.06)" },
      { max: 55, color: "rgba(234,88,12,0.06)" },
      { max: 150, color: "rgba(220,38,38,0.06)" },
    ]
    for (const band of bands) {
      if (band.max < maxVal) {
        const y1 = yScale(Math.min(band.max, maxVal))
        const y0 = yScale(band.max === 12 ? 0 : bands[bands.indexOf(band) - 1]?.max ?? 0)
        ctx.fillStyle = band.color
        ctx.fillRect(pad.left, y1, w, y0 - y1)
      }
    }

    // Grid lines
    ctx.strokeStyle = "#e2e8f0"
    ctx.lineWidth = 0.5
    const yTicks = [0, 25, 50, 75, 100, 150, 200].filter(v => v <= maxVal * 1.1)
    for (const v of yTicks) {
      const y = yScale(v)
      ctx.beginPath()
      ctx.moveTo(pad.left, y)
      ctx.lineTo(pad.left + w, y)
      ctx.stroke()
      ctx.fillStyle = "#94a3b8"
      ctx.font = "10px system-ui"
      ctx.textAlign = "right"
      ctx.fillText(String(v), pad.left - 6, y + 3)
    }

    // X-axis labels
    ctx.fillStyle = "#94a3b8"
    ctx.font = "10px system-ui"
    ctx.textAlign = "center"
    const labelCount = hours <= 24 ? 6 : hours <= 72 ? 6 : 7
    for (let i = 0; i <= labelCount; i++) {
      const ts = minTs + (i / labelCount) * (maxTs - minTs)
      const d = new Date(ts)
      const label = hours <= 24
        ? d.toLocaleTimeString("en-US", { hour: "numeric", hour12: true })
        : d.toLocaleDateString("en-US", { month: "short", day: "numeric" })
      ctx.fillText(label, xScale(ts), pad.top + h + 18)
    }

    // Line
    ctx.strokeStyle = "#3b82f6"
    ctx.lineWidth = 1.5
    ctx.lineJoin = "round"
    ctx.beginPath()
    let started = false
    for (const p of points) {
      if (p.val === null) { started = false; continue }
      const x = xScale(p.ts)
      const y = yScale(p.val)
      if (!started) { ctx.moveTo(x, y); started = true }
      else ctx.lineTo(x, y)
    }
    ctx.stroke()

    // Fill under line
    if (started) {
      ctx.lineTo(xScale(points[points.length - 1].ts), yScale(0))
      ctx.lineTo(xScale(points[0].ts), yScale(0))
      ctx.closePath()
      ctx.fillStyle = "rgba(59,130,246,0.08)"
      ctx.fill()
    }

    // Dots for each valid point
    for (const p of points) {
      if (p.val === null) continue
      ctx.beginPath()
      ctx.arc(xScale(p.ts), yScale(p.val), 2, 0, Math.PI * 2)
      ctx.fillStyle = "#3b82f6"
      ctx.fill()
    }
  }, [data, hours])

  return (
    <canvas
      ref={canvasRef}
      className="w-full"
      style={{ height: 240 }}
    />
  )
}

// ── Tab type ──
type TabKey = "overview" | "uptime" | "diurnal" | "episodes"

// ── Page ──

export function StationProfileClient() {
  const router = useRouter()
  const { stationId } = useParams() as { stationId: string }

  const [historyHours, setHistoryHours] = useState(24)
  const [activeTab, setActiveTab] = useState<TabKey>("overview")

  const { data: overview, isLoading: overviewLoading } = useQuery({
    queryKey: ["station-overview", stationId],
    queryFn: () => fetchOverview(stationId),
    enabled: !!stationId,
  })

  const { data: history, isLoading: historyLoading } = useQuery({
    queryKey: ["station-history", stationId, historyHours],
    queryFn: () => fetchHistory(stationId, historyHours),
    enabled: !!stationId,
  })

  const station = overview?.station
  const avail = overview?.data_availability
  const poll = overview?.pollutant_summary
  const status = statusBadge(avail?.last_obs ?? null)

  // Compute 24h stats from history
  const historyStats = useMemo(() => {
    if (!history?.length) return null
    const vals = history.filter(h => h.pm25 != null).map(h => h.pm25!)
    if (!vals.length) return null
    const mean = vals.reduce((a, b) => a + b, 0) / vals.length
    const max = Math.max(...vals)
    const min = Math.min(...vals)
    const validHours = vals.length
    const totalHours = history.length
    return { mean, max, min, validHours, totalHours }
  }, [history])

  if (overviewLoading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="flex items-center gap-2 text-sm text-slate-500">
          <div className="w-4 h-4 border-2 border-slate-300 border-t-slate-600 rounded-full animate-spin" />
          Loading station...
        </div>
      </div>
    )
  }

  if (!overview || !station) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center">
          <p className="text-lg font-medium text-slate-700">Station not found</p>
          <p className="text-sm text-slate-500 mt-1">{stationId}</p>
          <button onClick={() => router.back()} className="mt-4 text-sm text-blue-600 hover:underline">
            Go back
          </button>
        </div>
      </div>
    )
  }

  const currentPM25 = poll?.last_value
  const band = currentPM25 != null ? pm25Band(currentPM25) : null

  // Trend: compare 24h mean to 7d mean
  const trend = (() => {
    const m24 = poll?.rolling_means?.["24h"]
    const m7d = poll?.rolling_means?.["7d"]
    if (m24 == null || m7d == null) return null
    const diff = m24 - m7d
    if (Math.abs(diff) < 2) return { dir: "flat" as const, diff }
    return { dir: diff > 0 ? "up" as const : "down" as const, diff }
  })()

  const TABS: { key: TabKey; label: string }[] = [
    { key: "overview", label: "Details" },
    { key: "uptime", label: "Uptime" },
    { key: "diurnal", label: "Diurnal" },
    { key: "episodes", label: "Episodes" },
  ]

  return (
    <div className="flex-1 overflow-y-auto bg-slate-50">
      {/* ── Top bar ── */}
      <div className="bg-white border-b border-slate-200 sticky top-0 z-10">
        <div className="max-w-6xl mx-auto px-6 py-3 flex items-center gap-4">
          <button
            onClick={() => router.back()}
            className="p-1.5 rounded-lg hover:bg-slate-100 transition-colors"
          >
            <ArrowLeft size={18} className="text-slate-500" />
          </button>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <h1 className="text-lg font-bold text-slate-900 truncate">{station.name}</h1>
              <span
                className="shrink-0 px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase"
                style={{ color: status.color, background: status.color + "18" }}
              >
                {status.label}
              </span>
            </div>
            <div className="flex items-center gap-2 text-xs text-slate-500 mt-0.5">
              <MapPin size={11} />
              <span>{[station.city, station.state, station.country].filter(Boolean).join(" · ")}</span>
              {station.provider && (
                <>
                  <span className="text-slate-300">·</span>
                  <span>{station.provider}</span>
                </>
              )}
            </div>
          </div>

          {/* Current reading badge */}
          {band && currentPM25 != null && (
            <div className="shrink-0 flex items-center gap-3 px-4 py-2 rounded-xl" style={{ background: band.bg }}>
              <div>
                <div className="text-2xl font-bold tabular-nums" style={{ color: band.color }}>
                  {Math.round(currentPM25)}
                </div>
                <div className="text-[10px] text-slate-500">µg/m³</div>
              </div>
              <div className="text-right">
                <div className="text-xs font-semibold" style={{ color: band.color }}>{band.label}</div>
                {poll?.last_value_ts && (
                  <div className="text-[10px] text-slate-400">{timeAgo(poll.last_value_ts)}</div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-6 py-6 space-y-6">
        {/* ── Status cards ── */}
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
          <StatCard
            label="Latest PM2.5"
            value={currentPM25 != null ? `${Math.round(currentPM25)}` : "—"}
            unit="µg/m³"
            color={band?.color}
          />
          <StatCard
            label="24h Average"
            value={poll?.rolling_means?.["24h"] != null ? `${Math.round(poll.rolling_means["24h"])}` : "—"}
            unit="µg/m³"
          />
          <StatCard
            label="24h Max"
            value={historyStats ? `${Math.round(historyStats.max)}` : "—"}
            unit="µg/m³"
          />
          <StatCard
            label="7d Average"
            value={poll?.rolling_means?.["7d"] != null ? `${Math.round(poll.rolling_means["7d"])}` : "—"}
            unit="µg/m³"
          />
          <StatCard
            label="Trend vs 7d"
            value={trend ? `${trend.diff > 0 ? "+" : ""}${Math.round(trend.diff)}` : "—"}
            unit="µg/m³"
            icon={trend?.dir === "up" ? <TrendingUp size={14} className="text-red-500" /> : trend?.dir === "down" ? <TrendingDown size={14} className="text-green-500" /> : <Minus size={14} className="text-slate-400" />}
          />
          <StatCard
            label="Completeness"
            value={historyStats ? `${Math.round((historyStats.validHours / historyStats.totalHours) * 100)}` : avail?.coverage_last_365d_pct != null ? `${Math.round(avail.coverage_last_365d_pct)}` : "—"}
            unit="%"
          />
        </div>

        {/* ── Trend chart ── */}
        <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
          <div className="px-5 py-3 border-b border-slate-100 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-800">PM2.5 Trend</h2>
            <div className="flex gap-1">
              {[
                { h: 24, label: "24h" },
                { h: 72, label: "3d" },
                { h: 168, label: "7d" },
              ].map(opt => (
                <button
                  key={opt.h}
                  onClick={() => setHistoryHours(opt.h)}
                  className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
                    historyHours === opt.h
                      ? "bg-slate-800 text-white"
                      : "text-slate-500 hover:bg-slate-100"
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>
          <div className="p-4">
            {historyLoading ? (
              <div className="h-[240px] flex items-center justify-center text-sm text-slate-400">
                Loading...
              </div>
            ) : history?.length ? (
              <PM25Chart data={history} hours={historyHours} />
            ) : (
              <div className="h-[240px] flex items-center justify-center text-sm text-slate-400">
                No history data available
              </div>
            )}
          </div>
        </div>

        {/* ── Tabbed panels ── */}
        <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
          <div className="border-b border-slate-200 px-5">
            <div className="flex gap-5">
              {TABS.map(({ key, label }) => (
                <button
                  key={key}
                  onClick={() => setActiveTab(key)}
                  className={`py-3 text-sm font-medium border-b-2 transition-colors ${
                    activeTab === key
                      ? "border-slate-800 text-slate-800"
                      : "border-transparent text-slate-400 hover:text-slate-600"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
          <div className="p-5">
            {activeTab === "overview" && <OverviewPanel stationId={stationId} />}
            {activeTab === "uptime" && <UptimePanel stationId={stationId} />}
            {activeTab === "diurnal" && <DiurnalPanel stationId={stationId} />}
            {activeTab === "episodes" && <EpisodesPanel stationId={stationId} />}
          </div>
        </div>

        {/* ── Metadata ── */}
        <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
          <div className="px-5 py-3 border-b border-slate-100">
            <h2 className="text-sm font-semibold text-slate-800">Metadata</h2>
          </div>
          <div className="p-5 grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-y-4 gap-x-8 text-sm">
            <MetaField label="Station ID" value={station.station_id} />
            <MetaField label="Source ID" value={station.source_station_id} />
            <MetaField label="Provider" value={station.provider} />
            <MetaField label="Network" value={station.site_type} />
            <MetaField label="Latitude" value={station.lat?.toFixed(5)} />
            <MetaField label="Longitude" value={station.lon?.toFixed(5)} />
            <MetaField label="City" value={station.city} />
            <MetaField label="Province" value={station.state} />
            <MetaField label="Country" value={station.country} />
            <MetaField label="Timezone" value={station.timezone} />
            <MetaField label="Indoor/Outdoor" value={station.indoor_outdoor} />
            <MetaField label="Height" value={station.height_m != null ? `${station.height_m} m` : null} />
            <MetaField label="Distance to Road" value={station.distance_to_road_m != null ? `${station.distance_to_road_m} m` : null} />
            <MetaField label="First Observation" value={avail?.first_obs ? new Date(avail.first_obs).toLocaleDateString() : null} />
            <MetaField label="Last Observation" value={avail?.last_obs ? new Date(avail.last_obs).toLocaleDateString() : null} />
            <MetaField label="Days with Data" value={avail?.total_days_with_any_data?.toString()} />
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Subcomponents ──

function StatCard({ label, value, unit, color, icon }: { label: string; value: string; unit?: string; color?: string; icon?: React.ReactNode }) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 px-4 py-3">
      <div className="text-[10px] font-medium text-slate-400 uppercase tracking-wide">{label}</div>
      <div className="mt-1 flex items-baseline gap-1">
        {icon && <span className="mr-0.5">{icon}</span>}
        <span className="text-xl font-bold tabular-nums" style={{ color: color ?? "#1e293b" }}>{value}</span>
        {unit && value !== "—" && <span className="text-xs text-slate-400">{unit}</span>}
      </div>
    </div>
  )
}

function MetaField({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div>
      <div className="text-xs text-slate-400">{label}</div>
      <div className="text-sm font-medium text-slate-700 mt-0.5">{value ?? "—"}</div>
    </div>
  )
}
