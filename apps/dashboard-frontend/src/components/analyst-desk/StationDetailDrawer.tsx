"use client"

import { useMemo } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import type { ForecastEntry } from './types'
import {
  BAND_COLORS,
  BAND_BG_COLORS,
  BAND_LABELS,
  CONFIDENCE_STYLES,
  EPISODE_LABELS,
  PRIORITY_STYLES,
  formatPM25,
} from './utils'

interface StationDetailDrawerProps {
  sensorId: number | null
  forecasts: ForecastEntry[]
  onClose: () => void
}

export function StationDetailDrawer({ sensorId, forecasts, onClose }: StationDetailDrawerProps) {
  const stationData = useMemo(() => {
    if (sensorId == null) return null
    const rows = forecasts.filter(f => f.sensor_id === sensorId)
    if (rows.length === 0) return null
    return {
      meta: rows[0],
      byHorizon: rows.sort((a, b) => a.lead_days - b.lead_days),
    }
  }, [sensorId, forecasts])

  if (!stationData) return null

  const { meta, byHorizon } = stationData

  return (
    <div className="fixed inset-y-0 right-0 w-full sm:w-96 bg-white shadow-2xl z-50 flex flex-col border-l border-slate-200">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 bg-slate-50">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">
            {meta.station_name || `Station ${meta.sensor_id}`}
          </h3>
          <p className="text-xs text-slate-500">
            {meta.city_name}{meta.state_name ? `, ${meta.state_name}` : ''}
          </p>
        </div>
        <button
          onClick={onClose}
          className="p-1.5 rounded-md hover:bg-slate-200 transition-colors"
        >
          <svg className="w-4 h-4 text-slate-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">

        {/* Forecast trajectory */}
        <div>
          <h4 className="text-xs font-medium text-slate-500 mb-2">Forecast Trajectory</h4>
          <div className="flex items-end gap-3 h-32 bg-slate-50 rounded-lg p-3">
            {byHorizon.map(entry => {
              const forecast = entry.pm25_forecast ?? 0
              const q75 = entry.pm25_q75 ?? forecast
              const q90 = entry.pm25_q90 ?? q75
              const maxVal = Math.max(...byHorizon.map(e => e.pm25_q90 ?? e.pm25_forecast ?? 0), 1)

              const fHeight = Math.max(8, (forecast / maxVal) * 100)
              const q75Height = Math.max(fHeight, (q75 / maxVal) * 100)
              const q90Height = Math.max(q75Height, (q90 / maxVal) * 100)
              const color = BAND_COLORS[entry.risk_band] || '#9ca3af'

              return (
                <div key={entry.lead_days} className="flex-1 flex flex-col items-center gap-1">
                  <div className="relative w-full flex justify-center" style={{ height: '100px' }}>
                    {/* Q90 bar (lightest) */}
                    <div
                      className="absolute bottom-0 w-full rounded-t opacity-20"
                      style={{ height: `${q90Height}%`, backgroundColor: color }}
                    />
                    {/* Q75 bar (medium) */}
                    <div
                      className="absolute bottom-0 w-3/4 rounded-t opacity-40"
                      style={{ height: `${q75Height}%`, backgroundColor: color }}
                    />
                    {/* Median bar (solid) */}
                    <div
                      className="absolute bottom-0 w-1/2 rounded-t"
                      style={{ height: `${fHeight}%`, backgroundColor: color }}
                    />
                    {/* Value label */}
                    <div className="absolute -top-1 text-[10px] font-bold text-slate-700">
                      {formatPM25(entry.pm25_forecast)}
                    </div>
                  </div>
                  <span className="text-[10px] text-slate-500 font-medium">D+{entry.lead_days}</span>
                  {entry.ramp_detected && (
                    <span className="text-[10px] text-amber-500">&#9889;</span>
                  )}
                </div>
              )
            })}
          </div>
          <div className="flex items-center gap-3 mt-1.5 text-[10px] text-slate-400">
            <span>&#9632; Median</span>
            <span style={{ opacity: 0.4 }}>&#9632; Q75</span>
            <span style={{ opacity: 0.2 }}>&#9632; Q90</span>
          </div>
        </div>

        {/* Per-horizon detail cards */}
        {byHorizon.map(entry => (
          <Card key={entry.lead_days}>
            <CardContent className="p-3">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-semibold text-slate-700">D+{entry.lead_days}</span>
                <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${BAND_BG_COLORS[entry.risk_band] || 'bg-gray-100 text-gray-600'}`}>
                  {BAND_LABELS[entry.risk_band] || entry.risk_band}
                </span>
              </div>

              <div className="grid grid-cols-3 gap-2 text-center mb-2">
                <div>
                  <div className="text-base font-bold text-slate-900">{formatPM25(entry.pm25_forecast)}</div>
                  <div className="text-[10px] text-slate-400">Median</div>
                </div>
                <div>
                  <div className="text-base font-bold text-slate-600">{formatPM25(entry.pm25_q75)}</div>
                  <div className="text-[10px] text-slate-400">Q75</div>
                </div>
                <div>
                  <div className="text-base font-bold text-slate-600">{formatPM25(entry.pm25_q90)}</div>
                  <div className="text-[10px] text-slate-400">Q90</div>
                </div>
              </div>

              <div className="flex flex-wrap gap-1.5">
                {/* Episode state */}
                <span className="px-1.5 py-0.5 bg-slate-100 text-slate-600 rounded text-[10px] font-medium">
                  {EPISODE_LABELS[entry.episode_state] || entry.episode_state}
                </span>

                {/* Confidence */}
                <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${CONFIDENCE_STYLES[entry.confidence] || 'bg-gray-100 text-gray-600'}`}>
                  {entry.confidence}
                </span>

                {/* Priority */}
                <span className={`px-1.5 py-0.5 rounded border text-[10px] font-medium ${PRIORITY_STYLES[entry.priority] || 'bg-gray-50 text-gray-600 border-gray-200'}`}>
                  {entry.priority}
                </span>

                {/* Ramp flag */}
                {entry.ramp_detected && (
                  <span className="px-1.5 py-0.5 bg-amber-100 text-amber-700 rounded text-[10px] font-medium">
                    &#9889; Ramp
                  </span>
                )}
              </div>
            </CardContent>
          </Card>
        ))}

        {/* Data source completeness */}
        <div>
          <h4 className="text-xs font-medium text-slate-500 mb-2">Data Sources</h4>
          <div className="grid grid-cols-2 gap-2">
            {[
              { label: 'IFS / ECMWF', ok: meta.source_ifs },
              { label: 'CAMS', ok: meta.source_cams },
              { label: 'GEOS-CF', ok: meta.source_geos_cf },
              { label: 'MOS Correction', ok: meta.mos_applied },
            ].map(src => (
              <div
                key={src.label}
                className={`flex items-center gap-1.5 px-2 py-1.5 rounded text-xs ${
                  src.ok ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-600'
                }`}
              >
                <div className={`w-1.5 h-1.5 rounded-full ${src.ok ? 'bg-green-500' : 'bg-red-400'}`} />
                {src.label}
              </div>
            ))}
          </div>
        </div>

        {/* Coordinates */}
        {meta.latitude != null && meta.longitude != null && (
          <div className="text-[10px] text-slate-400">
            {meta.latitude.toFixed(4)}°N, {meta.longitude.toFixed(4)}°E &middot; ID: {meta.sensor_id}
          </div>
        )}
      </div>
    </div>
  )
}
