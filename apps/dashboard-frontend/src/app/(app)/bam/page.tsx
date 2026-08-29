'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { ArrowLeft, RefreshCw } from 'lucide-react'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'

const API_BASE = 'https://hawanama-152782825429.asia-south1.run.app'
const STATION_ID = 'bam_47c00c182e5d'

type TsPoint = { ts: string; pm25: number | null; flow: number | null; humidity: number | null; temp: number | null; pressure: number | null; wind: number | null }
type Timeseries = { minutes: number; downsampled: boolean; bucket_seconds: number; count: number; points: TsPoint[] }

async function fetchTimeseries(minutes: number): Promise<Timeseries> {
  const res = await fetch(`${API_BASE}/api/v1/internal/stations/${STATION_ID}/timeseries?minutes=${minutes}`)
  if (!res.ok) throw new Error('Failed to load time series')
  return res.json()
}

const CHANNELS = [
  { key: 'pm25', label: 'PM2.5', unit: 'µg/m³', color: '#dc2626' },
  { key: 'flow', label: 'Flow', unit: 'L/min', color: '#7c3aed' },
  { key: 'humidity', label: 'Humidity', unit: '%', color: '#0891b2' },
  { key: 'temp', label: 'Temp', unit: '°C', color: '#ea580c' },
  { key: 'pressure', label: 'Pressure', unit: 'hPa', color: '#65a30d' },
  { key: 'wind', label: 'Wind', unit: 'm/s', color: '#475569' },
] as const
const WINDOWS = [
  { label: '15m', minutes: 15 },
  { label: '1h', minutes: 60 },
  { label: '6h', minutes: 360 },
  { label: '24h', minutes: 1440 },
]

