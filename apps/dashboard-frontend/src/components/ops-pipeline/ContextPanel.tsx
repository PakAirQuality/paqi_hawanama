'use client'

import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Radio, ChevronUp, ChevronDown } from 'lucide-react'
import type { StationReading, PredictionData, RunReport } from './types'
import { fetchDailyBrief } from './api'

interface OpsContextPanelProps {
  selectedDate: string | null
  model: 'backbone' | 'support_aware'
  onModelChange: (m: 'backbone' | 'support_aware') => void
  stations: StationReading[]
  predictionStats: PredictionData['stats'] | null
  runReport: RunReport | null
}

function getBand(pm25: number): string {
  if (pm25 <= 35) return 'good'
  if (pm25 <= 75) return 'moderate'
  if (pm25 <= 150) return 'unhealthy'
  if (pm25 <= 250) return 'very_unhealthy'
  return 'severe'
}

const BAND_COLORS: Record<string, string> = {
  good: '#6ecc39', moderate: '#f0c20c', unhealthy: '#f18017',
  very_unhealthy: '#a070b5', severe: '#ef4444',
}
const BAND_LABELS: Record<string, string> = {
  good: 'good', moderate: 'moderate', unhealthy: 'unhealthy',
  very_unhealthy: 'very unhealthy', severe: 'severe',
}
const BANDS = ['good', 'moderate', 'unhealthy', 'very_unhealthy', 'severe'] as const

function assessmentText(
  obs: { count: number; mean: number; max: number; band: string; bands: Record<string, number>; worstCities: { city: string; avg: number; count: number }[] } | null,
  predMean: number | null,
  coverage: number | null,
): { text: string; severity: string; color: string } {
  if (!obs && predMean == null) return { text: 'No observation or prediction data available for this date.', severity: 'Unknown', color: '#6b7280' }

  const parts: string[] = []
  let severity = 'Moderate'
  let color = '#3b82f6'

  if (obs) {
    const unhealthy = obs.bands.unhealthy + obs.bands.very_unhealthy + obs.bands.severe
    const unhealthyPct = Math.round((unhealthy / obs.count) * 100)

    if (obs.mean > 150) {
      severity = 'Severe'
      color = '#ef4444'
      parts.push(`Severe air quality day with a national station mean of ${Math.round(obs.mean)} µg/m³ across ${obs.count} reporting stations.`)
    } else if (obs.mean > 75) {
      severity = 'Unhealthy'
      color = '#f18017'
      parts.push(`Unhealthy air quality conditions recorded with a national mean of ${Math.round(obs.mean)} µg/m³ across ${obs.count} stations.`)
    } else if (obs.mean > 35) {
      severity = 'Moderate'
      color = '#f0c20c'
      parts.push(`Moderate air quality observed with a mean of ${Math.round(obs.mean)} µg/m³ across ${obs.count} stations.`)
    } else {
      severity = 'Good'
      color = '#6ecc39'
      parts.push(`Good air quality day — national mean of ${Math.round(obs.mean)} µg/m³ across ${obs.count} stations.`)
    }

    if (unhealthy > 0) {
      parts.push(`${unhealthy} station${unhealthy > 1 ? 's' : ''} (${unhealthyPct}%) exceeded unhealthy thresholds.`)
    }

    if (obs.worstCities.length > 0) {
      const worst = obs.worstCities[0]
      parts.push(`${worst.city} recorded the highest levels at ${Math.round(worst.avg)} µg/m³.`)
    }

    if (predMean != null) {
      const bias = predMean - obs.mean
      const absBias = Math.abs(bias)
      if (absBias <= 5) {
        parts.push(`Model prediction closely matched observations (bias ${bias > 0 ? '+' : ''}${bias.toFixed(1)} µg/m³).`)
      } else if (absBias <= 15) {
        parts.push(`Model ${bias > 0 ? 'over' : 'under'}predicted by ${absBias.toFixed(1)} µg/m³ — within acceptable range.`)
      } else {
        parts.push(`Significant model ${bias > 0 ? 'over' : 'under'}prediction of ${absBias.toFixed(1)} µg/m³ — requires investigation.`)
      }
    }

    if (coverage != null && coverage < 80) {
      parts.push(`Grid coverage was limited at ${coverage}%.`)
    }
  } else if (predMean != null) {
    const band = getBand(predMean)
    severity = band === 'good' ? 'Good' : band === 'moderate' ? 'Moderate' : band === 'unhealthy' ? 'Unhealthy' : 'Severe'
    color = BAND_COLORS[band]
    parts.push(`Predicted national mean of ${Math.round(predMean)} µg/m³. No ground observations available for validation.`)
  }

  return { text: parts.join(' '), severity, color }
}

