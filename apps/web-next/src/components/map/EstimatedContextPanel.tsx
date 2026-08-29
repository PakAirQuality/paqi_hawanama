'use client'

import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Radio, ChevronUp, ChevronDown } from 'lucide-react'
import { fetchDailyStations, fetchDailyBrief } from '@/lib/api'

const BAND_COLORS: Record<string, string> = {
  good: '#6ecc39', moderate: '#f0c20c', unhealthy: '#f18017',
  very_unhealthy: '#a070b5', severe: '#ef4444',
}
const BAND_LABELS: Record<string, string> = {
  good: 'good', moderate: 'moderate', unhealthy: 'unhealthy',
  very_unhealthy: 'very unhealthy', severe: 'severe',
}
const BANDS = ['good', 'moderate', 'unhealthy', 'very_unhealthy', 'severe'] as const

function getBand(pm25: number): string {
  if (pm25 <= 35) return 'good'
  if (pm25 <= 75) return 'moderate'
  if (pm25 <= 150) return 'unhealthy'
  if (pm25 <= 250) return 'very_unhealthy'
  return 'severe'
}

function severityFromMean(mean: number | null): { label: string; color: string } {
  if (mean === null) return { label: 'Unknown', color: '#94a3b8' }
  if (mean <= 35) return { label: 'Good', color: BAND_COLORS.good }
  if (mean <= 75) return { label: 'Moderate', color: BAND_COLORS.moderate }
  if (mean <= 150) return { label: 'Unhealthy', color: BAND_COLORS.unhealthy }
  if (mean <= 250) return { label: 'Very Unhealthy', color: BAND_COLORS.very_unhealthy }
  return { label: 'Severe', color: BAND_COLORS.severe }
}

// Strip sentences that contain model-evaluation / bias language.
// The LLM prompt instructs Gemini to emit these; we filter them for the public audience.
function stripModelEval(narrative: string): string {
  const sentences = narrative.split(/(?<=[.!?])\s+/)
  const re = /\b(bias|satellite backbone|enhanced model|under[- ]?(estim|predict)|over[- ]?(estim|predict))\b/i
  return sentences.filter(s => !re.test(s)).join(' ').trim()
}

interface Props {
  selectedDate: string
}

export default function EstimatedContextPanel({ selectedDate }: Props) {
  const [minimized, setMinimized] = useState(false)

  const { data: stations } = useQuery({
    queryKey: ['daily-stations', selectedDate],
    queryFn: () => fetchDailyStations(selectedDate),
    staleTime: Infinity,
  })

  const { data: brief, isLoading: briefLoading } = useQuery({
    queryKey: ['daily-brief', selectedDate],
    queryFn: () => fetchDailyBrief(selectedDate),
    staleTime: Infinity,
    retry: 1,
  })

  const obs = useMemo(() => {
    if (!stations || stations.length === 0) return null
    const bands: Record<string, number> = { good: 0, moderate: 0, unhealthy: 0, very_unhealthy: 0, severe: 0 }
    let sum = 0
    for (const s of stations) {
      bands[getBand(s.pm25)]++
      sum += s.pm25
    }
    return { count: stations.length, mean: sum / stations.length, bands }
  }, [stations])

  const formattedDate = useMemo(() => {
    const d = new Date(selectedDate + 'T00:00:00')
    return d.toLocaleDateString('en-US', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })
  }, [selectedDate])

  const cleaned = brief?.narrative ? stripModelEval(brief.narrative) : ''
  const severity = severityFromMean(obs?.mean ?? null)

  const showBrief = cleaned.length > 0
  const showBriefLoading = briefLoading && !cleaned

  return (
    <div
      className="flex flex-col rounded-xl shadow-2xl overflow-hidden"
      style={{
        background: 'rgba(15, 23, 42, 0.95)',
        border: '1px solid rgba(255,255,255,0.12)',
        width: 320,
        maxHeight: 'calc(100vh - 140px)',
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
            {minimized
              ? <ChevronDown size={14} className="text-white/40" />
              : <ChevronUp size={14} className="text-white/40" />}
          </button>
        </div>

        {obs && !minimized && (
          <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 pb-1.5 text-[10px]">
            <Radio size={12} className="text-slate-500 shrink-0" />
            <span className="text-slate-300">{obs.count} stations</span>
            <span className="text-slate-600">·</span>
            <span className="flex flex-wrap gap-x-2 gap-y-0.5 text-[9px]">
              {BANDS.map(band => obs.bands[band] > 0 ? (
                <span key={band} style={{ color: BAND_COLORS[band] }}>
                  {obs.bands[band]} {BAND_LABELS[band]}
                </span>
              ) : null)}
            </span>
          </div>
        )}
      </div>

      {/* ── Brief block — hidden if no brief ── */}
      {!minimized && (showBrief || showBriefLoading) && (
        <div
          className="mx-3 my-2 rounded-lg overflow-hidden"
          style={{
            background: 'rgba(255,255,255,0.03)',
            border: '1px solid rgba(255,255,255,0.06)',
            borderLeft: `3px solid ${severity.color}`,
          }}
        >
          <div className="flex items-center justify-between px-3 pt-2.5 pb-0">
            <span className="text-[8px] font-semibold uppercase tracking-widest text-white/20">Brief</span>
            <span
              className="rounded px-1.5 py-0.5 text-[7px] font-bold uppercase"
              style={{ color: severity.color, background: severity.color + '18' }}
            >
              {severity.label}
            </span>
          </div>
          <div className="px-3 pt-2 pb-2.5 text-[12px] leading-[1.6] text-white/80">
            {showBriefLoading
              ? <span className="text-white/40 italic">Loading brief…</span>
              : cleaned}
          </div>
        </div>
      )}
    </div>
  )
}
