'use client'

import { useState, useMemo } from 'react'
import { Flame, ChevronLeft, Navigation, AlertTriangle, RefreshCw } from 'lucide-react'
import { SatelliteImage } from '@/components/shared/SatelliteImage'
import type { FiresGeoJSON, FiresStatus } from '@/components/analyst-desk/api'
import { formatDateOnly, formatPkt } from '@/lib/time'
import { firesDelayed } from '@/lib/fires'

interface FireFeature {
  type: "Feature"
  geometry: { type: "Point"; coordinates: [number, number] }
  properties: {
    frp: number
    confidence: string
    satellite: string
    acq_date: string
    acq_time?: string
    acq_datetime_utc?: string
  }
}

interface FiresPanelProps {
  firesData: FiresGeoJSON | null
  onFlyTo: (lng: number, lat: number, zoom?: number) => void
  selectedDate: string | null
  /** react-query state so failure never looks like loading */
  isLoading?: boolean
  isFetching?: boolean
  isError?: boolean
  errorMessage?: string | null
}

function confidenceColor(c: string): string {
  const cl = c?.toLowerCase()
  if (cl === 'h' || cl === 'high') return '#ef4444'
  if (cl === 'n' || cl === 'nominal') return '#f59e0b'
  return '#94a3b8'
}

function confidenceLabel(c: string): string {
  const cl = c?.toLowerCase()
  if (cl === 'h' || cl === 'high') return 'High'
  if (cl === 'n' || cl === 'nominal') return 'Nominal'
  if (cl === 'l' || cl === 'low') return 'Low'
  return c || 'Unknown'
}

function confidenceBadgeBg(c: string): string {
  const cl = c?.toLowerCase()
  if (cl === 'h' || cl === 'high') return 'bg-red-50 text-red-600'
  if (cl === 'n' || cl === 'nominal') return 'bg-amber-50 text-amber-600'
  return 'bg-slate-50 text-slate-500'
}

function frpCategory(frp: number): string {
  if (frp >= 100) return 'Extreme'
  if (frp >= 50) return 'Strong'
  if (frp >= 20) return 'Moderate'
  if (frp >= 5) return 'Low'
  return 'Very Low'
}

function satelliteName(s: string): string {
  const u = (s || '').toUpperCase()
  if (u === 'N20' || u.includes('NOAA20')) return 'NOAA-20'
  if (u === 'N21' || u.includes('NOAA21')) return 'NOAA-21'
  if (u === 'N' || u.includes('SNPP')) return 'Suomi NPP'
  return s || 'VIIRS'
}

/** The six states a reader must be able to tell apart. */
export function describeFiresState(
  data: FiresGeoJSON | null,
  { isLoading, isError, selectedDate }: { isLoading?: boolean; isError?: boolean; selectedDate: string | null },
): { tone: 'ok' | 'empty' | 'warn' | 'error' | 'loading'; title: string; detail: string } {
  if (isError) return { tone: 'error', title: 'Fire data unavailable', detail: 'The fire service did not answer. Nothing is shown rather than an older day.' }
  if (isLoading || !data) return { tone: 'loading', title: 'Loading fire detections…', detail: '' }
  const status: FiresStatus = data.status ?? (data.features.length ? 'ok' : 'empty')
  const day = data.date ? formatDateOnly(data.date) : ''
  const fetched = data.last_successful_fetch ? ` · fetched ${formatPkt(data.last_successful_fetch)}` : ''
  const window = data.observation_period ? ` · overpasses ${formatPkt(data.observation_period.start)} to ${formatPkt(data.observation_period.end)}` : ''
  const delayed = firesDelayed(data)
  const delayNote = delayed ? `Last update ${Math.round(data.fetched_age_hours ?? 0)} h ago; the 3-hourly fire feed is behind, so recent overpasses may be missing. ` : ''
  switch (status) {
    case 'ok':
      return { tone: delayed ? 'warn' : 'ok', title: `${data.features.length} detections on ${day}`, detail: `${delayNote}Pakistan day${window}${fetched}` }
    case 'empty':
      return { tone: delayed ? 'warn' : 'empty', title: `No detections returned for ${day}`, detail: `${delayNote}The satellites passed and found no thermal anomalies in the area${fetched}` }
    case 'partial': {
      const failed = (data.sources ?? []).filter((s) => s.status !== 'ok').map((s) => s.source.replace('VIIRS_', '').replace('_NRT', ''))
      return { tone: 'warn', title: `Partial coverage for ${day}`, detail: `${failed.join(', ') || 'A source'} failed on the latest fetch; detections may be missing${fetched}` }
    }
    case 'stale':
      return { tone: 'warn', title: `Showing last successful update (${day})`, detail: `No fire file exists yet for ${selectedDate ? formatDateOnly(selectedDate) : 'the selected day'}${fetched}` }
    default:
      return { tone: 'error', title: 'Fire data unavailable', detail: `No detections stored for ${selectedDate ? formatDateOnly(selectedDate) : 'this day'} or the two days before it.` }
  }
}