export function OpsContextPanel({ selectedDate, model, onModelChange, stations, predictionStats, runReport }: OpsContextPanelProps) {
  const [minimized, setMinimized] = useState(false)
  const obs = useMemo(() => {
    const valid = stations.filter(s => s.pm25 != null)
    if (!valid.length) return null
    const values = valid.map(s => s.pm25)
    const mean = values.reduce((a, b) => a + b, 0) / values.length
    const max = Math.max(...values)
    const bands: Record<string, number> = { good: 0, moderate: 0, unhealthy: 0, very_unhealthy: 0, severe: 0 }
    valid.forEach(s => { bands[getBand(s.pm25)]++ })
    const cityMap: Record<string, number[]> = {}
    valid.forEach(s => { if (s.city) { (cityMap[s.city] ??= []).push(s.pm25) } })
    const worstCities = Object.entries(cityMap)
      .map(([city, vals]) => ({ city, avg: vals.reduce((a, b) => a + b, 0) / vals.length, count: vals.length }))
      .sort((a, b) => b.avg - a.avg)
    return { count: valid.length, mean, max: Math.round(max), band: getBand(mean), bands, worstCities }
  }, [stations])

  const coverage = predictionStats?.n_total
    ? Math.round((predictionStats.n_valid / predictionStats.n_total) * 100) : null

  const assessment = useMemo(
    () => assessmentText(obs, predictionStats?.mean ?? null, coverage),
    [obs, predictionStats?.mean, coverage]
  )

  const { data: brief, isLoading: briefLoading } = useQuery({
    queryKey: ['ops-brief', selectedDate],
    queryFn: () => fetchDailyBrief(selectedDate!),
    enabled: !!selectedDate,
    staleTime: Infinity,
    retry: 1,
  })

  const formattedDate = selectedDate
    ? new Date(selectedDate).toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' })
    : '—'

  return (
    <div
      className="absolute top-3 right-4 z-10 flex flex-col rounded-xl shadow-2xl overflow-hidden"
      style={{
        background: 'rgba(15, 23, 42, 0.95)',
        border: '1px solid rgba(255,255,255,0.12)',
        width: 340,
        maxHeight: 'calc(100vh - 120px)',
      }}
    >
      {/* ── Header ── */}
      <div className="px-4 pt-4 pb-1.5" style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
        <div className="flex items-start justify-between">
          <div>
            <div className="text-[14px] font-bold text-white/90">Pakistan</div>
            <div className="mt-0.5 text-[9px] text-slate-400">{formattedDate}</div>
          </div>
          <button
            onClick={() => setMinimized(v => !v)}
            className="p-1 rounded-md hover:bg-white/10 transition-colors -mt-0.5 -mr-1"
            title={minimized ? 'Expand' : 'Minimize'}
          >
            {minimized ? <ChevronDown size={14} className="text-white/40" /> : <ChevronUp size={14} className="text-white/40" />}
          </button>
        </div>

        {/* Station stats row — visible even when minimized */}
        {obs && !minimized && (
          <div className="mt-2 flex items-center gap-2 pb-1.5 text-[10px]">
            <Radio size={12} className="text-slate-500" />
            <span className="text-slate-300">{obs.count} stations</span>
            <span className="text-slate-600">·</span>
            <span className="flex gap-2 text-[9px]">
              {BANDS.map(band => obs.bands[band] > 0 ? (
                <span key={band} style={{ color: BAND_COLORS[band] }}>{obs.bands[band]} {BAND_LABELS[band]}</span>
              ) : null)}
            </span>
          </div>
        )}
      </div>

      {!minimized && (
        <>
          {/* ── Assessment ── */}
          <div
            className="mx-3 my-2 rounded-lg overflow-hidden"
            style={{
              background: 'rgba(255,255,255,0.03)',
              border: '1px solid rgba(255,255,255,0.06)',
              borderLeft: `3px solid ${assessment.color}`,
            }}
          >
            <div className="flex items-center justify-between px-3 pt-2.5 pb-0">
              <span className="text-[8px] font-semibold uppercase tracking-widest text-white/20">{brief?.narrative ? 'Brief' : 'Assessment'}</span>
              <span
                className="rounded px-1.5 py-0.5 text-[7px] font-bold uppercase"
                style={{ color: assessment.color, background: assessment.color + '18' }}
              >
                {assessment.severity}
              </span>
            </div>
            <div className="px-3 pt-2 pb-2.5 text-[12px] leading-[1.6] text-white/80">
              {briefLoading ? (
                <span className="text-white/40 italic">Generating brief…</span>
              ) : brief?.narrative ? (
                brief.narrative
              ) : (
                assessment.text
              )}
            </div>
          </div>

          {/* ── Model toggle ── */}
          <div className="mx-3 mb-3">
            <div
              className="flex rounded-lg overflow-hidden"
              style={{ border: '1px solid rgba(255,255,255,0.1)', background: 'rgba(255,255,255,0.03)' }}
            >
              <button
                onClick={() => onModelChange('backbone')}
                className="flex-1 py-1.5 text-[10px] font-semibold transition-colors"
                style={{
                  background: model === 'backbone' ? 'rgba(255,255,255,0.08)' : 'transparent',
                  color: model === 'backbone' ? '#fff' : 'rgba(255,255,255,0.3)',
                }}
              >
                Satellite
              </button>
              <button
                onClick={() => onModelChange('support_aware')}
                className="flex-1 py-1.5 text-[10px] font-semibold transition-colors"
                style={{
                  background: model === 'support_aware' ? 'rgba(52,211,153,0.15)' : 'transparent',
                  color: model === 'support_aware' ? '#34d399' : 'rgba(255,255,255,0.3)',
                }}
              >
                Enhanced
              </button>
            </div>
          </div>

          {/* ── Source attribution ── */}
          <div className="px-4 pb-2.5 text-center text-[7px] text-white/15">
            LightGBM · ERA5 · MODIS AOD · TROPOMI
          </div>
        </>
      )}
    </div>
  )
}
