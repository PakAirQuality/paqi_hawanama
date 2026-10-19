'use client'

import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Radio, ChevronUp, ChevronDown, Info } from 'lucide-react'
import type { StationReading, PredictionData, RunReport } from './types'
import { fetchDailyBrief } from './api'
import { BAND_KEYS, bandColor, bandCounts, bandKey, bandLabel, classifyPm25, unhealthyOrWorse, BAND_SCALE_LABEL } from '@/lib/aqi'
import { formatDateOnly } from '@/lib/time'
import { MODEL_HELP, MODEL_LABELS, type ModelKey } from '@/lib/selection'

interface OpsContextPanelProps {
  selectedDate: string | null
  model: ModelKey
  onModelChange: (m: ModelKey) => void
  stations: StationReading[]
  /** stats of the prediction grid for `model` (an area average over the model domain) */
  predictionStats: PredictionData['stats'] | null
  runReport: RunReport | null
}

interface Obs {
  count: number
  mean: number
  max: number
  band: string
  bands: ReturnType<typeof bandCounts>
  worstCities: { city: string; avg: number; count: number }[]
}

function assessmentText(
  obs: Obs | null,
  gridMean: number | null,
  coverage: number | null,
  matched: { bias: number; mae: number; n: number } | null,
  modelLabel: string,
): { text: string; severity: string; color: string } {
  if (!obs && gridMean == null) return { text: 'No observation or prediction data available for this date.', severity: 'Unknown', color: '#6b7280' }

  const parts: string[] = []
  let severity = 'Moderate'
  let color = '#3b82f6'

  if (obs) {
    const band = classifyPm25(obs.mean)
    severity = band.label
    color = band.color
    parts.push(
      `${band.label} conditions at the reporting-station mean of ${Math.round(obs.mean)} µg/m³ PM2.5 across ${obs.count} reporting stations (${BAND_SCALE_LABEL}).`,
    )
    const bad = unhealthyOrWorse(obs.bands)
    if (bad > 0) {
      parts.push(`${bad} station${bad > 1 ? 's' : ''} (${Math.round((bad / obs.count) * 100)}%) were Unhealthy or worse.`)
    }
    if (obs.worstCities.length > 0) {
      const worst = obs.worstCities[0]
      parts.push(`${worst.city} recorded the highest city mean at ${Math.round(worst.avg)} µg/m³ (${worst.count} station${worst.count > 1 ? 's' : ''}).`)
    }
    if (matched) {
      const abs = Math.abs(matched.bias)
      const dir = matched.bias > 0 ? 'over' : 'under'
      parts.push(
        abs <= 5
          ? `The ${modelLabel} matched the stations closely (bias ${matched.bias > 0 ? '+' : ''}${matched.bias.toFixed(1)} µg/m³ at ${matched.n} matched stations).`
          : `The ${modelLabel} ${dir}-estimated at the stations by ${abs.toFixed(1)} µg/m³ on average (${matched.n} matched stations, MAE ${matched.mae.toFixed(1)}).`,
      )
    } else if (gridMean != null) {
      parts.push(`Modelled area-average PM2.5 was ${Math.round(gridMean)} µg/m³; no matched-station comparison is available for this date.`)
    }
    if (coverage != null && coverage < 80) parts.push(`Model grid coverage was limited at ${coverage}%.`)
  } else if (gridMean != null) {
    const band = classifyPm25(gridMean)
    severity = band.label
    color = band.color
    parts.push(`Modelled area-average PM2.5 of ${Math.round(gridMean)} µg/m³. No ground observations were available for comparison.`)
  }

  return { text: parts.join(' '), severity, color }
}

