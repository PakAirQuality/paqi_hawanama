'use client'

import React from 'react'

// Use SVG's own coordinate system
const VIEWBOX_WIDTH = 800
const VIEWBOX_HEIGHT = 654

// TODO: paste your actual path from exported SVG here:

type StationStatus = 'healthy' | 'noisy' | 'failed'

interface Station {
  id: string
  name: string
  lat: number
  lng: number
  status: StationStatus
}

const statusColor: Record<StationStatus, string> = {
  healthy: '#16a34a',
  noisy: '#f59e0b',
  failed: '#dc2626',
}

// Bounds for simple lon/lat → x/y mapping
const MIN_LNG = 60.9
const MAX_LNG = 77.8
const MIN_LAT = 23.5
const MAX_LAT = 37.2

function project(lng: number, lat: number) {
  const x = ((lng - MIN_LNG) / (MAX_LNG - MIN_LNG)) * VIEWBOX_WIDTH
  const y = ((MAX_LAT - lat) / (MAX_LAT - MIN_LAT)) * VIEWBOX_HEIGHT
  return [x, y] as const
}

interface Props {
  networkPm25: number
  bandLabel: string
  worstCity: string
  worstValue: number
  bestCity: string
  bestValue: number
  aboveGuidelinePct: number
  stations: Station[]
}

export const RegionalHeroCard: React.FC<Props> = ({
  networkPm25,
  bandLabel,
  worstCity,
  worstValue,
  bestCity,
  bestValue,
  aboveGuidelinePct,
  stations,
}) => {
  // Load the complete Pakistan path from the extracted file
  const [pakistanPath, setPakistanPath] = React.useState<string>('')

  React.useEffect(() => {
    fetch('/pakistan_boundary_path.txt')
      .then(res => res.text())
      .then(path => setPakistanPath(path))
      .catch(err => console.error('Failed to load Pakistan path:', err))
  }, [])

  return (
  <div className="flex rounded-3xl bg-white shadow-sm border border-slate-100 p-8 gap-8">
    {/* Left: numbers */}
    <div className="flex-1 flex flex-col justify-between">
      <div>
        <h3 className="text-lg font-semibold text-slate-900">
          Air Quality Across South Asia
        </h3>

        <span className="inline-flex mt-4 items-center rounded-full bg-red-50 px-4 py-1 text-xs font-semibold tracking-wide text-red-600 uppercase">
          {bandLabel}
        </span>

        <div className="mt-5 flex items-baseline gap-2">
          <span className="text-5xl font-bold text-slate-900">
            {networkPm25.toFixed(1)}
          </span>
          <span className="text-2xl text-slate-500">µg/m³</span>
        </div>
        <p className="mt-1 text-xs text-slate-500">Network PM₂.₅ (1 h)</p>
      </div>

      <div className="mt-6 space-y-1 text-sm text-slate-700">
        <p>
          Worst city:{' '}
          <span className="font-semibold">{worstCity}</span>{' '}
          {worstValue.toFixed(0)} µg/m³
        </p>
        <p>
          Cleanest:{' '}
          <span className="font-semibold">{bestCity}</span>{' '}
          {bestValue.toFixed(0)} µg/m³
        </p>
        <p className="text-slate-500">
          Above WHO 24h guideline: {aboveGuidelinePct.toFixed(0)}% of stations
        </p>
      </div>
    </div>

    {/* Right: map */}
    <div className="flex flex-col items-center justify-center w-[260px]">
      <div className="rounded-xl bg-slate-50 border border-slate-200 p-3">
        <svg
          width="220"
          height="220"
          viewBox={`0 0 ${VIEWBOX_WIDTH} ${VIEWBOX_HEIGHT}`}
          className="w-[220px] h-[220px]"
        >
          {/* Pakistan silhouette */}
          {pakistanPath && (
            <path
              d={pakistanPath}
              fill="#e5e7eb"       // slate-200
              stroke="#9ca3af"     // slate-400
              strokeWidth={1}
            />
          )}

          {/* Stations */}
          {stations.map((s) => {
            const [x, y] = project(s.lng, s.lat)
            if (Number.isNaN(x) || Number.isNaN(y)) return null
            return (
              <circle
                key={s.id}
                cx={x}
                cy={y}
                r={8}
                fill={statusColor[s.status]}
                stroke="#ffffff"
                strokeWidth={1}
              />
            )
          })}
        </svg>
      </div>

      {/* Legend */}
      <div className="mt-4 flex gap-6 text-xs text-slate-700">
        <Legend color={statusColor.healthy} label="Healthy" />
        <Legend color={statusColor.noisy} label="Noisy" />
        <Legend color={statusColor.failed} label="Failed" />
      </div>
    </div>
  </div>
  )
}

const Legend: React.FC<{ color: string; label: string }> = ({ color, label }) => (
  <div className="flex items-center gap-1.5">
    <span
      className="inline-block h-2.5 w-2.5 rounded-full"
      style={{ backgroundColor: color }}
    />
    <span>{label}</span>
  </div>
)