function LiveTimeSeries() {
  const [minutes, setMinutes] = useState(60)
  const [channel, setChannel] = useState<string>('pm25')
  const { data, isFetching } = useQuery({
    queryKey: ['bam-ts', minutes],
    queryFn: () => fetchTimeseries(minutes),
    refetchInterval: 15000,
  })
  const ch = CHANNELS.find(c => c.key === channel)!
  const fmtTime = (t: string) => {
    const d = new Date(t)
    if (isNaN(d.getTime())) return ''
    return minutes <= 15
      ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
      : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })
  }
  const points = data?.points ?? []
  return (
    <div className="bg-white border border-slate-200 rounded-xl p-4">
      <div className="flex items-center justify-between flex-wrap gap-2 mb-3">
        <div className="text-sm font-semibold text-slate-700">
          Live time series {data ? (data.downsampled ? `· ${data.bucket_seconds}s avg` : '· per-second') : ''}
          {isFetching ? <span className="text-slate-400 font-normal"> · updating…</span> : null}
        </div>
        <div className="flex gap-1">
          {WINDOWS.map(w => (
            <button key={w.minutes} onClick={() => setMinutes(w.minutes)}
              className={`text-xs px-2 py-1 rounded ${minutes === w.minutes ? 'bg-slate-800 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'}`}>
              {w.label}
            </button>
          ))}
        </div>
      </div>
      <div className="flex gap-1 flex-wrap mb-3">
        {CHANNELS.map(c => (
          <button key={c.key} onClick={() => setChannel(c.key)}
            className={`text-xs px-2 py-1 rounded border ${channel === c.key ? 'text-white border-transparent' : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'}`}
            style={channel === c.key ? { background: c.color } : undefined}>
            {c.label}
          </button>
        ))}
      </div>
      <div style={{ width: '100%', height: 280 }}>
        <ResponsiveContainer>
          <LineChart data={points} margin={{ top: 5, right: 10, left: -10, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
            <XAxis dataKey="ts" tickFormatter={fmtTime} minTickGap={60} tick={{ fontSize: 11, fill: '#64748b' }} />
            <YAxis tick={{ fontSize: 11, fill: '#64748b' }} width={44}
              label={{ value: ch.unit, angle: -90, position: 'insideLeft', style: { fontSize: 11, fill: '#94a3b8' } }} />
            <Tooltip
              labelFormatter={(t) => fmtTime(String(t))}
              formatter={(v: number | string) => [v == null ? '—' : `${v} ${ch.unit}`, ch.label]}
              contentStyle={{ fontSize: 12, borderRadius: 8 }} />
            <Line type="monotone" dataKey={channel} stroke={ch.color} dot={false} strokeWidth={1.5} isAnimationActive={false} connectNulls />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="text-xs text-slate-400 mt-2">
        {data ? `${data.count.toLocaleString()} points` : 'loading…'} · showing {ch.label} · auto-refresh 15s
      </div>
    </div>
  )
}

type Check = { key: string; label: string; status: 'pass' | 'warn' | 'fail'; value: number | null; detail: string }
type QcStatus = {
  station_id: string
  name: string
  provider: string | null
  lat: number
  lon: number
  window_hours: number
  current: {
    ts_utc: string | null
    age_seconds: number | null
    status: 'online' | 'delayed' | 'offline'
    pm25: number | null
    aqi_us: number | null
    temp_c: number | null
    humidity: number | null
    pressure_hpa: number | null
    wind_speed_ms: number | null
    wind_dir_deg: number | null
    flow: number | null
    qc_state: string | null
    qc_flags: string[]
  } | null
  stats24h: {
    n: number
    pm25_avg: number | null
    pm25_max: number | null
    coverage_pct: number
    invalid_rate_pct: number
    suspect_rate_pct: number
    high_rh_rate_pct: number
    flow_ok_rate_pct: number | null
    flow_avg: number | null
  }
  neighbors: { n: number; median: number | null; bam_median: number | null }
  series: { hour_utc: string; pm25: number | null }[]
  checks: Check[]
  verdict: { level: 'GREEN' | 'YELLOW' | 'RED'; headline: string; issues: string[] }
}

async function fetchQc(): Promise<QcStatus> {
  const res = await fetch(`${API_BASE}/api/v1/internal/stations/${STATION_ID}/qc-status?hours=24`)
  if (!res.ok) throw new Error('Failed to load BAM QC status')
  return res.json()
}

// ---- helpers ----
function pm25Band(v: number | null | undefined): { label: string; color: string; bg: string } {
  if (v == null) return { label: '—', color: '#64748b', bg: '#f1f5f9' }
  if (v <= 9) return { label: 'Good', color: '#16a34a', bg: '#dcfce7' }
  if (v <= 35.4) return { label: 'Moderate', color: '#ca8a04', bg: '#fef9c3' }
  if (v <= 55.4) return { label: 'Unhealthy (SG)', color: '#ea580c', bg: '#ffedd5' }
  if (v <= 125.4) return { label: 'Unhealthy', color: '#dc2626', bg: '#fee2e2' }
  if (v <= 225.4) return { label: 'Very Unhealthy', color: '#9333ea', bg: '#f3e8ff' }
  return { label: 'Hazardous', color: '#7f1d1d', bg: '#fee2e2' }
}

const VERDICT_STYLE: Record<string, { bg: string; fg: string; ring: string; label: string }> = {
  GREEN: { bg: '#dcfce7', fg: '#166534', ring: '#22c55e', label: 'HEALTHY' },
  YELLOW: { bg: '#fef9c3', fg: '#854d0e', ring: '#eab308', label: 'WATCH' },
  RED: { bg: '#fee2e2', fg: '#991b1b', ring: '#ef4444', label: 'PROBLEM' },
}

const CHECK_STYLE: Record<string, { dot: string; fg: string; text: string }> = {
  pass: { dot: '#22c55e', fg: '#166534', text: 'PASS' },
  warn: { dot: '#eab308', fg: '#854d0e', text: 'WARN' },
  fail: { dot: '#ef4444', fg: '#991b1b', text: 'FAIL' },
}

function statusPill(s: 'online' | 'delayed' | 'offline') {
  const m = {
    online: { bg: '#dcfce7', fg: '#166534', label: 'ONLINE' },
    delayed: { bg: '#fef9c3', fg: '#854d0e', label: 'DELAYED' },
    offline: { bg: '#fee2e2', fg: '#991b1b', label: 'OFFLINE' },
  }[s]
  return m
}

function ageText(s: number | null | undefined) {
  if (s == null) return 'no data'
  if (s < 90) return `${Math.round(s)}s ago`
  if (s < 5400) return `${Math.round(s / 60)}m ago`
  return `${Math.round(s / 3600)}h ago`
}

type LiveReading = {
  ts_utc: string; pm25: number | null; aqi_us: number | null; temp_c: number | null
  humidity: number | null; pressure_hpa: number | null; wind_speed_ms: number | null
  wind_dir_deg: number | null; qc_state: string | null; qc_flags: string[]
  raw: Record<string, unknown> | null; ingested_at: string | null
}
type LiveResp = { count: number; readings: LiveReading[] }

async function fetchLive(): Promise<LiveResp> {
  const res = await fetch(`${API_BASE}/api/v1/internal/stations/${STATION_ID}/live?limit=40`)
  if (!res.ok) throw new Error('Failed to load live feed')
  return res.json()
}

const QC_COLOR: Record<string, string> = { OK: '#16a34a', SUSPECT: '#ca8a04', INVALID: '#dc2626' }

function fmtClock(t: string | null) {
  if (!t) return '—'
  const d = new Date(t)
  return isNaN(d.getTime()) ? '—' : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
}

function LiveRawFeed() {
  const { data, isFetching } = useQuery({
    queryKey: ['bam-live'],
    queryFn: fetchLive,
    refetchInterval: 2000,
  })
  const readings = data?.readings ?? []
  const latest = readings[0]
  return (
    <div className="bg-white border border-slate-200 rounded-xl p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="text-sm font-semibold text-slate-700">Live raw feed</div>
        <span className="flex items-center gap-1.5 text-[11px] font-semibold text-emerald-600">
          <span className={`w-2 h-2 rounded-full bg-emerald-500 ${isFetching ? 'animate-ping' : 'animate-pulse'}`} />
          LIVE · every 2s
        </span>
      </div>
      <div className="grid md:grid-cols-2 gap-3">
        {/* Latest raw reading as JSON — the actual payload from BAM */}
        <div>
          <div className="text-xs text-slate-500 mb-1">Latest reading (raw JSON)</div>
          <pre className="text-[11px] leading-relaxed bg-slate-900 text-emerald-300 rounded-lg p-3 overflow-auto max-h-80 font-mono">
{latest ? JSON.stringify(latest, null, 2) : 'waiting for data…'}
          </pre>
        </div>
        {/* Ticking log of recent readings */}
        <div>
          <div className="text-xs text-slate-500 mb-1">Recent readings ({readings.length})</div>
          <div className="bg-slate-50 rounded-lg border border-slate-200 max-h-80 overflow-auto divide-y divide-slate-100">
            {readings.map((r, i) => (
              <div key={r.ts_utc ?? i} className="flex items-center gap-2 px-3 py-1.5 text-xs font-mono">
                <span className="text-slate-400 w-16">{fmtClock(r.ts_utc)}</span>
                <span className="text-slate-800 w-16">{r.pm25 != null ? `${r.pm25}` : '—'} <span className="text-slate-400">µg</span></span>
                <span className="text-slate-500 w-14">flow {String((r.raw as any)?.flow ?? '—')}</span>
                <span className="ml-auto font-semibold" style={{ color: QC_COLOR[r.qc_state ?? ''] ?? '#64748b' }}>
                  {r.qc_state ?? '—'}
                </span>
              </div>
            ))}
            {!readings.length && <div className="px-3 py-2 text-xs text-slate-400">waiting for data…</div>}
          </div>
        </div>
      </div>
    </div>
  )
}

export default function BamMonitorPage() {
  const router = useRouter()
  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ['bam-qc'],
    queryFn: fetchQc,
    refetchInterval: 20000,
  })

  if (isLoading) {
    return <div className="p-8 text-slate-500">Loading BAM monitor…</div>
  }
  if (error || !data) {
    return (
      <div className="p-8">
        <button onClick={() => router.push('/')} className="text-sm text-slate-500 mb-4 flex items-center gap-1">
          <ArrowLeft size={14} /> Back
        </button>
        <div className="text-red-600">Failed to load BAM QC status.</div>
      </div>
    )
  }

  const cur = data.current
  const band = pm25Band(cur?.pm25)
  const v = VERDICT_STYLE[data.verdict.level] ?? VERDICT_STYLE.YELLOW
  const st = statusPill(cur?.status ?? 'offline')
  const s24 = data.stats24h

  return (
    <div className="max-w-5xl mx-auto p-4 lg:p-6 space-y-4">
      {/* Back + refresh */}
      <div className="flex items-center justify-between">
        <button onClick={() => router.push('/')} className="text-sm text-slate-500 hover:text-slate-800 flex items-center gap-1">
          <ArrowLeft size={14} /> Air Quality Tracker
        </button>
        <button onClick={() => refetch()} className="text-sm text-slate-500 hover:text-slate-800 flex items-center gap-1">
          <RefreshCw size={13} className={isFetching ? 'animate-spin' : ''} /> Refresh
        </button>
      </div>

      {/* Verdict banner */}
      <div className="rounded-xl border p-4 flex items-center gap-4" style={{ background: v.bg, borderColor: v.ring }}>
        <div className="w-3 h-3 rounded-full" style={{ background: v.ring }} />
        <div className="flex-1">
          <div className="text-xs font-bold tracking-wide" style={{ color: v.fg }}>{v.label}</div>
          <div className="text-sm font-medium" style={{ color: v.fg }}>{data.verdict.headline}</div>
        </div>
      </div>

      {/* Header + current reading */}
      <div className="bg-white border border-slate-200 rounded-xl p-4 flex items-start justify-between flex-wrap gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-semibold text-slate-900">{data.name}</h1>
            <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full" style={{ background: st.bg, color: st.fg }}>{st.label}</span>
          </div>
          <div className="text-sm text-slate-500 mt-0.5">
            {data.provider ?? 'SFL BAM Network'} · {data.lat.toFixed(4)}, {data.lon.toFixed(4)} · reference monitor
          </div>
          <div className="text-xs text-slate-400 mt-1">Last reading {ageText(cur?.age_seconds)}</div>
        </div>
        <div className="text-right">
          <div className="text-4xl font-bold" style={{ color: band.color }}>
            {cur?.pm25 != null ? cur.pm25.toFixed(1) : '—'}
          </div>
          <div className="text-xs text-slate-500">µg/m³ PM2.5</div>
          <span className="inline-block mt-1 text-[11px] font-semibold px-2 py-0.5 rounded-full" style={{ background: band.bg, color: band.color }}>{band.label}</span>
        </div>
      </div>

      {/* 24h stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="24h Avg" value={s24.pm25_avg != null ? `${s24.pm25_avg}` : '—'} unit="µg/m³" />
        <StatCard label="24h Max" value={s24.pm25_max != null ? `${s24.pm25_max}` : '—'} unit="µg/m³" />
        <StatCard label="Coverage" value={`${s24.coverage_pct}`} unit="% of 24h" />
        <StatCard label="Invalid" value={`${s24.invalid_rate_pct}`} unit="% flagged" />
      </div>

      {/* Live per-second time series */}
      <LiveTimeSeries />

      {/* Live raw feed (JSON ticking every ~2s) */}
      <LiveRawFeed />

      {/* QC checks */}
      <div className="bg-white border border-slate-200 rounded-xl p-4">
        <div className="text-sm font-semibold text-slate-700 mb-3">Data Quality Checks</div>
        <div className="space-y-2">
          {data.checks.map((c) => {
            const cs = CHECK_STYLE[c.status]
            return (
              <div key={c.key} className="flex items-center gap-3 py-1.5 border-b border-slate-100 last:border-0">
                <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: cs.dot }} />
                <div className="flex-1">
                  <div className="text-sm font-medium text-slate-800">{c.label}</div>
                  <div className="text-xs text-slate-500">{c.detail}</div>
                </div>
                <span className="text-[11px] font-bold" style={{ color: cs.fg }}>{cs.text}</span>
              </div>
            )
          })}
        </div>
      </div>

      {/* Latest sensor channels */}
      <div className="bg-white border border-slate-200 rounded-xl p-4">
        <div className="text-sm font-semibold text-slate-700 mb-3">Latest Sensor Channels</div>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-x-6 gap-y-2 text-sm">
          <Channel label="Flow" value={cur?.flow != null ? `${cur.flow} L/min` : '—'} />
          <Channel label="Humidity" value={cur?.humidity != null ? `${cur.humidity}%` : '—'} />
          <Channel label="Temperature" value={cur?.temp_c != null ? `${cur.temp_c} °C` : '—'} />
          <Channel label="Pressure" value={cur?.pressure_hpa != null ? `${cur.pressure_hpa} hPa` : '—'} />
          <Channel label="Wind" value={cur?.wind_speed_ms != null ? `${cur.wind_speed_ms} m/s` : '—'} />
          <Channel label="US AQI" value={cur?.aqi_us != null ? `${cur.aqi_us}` : '—'} />
        </div>
        {cur?.qc_flags?.length ? (
          <div className="mt-3 text-xs text-slate-500">
            Latest flags: {cur.qc_flags.map(f => (
              <span key={f} className="inline-block bg-slate-100 text-slate-600 rounded px-1.5 py-0.5 mr-1 font-mono">{f}</span>
            ))}
          </div>
        ) : null}
      </div>

      <div className="text-xs text-slate-400 text-center pb-4">
        Auto-refreshes every 20s · window {data.window_hours}h · {s24.n.toLocaleString()} readings
      </div>
    </div>
  )
}

function StatCard({ label, value, unit }: { label: string; value: string; unit: string }) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl p-3">
      <div className="text-lg font-bold text-slate-900">{value}</div>
      <div className="text-xs text-slate-500">{label} · {unit}</div>
    </div>
  )
}

function Channel({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between border-b border-slate-100 pb-1">
      <span className="text-slate-500">{label}</span>
      <span className="text-slate-800 font-medium">{value}</span>
    </div>
  )
}