export function OpsContextPanel({ selectedDate, model, onModelChange, stations, predictionStats, runReport }: OpsContextPanelProps) {
  const [minimized, setMinimized] = useState(false)
  const [showModelHelp, setShowModelHelp] = useState(false)

  const obs = useMemo<Obs | null>(() => {
    const valid = stations.filter(s => s.pm25 != null)
    if (!valid.length) return null
    const values = valid.map(s => s.pm25)
    const mean = values.reduce((a, b) => a + b, 0) / values.length
    const max = Math.max(...values)
    const cityMap: Record<string, number[]> = {}
    valid.forEach(s => { if (s.city) { (cityMap[s.city] ??= []).push(s.pm25) } })
    const worstCities = Object.entries(cityMap)
      .map(([city, vals]) => ({ city, avg: vals.reduce((a, b) => a + b, 0) / vals.length, count: vals.length }))
      .sort((a, b) => b.avg - a.avg)
    return { count: valid.length, mean, max: Math.round(max), band: bandKey(mean), bands: bandCounts(values), worstCities }
  }, [stations])

  const coverage = predictionStats?.n_total
    ? Math.round((predictionStats.n_valid / predictionStats.n_total) * 100) : null

  const { data: brief, isLoading: briefLoading } = useQuery({
    queryKey: ['ops-brief', selectedDate],
    queryFn: () => fetchDailyBrief(selectedDate!),
    enabled: !!selectedDate,
    staleTime: Infinity,
    retry: 1,
  })

  const matched = brief?.matched_bias?.[model] ?? null
  const modelLabel = MODEL_LABELS[model]

  const assessment = useMemo(
    () => assessmentText(obs, predictionStats?.mean ?? null, coverage, matched, modelLabel),
    [obs, predictionStats?.mean, coverage, matched, modelLabel]
  )

  const formattedDate = selectedDate
    ? formatDateOnly(selectedDate, { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' })
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
            <div className="mt-0.5 text-[9px] text-slate-400">{formattedDate} · Pakistan Standard Time · daily means of hourly PM2.5</div>
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
            <span className="text-slate-300" title="Unweighted mean across the stations that reported on this day; not an area or population average">
              Reporting-station mean {Math.round(obs.mean)} µg/m³ · {obs.count} stations
            </span>
          </div>
        )}
        {obs && !minimized && (
          <div className="flex flex-wrap gap-x-2 gap-y-0.5 pb-1.5 text-[9px]">
            {BAND_KEYS.map(k => obs.bands[k] > 0 ? (
              <span key={k} style={{ color: bandColor(k) }}>{obs.bands[k]} {bandLabel(k, true)}</span>
            ) : null)}
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
                <span className="text-white/40 italic">Loading brief…</span>
              ) : brief?.narrative ? (
                brief.narrative
              ) : (
                assessment.text
              )}
            </div>
          </div>

          {/* ── Model figures for the selected model ── */}
          <div className="mx-3 mb-2 grid grid-cols-2 gap-2 text-[10px]">
            <div className="rounded-lg px-2.5 py-2" style={{ background: 'rgba(255,255,255,0.03)' }}>
              <div className="text-[8px] uppercase tracking-wider text-white/30">Modelled area-average</div>
              <div className="text-white/90 font-semibold tabular-nums text-[13px]">
                {predictionStats?.mean != null ? `${Math.round(predictionStats.mean)} µg/m³` : '—'}
              </div>
              <div className="text-white/30">{modelLabel}{coverage != null ? ` · ${coverage}% grid coverage` : ''}</div>
            </div>
            <div className="rounded-lg px-2.5 py-2" style={{ background: 'rgba(255,255,255,0.03)' }}>
              <div className="text-[8px] uppercase tracking-wider text-white/30">Matched-station bias</div>
              <div className="text-white/90 font-semibold tabular-nums text-[13px]">
                {matched ? `${matched.bias > 0 ? '+' : ''}${matched.bias.toFixed(1)} µg/m³` : '—'}
              </div>
              <div className="text-white/30">{matched ? `${matched.n} stations · MAE ${matched.mae.toFixed(1)}` : 'no matched comparison'}</div>
            </div>
          </div>

          {/* ── Model toggle ── */}
          <div className="mx-3 mb-2">
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
              <button
                onClick={() => setShowModelHelp(v => !v)}
                className="px-2 text-white/30 hover:text-white/70"
                title="What do these modes mean?"
                aria-label="Explain model modes"
              >
                <Info size={12} />
              </button>
            </div>
            {showModelHelp && (
              <div className="mt-1.5 text-[9px] leading-snug text-white/50">
                <div><span className="text-white/70">Satellite:</span> {MODEL_HELP.backbone}</div>
                <div className="mt-1"><span className="text-white/70">Enhanced:</span> {MODEL_HELP.support_aware}</div>
              </div>
            )}
          </div>

          {/* ── Source attribution ── */}
          <div className="px-4 pb-2.5 text-center text-[8px] text-white/25">
            {runReport?.model_version ? `Model ${runReport.model_version} · ` : ''}LightGBM · ERA5 · MODIS AOD · TROPOMI · {BAND_SCALE_LABEL}
          </div>
        </>
      )}
    </div>
  )
}
