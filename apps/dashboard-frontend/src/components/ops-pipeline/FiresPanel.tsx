'use client'

import { useState, useMemo } from 'react'
import { Flame, MapPin, ChevronLeft, Navigation } from 'lucide-react'
import { SatelliteImage } from '@/components/shared/SatelliteImage'
import type { FiresGeoJSON } from '@/components/analyst-desk/api'

interface FireFeature {
  type: "Feature"
  geometry: { type: "Point"; coordinates: [number, number] }
  properties: {
    frp: number
    confidence: string
    satellite: string
    acq_date: string
  }
}

interface FiresPanelProps {
  firesData: FiresGeoJSON | null
  onFlyTo: (lng: number, lat: number, zoom?: number) => void
  selectedDate: string | null
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

type View = { type: 'list' } | { type: 'detail'; fire: FireFeature; index: number }

export function FiresPanel({ firesData, onFlyTo, selectedDate }: FiresPanelProps) {
  const [sortBy, setSortBy] = useState<'frp' | 'confidence'>('frp')
  const [view, setView] = useState<View>({ type: 'list' })

  const features = firesData?.features ?? []

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

  const displayDate = firesData?.date || selectedDate
  const formattedDate = displayDate
    ? new Date(displayDate).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
    : ''

  // ── Loading state ──
  if (!firesData) {
    return (
      <div className="flex-1 flex items-center justify-center bg-[#fafbfc]">
        <div className="flex items-center gap-2 text-slate-400 text-sm">
          <div className="w-4 h-4 border-2 border-slate-300 border-t-slate-500 rounded-full animate-spin" />
          Loading fires...
        </div>
      </div>
    )
  }

  // ── Fire detail view ──
  if (view.type === 'detail') {
    const f = view.fire
    const [lng, lat] = f.geometry.coordinates
    const { frp, confidence, satellite, acq_date } = f.properties

    return (
      <div className="flex flex-col h-full bg-[#fafbfc]">
        <button
          onClick={() => setView({ type: 'list' })}
          className="flex items-center gap-1 px-5 py-3 text-[12px] font-medium text-slate-400 hover:text-slate-600 transition-colors w-full"
        >
          <ChevronLeft size={14} strokeWidth={2} /> All Fires
        </button>
        <div className="flex-1 overflow-y-auto scrollbar-hide">
          {/* Header */}
          <div className="px-5 pb-4">
            <h2 className="text-[20px] font-semibold text-[#1e293b] leading-snug tracking-[-0.01em]">
              Fire #{view.index + 1}
            </h2>
            <p className="text-[12px] text-[#94a3b8] mt-1 leading-relaxed">
              {lat.toFixed(4)}°N, {lng.toFixed(4)}°E &middot; {satellite}
            </p>
            <span className={`inline-flex items-center mt-2.5 text-[10px] font-semibold uppercase tracking-wide px-2.5 py-[3px] rounded-full ${confidenceBadgeBg(confidence)}`}>
              {confidenceLabel(confidence)} confidence
            </span>
          </div>

          {/* Satellite image */}
          <div className="px-4 pb-3">
            <SatelliteImage
              lat={lat}
              lon={lng}
              name={`Fire detection at ${lat.toFixed(4)}, ${lng.toFixed(4)}`}
              zoom="close"
              label="Fire location"
              markerColor={confidenceColor(confidence)}
            />
          </div>

          {/* Details card */}
          <div className="px-4 pb-4">
            <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
              <div className="px-4 py-2.5 border-b border-slate-100">
                <span className="text-[12px] font-bold text-slate-700">Fire Details</span>
              </div>
              <div className="px-4 py-3 grid grid-cols-2 gap-x-6 gap-y-2.5 text-[11px]">
                <div>
                  <div className="text-slate-400 text-[10px]">Fire Radiative Power</div>
                  <div className="text-slate-700 font-medium">{frp} MW</div>
                </div>
                <div>
                  <div className="text-slate-400 text-[10px]">Intensity</div>
                  <div className="text-slate-700 font-medium">{frpCategory(frp)}</div>
                </div>
                <div>
                  <div className="text-slate-400 text-[10px]">Confidence</div>
                  <div className="font-medium" style={{ color: confidenceColor(confidence) }}>{confidenceLabel(confidence)}</div>
                </div>
                <div>
                  <div className="text-slate-400 text-[10px]">Satellite</div>
                  <div className="text-slate-700 font-medium">{satellite}</div>
                </div>
                <div>
                  <div className="text-slate-400 text-[10px]">Detection Date</div>
                  <div className="text-slate-700 font-medium">{acq_date}</div>
                </div>
                <div>
                  <div className="text-slate-400 text-[10px]">Coordinates</div>
                  <div className="text-slate-700 font-medium">{lat.toFixed(5)}, {lng.toFixed(5)}</div>
                </div>
              </div>
            </div>
          </div>

          {/* Fly-to button */}
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
      {/* Header */}
      <div className="px-5 pt-5 pb-3 border-b border-slate-100">
        <div className="flex items-center gap-2 mb-1">
          <Flame size={16} className="text-orange-500" />
          <span className="text-[13px] font-semibold text-slate-800">Active Fires</span>
        </div>
        <div className="text-[11px] text-slate-500 mb-3">{formattedDate} &middot; FIRMS VIIRS</div>

        {/* Summary pills */}
        <div className="flex gap-2">
          <div className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-orange-50 border border-orange-100">
            <span className="text-[18px] font-bold text-orange-600">{features.length}</span>
            <span className="text-[10px] text-orange-600/70 font-medium">total</span>
          </div>
          <div className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-red-50 border border-red-100">
            <span className="text-[18px] font-bold text-red-600">{highCount}</span>
            <span className="text-[10px] text-red-600/70 font-medium">high conf.</span>
          </div>
        </div>
      </div>

      {/* Sort control */}
      {features.length > 0 && (
        <div className="px-5 py-2 border-b border-slate-100/80 flex items-center gap-2">
          <span className="text-[10px] text-slate-400 font-medium uppercase tracking-wider">Sort</span>
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as 'frp' | 'confidence')}
            className="text-[11px] text-slate-600 bg-white border border-slate-200 rounded px-2 py-1 outline-none focus:border-slate-400"
          >
            <option value="frp">Fire Power (FRP)</option>
            <option value="confidence">Confidence</option>
          </select>
        </div>
      )}

      {/* Fire list */}
      <div className="flex-1 overflow-y-auto">
        {features.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-400 gap-2">
            <Flame size={24} className="opacity-30" />
            <span className="text-[12px]">No fire detections for this date</span>
          </div>
        ) : (
          sorted.map((f, i) => {
            const [lng, lat] = f.geometry.coordinates
            const { frp, confidence, satellite } = f.properties
            return (
              <button
                key={i}
                onClick={() => {
                  setView({ type: 'detail', fire: f as FireFeature, index: i })
                  onFlyTo(lng, lat, 12)
                }}
                className="w-full flex items-center gap-3 px-5 py-2.5 hover:bg-slate-50 border-b border-slate-100/80 text-left transition-colors"
              >
                {/* Confidence dot */}
                <div
                  className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                  style={{ background: confidenceColor(confidence) }}
                />
                {/* Details */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-baseline gap-2">
                    <span className="text-[12px] font-semibold text-slate-800">{frp} MW</span>
                    <span
                      className="text-[10px] font-medium"
                      style={{ color: confidenceColor(confidence) }}
                    >
                      {confidenceLabel(confidence)}
                    </span>
                  </div>
                  <div className="text-[10px] text-slate-400">
                    {satellite} &middot; {lat.toFixed(3)}, {lng.toFixed(3)}
                  </div>
                </div>
                {/* Chevron */}
                <ChevronLeft size={12} className="text-slate-300 flex-shrink-0 rotate-180" />
              </button>
            )
          })
        )}
      </div>
    </div>
  )
}