type View = { type: 'list' } | { type: 'detail'; fire: FireFeature; index: number }

export function FiresPanel({ firesData, onFlyTo, selectedDate, isLoading, isFetching, isError, errorMessage }: FiresPanelProps) {
  const [sortBy, setSortBy] = useState<'frp' | 'confidence'>('frp')
  const [view, setView] = useState<View>({ type: 'list' })

  const features = firesData?.features ?? []
  const state = describeFiresState(firesData, { isLoading, isError, selectedDate })

  const highCount = useMemo(() =>
    features.filter(f => {
      const c = f.properties.confidence?.toLowerCase()
      return c === 'h' || c === 'high'
    }).length
  , [features])

  const sorted = useMemo(() => {
    const arr = [...features]
    if (sortBy === 'frp') {
      arr.sort((a, b) => (b.properties.frp || 0) - (a.properties.frp || 0))
    } else {
      const order: Record<string, number> = { h: 0, high: 0, n: 1, nominal: 1, l: 2, low: 2 }
      arr.sort((a, b) => {
        const oa = order[a.properties.confidence?.toLowerCase()] ?? 3
        const ob = order[b.properties.confidence?.toLowerCase()] ?? 3
        return oa !== ob ? oa - ob : (b.properties.frp || 0) - (a.properties.frp || 0)
      })
    }
    return arr
  }, [features, sortBy])

  const toneClass = {
    ok: 'bg-emerald-50 border-emerald-100 text-emerald-700',
    empty: 'bg-slate-50 border-slate-200 text-slate-600',
    warn: 'bg-amber-50 border-amber-100 text-amber-700',
    error: 'bg-red-50 border-red-100 text-red-700',
    loading: 'bg-slate-50 border-slate-200 text-slate-500',
  }[state.tone]

  // ── Loading state ──
  if (state.tone === 'loading') {
    return (
      <div className="flex-1 flex items-center justify-center bg-[#fafbfc]">
        <div className="flex items-center gap-2 text-slate-400 text-sm">
          <div className="w-4 h-4 border-2 border-slate-300 border-t-slate-500 rounded-full animate-spin" />
          {state.title}
        </div>
      </div>
    )
  }

  // ── Fire detail view ──
  if (view.type === 'detail') {
    const f = view.fire
    const [lng, lat] = f.geometry.coordinates
    const { frp, confidence, satellite, acq_date, acq_datetime_utc } = f.properties

    return (
      <div className="flex flex-col h-full bg-[#fafbfc]">
        <button
          onClick={() => setView({ type: 'list' })}
          className="flex items-center gap-1 px-5 py-3 text-[12px] font-medium text-slate-400 hover:text-slate-600 transition-colors w-full"
        >
          <ChevronLeft size={14} strokeWidth={2} /> All detections
        </button>
        <div className="flex-1 overflow-y-auto scrollbar-hide">
          <div className="px-5 pb-4">
            <h2 className="text-[20px] font-semibold text-[#1e293b] leading-snug tracking-[-0.01em]">
              Detection #{view.index + 1}
            </h2>
            <p className="text-[12px] text-[#94a3b8] mt-1 leading-relaxed">
              {lat.toFixed(4)}°N, {lng.toFixed(4)}°E &middot; {satelliteName(satellite)}
            </p>
            <span className={`inline-flex items-center mt-2.5 text-[10px] font-semibold uppercase tracking-wide px-2.5 py-[3px] rounded-full ${confidenceBadgeBg(confidence)}`}>
              {confidenceLabel(confidence)} confidence
            </span>
          </div>

          <div className="px-4 pb-3">
            <SatelliteImage
              lat={lat}
              lon={lng}
              name={`Fire detection at ${lat.toFixed(4)}, ${lng.toFixed(4)}`}
              zoom="close"
              label="Detection location"
              markerColor={confidenceColor(confidence)}
            />
          </div>

          <div className="px-4 pb-4">
            <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
              <div className="px-4 py-2.5 border-b border-slate-100">
                <span className="text-[12px] font-bold text-slate-700">Detection details</span>
              </div>
              <div className="px-4 py-3 grid grid-cols-2 gap-x-6 gap-y-2.5 text-[11px]">
                <div>
                  <div className="text-slate-400 text-[10px]">Fire radiative power</div>
                  <div className="text-slate-700 font-medium">{frp} MW</div>
                </div>
                <div>
                  <div className="text-slate-400 text-[10px]">Intensity (FRP class)</div>
                  <div className="text-slate-700 font-medium">{frpCategory(frp)}</div>
                </div>
                <div>
                  <div className="text-slate-400 text-[10px]">Confidence</div>
                  <div className="font-medium" style={{ color: confidenceColor(confidence) }}>{confidenceLabel(confidence)}</div>
                </div>
                <div>
                  <div className="text-slate-400 text-[10px]">Satellite</div>
                  <div className="text-slate-700 font-medium">{satelliteName(satellite)} (VIIRS)</div>
                </div>
                <div>
                  <div className="text-slate-400 text-[10px]">Acquired</div>
                  <div className="text-slate-700 font-medium">{acq_datetime_utc ? formatPkt(acq_datetime_utc) : acq_date}</div>
                </div>
                <div>
                  <div className="text-slate-400 text-[10px]">Coordinates</div>
                  <div className="text-slate-700 font-medium">{lat.toFixed(5)}, {lng.toFixed(5)}</div>
                </div>
              </div>
              <div className="px-4 pb-3 text-[10px] text-slate-400 leading-snug">
                A thermal anomaly at the satellite pixel; FRP is radiative power, not a measured contribution to PM2.5.
              </div>
            </div>
          </div>

          <div className="px-4 pb-5">
            <button
              onClick={() => onFlyTo(lng, lat, 14)}
              className="w-full flex items-center justify-center gap-2 py-2.5 bg-slate-800 hover:bg-slate-700 text-white text-[12px] font-medium rounded-lg transition-colors"
            >
              <Navigation size={13} /> Fly to location
            </button>
          </div>
        </div>
      </div>
    )
  }

  // ── List view ──
  return (
    <div className="flex flex-col h-full bg-[#fafbfc]">
      <div className="px-5 pt-5 pb-3 border-b border-slate-100">
        <div className="flex items-center gap-2 mb-1">
          <Flame size={16} className="text-orange-500" />
          <span className="text-[13px] font-semibold text-slate-800">Satellite fire detections</span>
          {isFetching && !isLoading && <RefreshCw size={12} className="text-slate-300 animate-spin" />}
        </div>
        <div className={`mt-2 rounded-lg border px-3 py-2 text-[11px] ${toneClass}`}>
          <div className="flex items-start gap-1.5">
            {(state.tone === 'warn' || state.tone === 'error') && <AlertTriangle size={12} className="mt-0.5 shrink-0" />}
            <div>
              <div className="font-semibold">{state.title}</div>
              {state.detail && <div className="opacity-80 mt-0.5">{state.detail}</div>}
              {isError && errorMessage && <div className="opacity-70 mt-0.5">{errorMessage}</div>}
            </div>
          </div>
        </div>

        {features.length > 0 && (
          <div className="flex gap-2 mt-3">
            <div className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-orange-50 border border-orange-100">
              <span className="text-[18px] font-bold text-orange-600">{features.length}</span>
              <span className="text-[10px] text-orange-600/70 font-medium">detections</span>
            </div>
            <div className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-red-50 border border-red-100">
              <span className="text-[18px] font-bold text-red-600">{highCount}</span>
              <span className="text-[10px] text-red-600/70 font-medium">high conf.</span>
            </div>
          </div>
        )}
      </div>

      {features.length > 0 && (
        <div className="px-5 py-2 border-b border-slate-100/80 flex items-center gap-2">
          <span className="text-[10px] text-slate-400 font-medium uppercase tracking-wider">Sort</span>
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as 'frp' | 'confidence')}
            className="text-[11px] text-slate-600 bg-white border border-slate-200 rounded px-2 py-1 outline-none focus:border-slate-400"
          >
            <option value="frp">Fire power (FRP)</option>
            <option value="confidence">Confidence</option>
          </select>
        </div>
      )}

      <div className="flex-1 overflow-y-auto">
        {features.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-400 gap-2 px-6 text-center">
            <Flame size={24} className="opacity-30" />
            <span className="text-[12px]">{state.tone === 'empty' ? 'No detections in this period.' : 'Nothing to list.'}</span>
          </div>
        ) : (
          sorted.map((f, i) => {
            const [lng, lat] = f.geometry.coordinates
            const { frp, confidence, satellite, acq_datetime_utc, acq_date } = f.properties
            return (
              <button
                key={i}
                onClick={() => {
                  setView({ type: 'detail', fire: f as FireFeature, index: i })
                  onFlyTo(lng, lat, 12)
                }}
                className="w-full flex items-center gap-3 px-5 py-2.5 hover:bg-slate-50 border-b border-slate-100/80 text-left transition-colors"
              >
                <div className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ background: confidenceColor(confidence) }} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-baseline gap-2">
                    <span className="text-[12px] font-semibold text-slate-800">{frp} MW</span>
                    <span className="text-[10px] font-medium" style={{ color: confidenceColor(confidence) }}>{confidenceLabel(confidence)}</span>
                  </div>
                  <div className="text-[10px] text-slate-400">
                    {satelliteName(satellite)} &middot; {acq_datetime_utc ? formatPkt(acq_datetime_utc) : acq_date} &middot; {lat.toFixed(3)}, {lng.toFixed(3)}
                  </div>
                </div>
                <ChevronLeft size={12} className="text-slate-300 flex-shrink-0 rotate-180" />
              </button>
            )
          })
        )}
      </div>
    </div>
  )
}
