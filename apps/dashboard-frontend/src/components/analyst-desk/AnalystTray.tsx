"use client"

import { useMemo } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell,
} from 'recharts'
import { BAND_COLORS, BAND_LABELS } from './utils'

export interface TrayStation {
  pm25: number | null
  band: string
  city: string
}

interface AnalystTrayProps {
  visible: boolean
  onClose: () => void
  stations: TrayStation[]
}

// ── Histogram bins matching risk_engine thresholds ──
const BINS = [
  { label: '0–35',   min: 0,   max: 35,  band: 'good' },
  { label: '35–75',  min: 35,  max: 75,  band: 'moderate' },
  { label: '75–150', min: 75,  max: 150, band: 'unhealthy' },
  { label: '150–250',min: 150, max: 250, band: 'very_unhealthy' },
  { label: '250+',   min: 250, max: Infinity, band: 'severe' },
]

const BAND_ORDER = ['good', 'moderate', 'unhealthy', 'very_unhealthy', 'severe']

// ── Standalone panel for copilot sidebar (single-column, scrollable) ──
export function AnalystPanel({ stations }: { stations: TrayStation[] }) {
  const histogramData = useMemo(() => {
    const counts = BINS.map(b => ({ ...b, count: 0 }))
    for (const s of stations) {
      if (s.pm25 == null) continue
      const idx = counts.findIndex(b => s.pm25! >= b.min && s.pm25! < b.max)
      if (idx >= 0) counts[idx].count++
    }
    return counts
  }, [stations])

  const donutData = useMemo(() => {
    const map: Record<string, number> = {}
    for (const s of stations) {
      map[s.band] = (map[s.band] || 0) + 1
    }
    return BAND_ORDER
      .filter(b => map[b])
      .map(b => ({ name: BAND_LABELS[b] || b, value: map[b], band: b }))
  }, [stations])

  const topCities = useMemo(() => {
    const cityMap: Record<string, { sum: number; count: number }> = {}
    for (const s of stations) {
      if (s.pm25 == null || !s.city) continue
      if (!cityMap[s.city]) cityMap[s.city] = { sum: 0, count: 0 }
      cityMap[s.city].sum += s.pm25
      cityMap[s.city].count++
    }
    return Object.entries(cityMap)
      .map(([city, { sum, count }]) => ({ city, mean: Math.round(sum / count) }))
      .sort((a, b) => b.mean - a.mean)
      .slice(0, 10)
  }, [stations])

  if (stations.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-slate-400 text-xs">
        No stations in current view
      </div>
    )
  }

  return (
    <div className="overflow-y-auto px-3 py-3 space-y-4">
      {/* PM2.5 Distribution */}
      <div>
        <p className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-1.5">PM2.5 Distribution</p>
        <div style={{ height: 160 }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={histogramData} margin={{ top: 4, right: 8, bottom: 0, left: -12 }}>
              <XAxis dataKey="label" tick={{ fontSize: 10 }} />
              <YAxis allowDecimals={false} tick={{ fontSize: 10 }} />
              <Tooltip
                formatter={(value: number) => [`${value} stations`, 'Count']}
                contentStyle={{ fontSize: 12, borderRadius: 8 }}
              />
              <Bar dataKey="count" radius={[3, 3, 0, 0]}>
                {histogramData.map((entry, i) => (
                  <Cell key={i} fill={BAND_COLORS[entry.band] || '#9ca3af'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Risk Bands */}
      <div>
        <p className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-1.5">Risk Bands</p>
        <div style={{ height: 180 }} className="relative">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={donutData}
                dataKey="value"
                nameKey="name"
                innerRadius="55%"
                outerRadius="80%"
                paddingAngle={2}
              >
                {donutData.map((entry, i) => (
                  <Cell key={i} fill={BAND_COLORS[entry.band] || '#9ca3af'} />
                ))}
              </Pie>
              <Tooltip
                formatter={(value: number, name: string) => [`${value}`, name]}
                contentStyle={{ fontSize: 12, borderRadius: 8 }}
              />
            </PieChart>
          </ResponsiveContainer>
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            <div className="text-center">
              <div className="text-lg font-bold text-slate-800">{stations.length}</div>
              <div className="text-[10px] text-slate-500">total</div>
            </div>
          </div>
        </div>
      </div>

      {/* Top Cities */}
      <div>
        <p className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-1.5">Top Cities (Mean PM2.5)</p>
        <div style={{ height: 200 }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={topCities} layout="vertical" margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
              <XAxis type="number" tick={{ fontSize: 10 }} />
              <YAxis dataKey="city" type="category" width={70} tick={{ fontSize: 9 }} />
              <Tooltip
                formatter={(value: number) => [`${value} µg/m³`, 'Mean PM2.5']}
                contentStyle={{ fontSize: 12, borderRadius: 8 }}
              />
              <Bar dataKey="mean" radius={[0, 3, 3, 0]}>
                {topCities.map((entry, i) => {
                  const band = entry.mean <= 35 ? 'good' : entry.mean <= 75 ? 'moderate' : entry.mean <= 150 ? 'unhealthy' : entry.mean <= 250 ? 'very_unhealthy' : 'severe'
                  return <Cell key={i} fill={BAND_COLORS[band] || '#9ca3af'} />
                })}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  )
}

export function AnalystTray({ visible, onClose, stations }: AnalystTrayProps) {
  // ── PM2.5 Histogram data ──
  const histogramData = useMemo(() => {
    const counts = BINS.map(b => ({ ...b, count: 0 }))
    for (const s of stations) {
      if (s.pm25 == null) continue
      const idx = counts.findIndex(b => s.pm25! >= b.min && s.pm25! < b.max)
      if (idx >= 0) counts[idx].count++
    }
    return counts
  }, [stations])

  // ── Risk Band Donut data ──
  const donutData = useMemo(() => {
    const map: Record<string, number> = {}
    for (const s of stations) {
      map[s.band] = (map[s.band] || 0) + 1
    }
    return BAND_ORDER
      .filter(b => map[b])
      .map(b => ({ name: BAND_LABELS[b] || b, value: map[b], band: b }))
  }, [stations])

  // ── Top Cities by mean PM2.5 ──
  const topCities = useMemo(() => {
    const cityMap: Record<string, { sum: number; count: number }> = {}
    for (const s of stations) {
      if (s.pm25 == null || !s.city) continue
      if (!cityMap[s.city]) cityMap[s.city] = { sum: 0, count: 0 }
      cityMap[s.city].sum += s.pm25
      cityMap[s.city].count++
    }
    return Object.entries(cityMap)
      .map(([city, { sum, count }]) => ({ city, mean: Math.round(sum / count) }))
      .sort((a, b) => b.mean - a.mean)
      .slice(0, 10)
  }, [stations])

  return (
    <div
      className={`absolute bottom-0 left-0 right-0 z-20 bg-white/95 backdrop-blur-md border-t border-slate-200 shadow-2xl transition-transform duration-300 ${
        visible ? 'translate-y-0' : 'translate-y-full'
      }`}
      style={{ height: '40%' }}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-slate-100">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-slate-800">Station Analytics</h3>
          <span className="text-xs text-slate-500 bg-slate-100 rounded-full px-2 py-0.5">
            {stations.length} stations
          </span>
        </div>
        <button
          onClick={onClose}
          className="p-1 rounded-md hover:bg-slate-100 text-slate-500 transition-colors"
        >
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </button>
      </div>

      {/* Charts */}
      {stations.length === 0 ? (
        <div className="flex items-center justify-center h-[calc(100%-44px)] text-slate-400 text-sm">
          No stations in current view
        </div>
      ) : (
        <div className="grid grid-cols-3 gap-4 p-4 h-[calc(100%-44px)]">
          {/* 1. PM2.5 Histogram */}
          <div className="flex flex-col min-h-0">
            <p className="text-xs font-medium text-slate-600 mb-1">PM2.5 Distribution</p>
            <div className="flex-1 min-h-0">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={histogramData} margin={{ top: 4, right: 8, bottom: 0, left: -12 }}>
                  <XAxis dataKey="label" tick={{ fontSize: 10 }} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 10 }} />
                  <Tooltip
                    formatter={(value: number) => [`${value} stations`, 'Count']}
                    contentStyle={{ fontSize: 12, borderRadius: 8 }}
                  />
                  <Bar dataKey="count" radius={[3, 3, 0, 0]}>
                    {histogramData.map((entry, i) => (
                      <Cell key={i} fill={BAND_COLORS[entry.band] || '#9ca3af'} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* 2. Risk Band Donut */}
          <div className="flex flex-col min-h-0">
            <p className="text-xs font-medium text-slate-600 mb-1">Risk Bands</p>
            <div className="flex-1 min-h-0 relative">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={donutData}
                    dataKey="value"
                    nameKey="name"
                    innerRadius="55%"
                    outerRadius="80%"
                    paddingAngle={2}
                  >
                    {donutData.map((entry, i) => (
                      <Cell key={i} fill={BAND_COLORS[entry.band] || '#9ca3af'} />
                    ))}
                  </Pie>
                  <Tooltip
                    formatter={(value: number, name: string) => [`${value}`, name]}
                    contentStyle={{ fontSize: 12, borderRadius: 8 }}
                  />
                </PieChart>
              </ResponsiveContainer>
              {/* Center label */}
              <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                <div className="text-center">
                  <div className="text-lg font-bold text-slate-800">{stations.length}</div>
                  <div className="text-[10px] text-slate-500">total</div>
                </div>
              </div>
            </div>
          </div>

          {/* 3. Top Cities horizontal bar */}
          <div className="flex flex-col min-h-0">
            <p className="text-xs font-medium text-slate-600 mb-1">Top Cities (Mean PM2.5)</p>
            <div className="flex-1 min-h-0">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={topCities} layout="vertical" margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                  <XAxis type="number" tick={{ fontSize: 10 }} />
                  <YAxis dataKey="city" type="category" width={70} tick={{ fontSize: 9 }} />
                  <Tooltip
                    formatter={(value: number) => [`${value} µg/m³`, 'Mean PM2.5']}
                    contentStyle={{ fontSize: 12, borderRadius: 8 }}
                  />
                  <Bar dataKey="mean" radius={[0, 3, 3, 0]}>
                    {topCities.map((entry, i) => {
                      const band = entry.mean <= 35 ? 'good' : entry.mean <= 75 ? 'moderate' : entry.mean <= 150 ? 'unhealthy' : entry.mean <= 250 ? 'very_unhealthy' : 'severe'
                      return <Cell key={i} fill={BAND_COLORS[band] || '#9ca3af'} />
                    })}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
