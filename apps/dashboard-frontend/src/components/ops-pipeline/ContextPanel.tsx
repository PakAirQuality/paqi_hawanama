'use client'

import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronUp, ChevronDown, ChevronLeft, ChevronRight, Info } from 'lucide-react'
import { AnimatePresence, m } from 'motion/react'
import { AqiCard } from '@/components/shared/AqiCard'
import { AnimatedNumber } from '@/components/shared/AnimatedNumber'
import { Skeleton } from '@/components/shared/Skeleton'
import type { StationReading, PredictionData, RunReport } from './types'
import { fetchDailyBrief } from './api'
import { BAND_KEYS, bandColor, bandCounts, bandKey, bandLabel, classifyPm25, unhealthyOrWorse, BAND_SCALE_LABEL } from '@/lib/aqi'
import { MIN_CITY_MONITORS, worstRankedCities } from '@/lib/cityRanking'
import { formatDateOnly } from '@/lib/time'
import { useIsMobile } from '@/lib/useMediaQuery'
import { MODEL_HELP, MODEL_LABELS, type ModelKey } from '@/lib/selection'

interface OpsContextPanelProps {
  selectedDate: string | null
  model: ModelKey
  onModelChange: (m: ModelKey) => void
  stations: StationReading[]
  /** stats of the prediction grid for `model` (an area average over the model domain) */
  predictionStats: PredictionData['stats'] | null
  runReport: RunReport | null
  /** fly the map to a place (lng, lat, zoom) */
  onFlyTo?: (lng: number, lat: number, zoom?: number) => void
  /** Which part of the timeline the card describes */
  mode?: 'day' | 'now' | 'forecast'
  /** Replaces the date line, for today and forecast days */
  dayLabel?: string
  /** What a station's number means in this view */
  readingLabel?: string
  /** A warning under the date, such as a forecast that has fallen behind */
  notice?: string | null
  /** A line about the data behind the view, for today and forecast days */
  detail?: string | null
  /** Fires and forecast ramps, for today and forecast days */
  evidence?: { fires: string; firesLabel: string; firesWarn: boolean; ramps: number } | null
  /** Air quality where the visitor is: the nearest monitor, or none within range */
  nearby?: { station: { name: string; city: string; pm25: number } | null; distKm: number | null; radiusKm: number } | null
}

interface Obs {
  count: number
  mean: number
  max: number
  band: string
  bands: ReturnType<typeof bandCounts>
  worstCities: { city: string; avg: number; count: number; lat: number; lon: number }[]
}

export function OpsContextPanel({ selectedDate, model, onModelChange, stations, predictionStats, runReport, onFlyTo, nearby, mode = 'day', dayLabel, readingLabel = 'PM2.5 daily mean', notice, detail, evidence }: OpsContextPanelProps) {
  const isMobile = useIsMobile()
  const [hidden, setHidden] = useState(false)
  const [seenMobile, setSeenMobile] = useState(false)
  if (isMobile && !seenMobile) { setSeenMobile(true); setHidden(true) }
  const [showModelHelp, setShowModelHelp] = useState(false)

  const obs = useMemo<Obs | null>(() => {
    const valid = stations.filter(s => s.pm25 != null)
    if (!valid.length) return null
    const values = valid.map(s => s.pm25)
    const mean = values.reduce((a, b) => a + b, 0) / values.length
    const max = Math.max(...values)
    const cityMap: Record<string, { vals: number[]; lat: number; lon: number; n: number }> = {}
    valid.forEach(s => {
      if (!s.city) return
      const lat = s.lat ?? s.latitude, lon = s.lon ?? s.longitude
      const c = (cityMap[s.city] ??= { vals: [], lat: 0, lon: 0, n: 0 })
      c.vals.push(s.pm25)
      if (lat != null && lon != null) { c.lat += lat; c.lon += lon; c.n += 1 }
    })
    const worstCities = Object.entries(cityMap)
      .filter(([, c]) => c.n > 0)
      .map(([city, c]) => ({ city, avg: c.vals.reduce((a, b) => a + b, 0) / c.vals.length, count: c.vals.length, lat: c.lat / c.n, lon: c.lon / c.n }))
      .sort((a, b) => b.avg - a.avg)
    return { count: valid.length, mean, max: Math.round(max), band: bandKey(mean), bands: bandCounts(values), worstCities }
  }, [stations])
  const rankedCities = worstRankedCities(obs?.worstCities ?? [])

  const coverage = predictionStats?.n_total
    ? Math.round((predictionStats.n_valid / predictionStats.n_total) * 100) : null

  // Only the matched-station bias is used from the daily brief response (shown in Model details)
  const { data: brief } = useQuery({
    queryKey: ['ops-brief', selectedDate],
    queryFn: () => fetchDailyBrief(selectedDate!),
    enabled: !!selectedDate,
    staleTime: Infinity,
    retry: 1,
  })

  const matched = brief?.matched_bias?.[model] ?? null
  const modelLabel = MODEL_LABELS[model]

  const formattedDate = dayLabel ?? (selectedDate
    ? formatDateOnly(selectedDate, { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' })
    : '—')
  const forecast = mode === 'forecast'

  const unhealthyCount = obs ? unhealthyOrWorse(obs.bands) : 0

  // Show the card again when a location result arrives (it starts tucked away on phones)
  const [seenNearby, setSeenNearby] = useState<typeof nearby>(null)
  if (nearby && nearby !== seenNearby) { setSeenNearby(nearby); setHidden(false) }
  const total = obs?.count ?? 0

  return (
    <>
    <AnimatePresence>
    {!hidden && (
    <m.section
      key="card"
      aria-label="Daily assessment"
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0, x: 0 }}
      exit={{ opacity: 0, x: '110%' }}
      transition={{ duration: 0.28, ease: [0.2, 0.8, 0.2, 1] }}
      className="absolute top-3 left-3 right-3 md:left-auto md:right-4 md:w-[352px] md:max-w-[calc(100%-2rem)] z-10 flex flex-col rounded-2xl overflow-y-auto overflow-x-hidden overscroll-contain max-h-[calc(100%-236px)] md:max-h-[calc(100%-200px)] text-slate-900"
      style={{
        background: 'rgba(255,255,255,0.82)',
        backdropFilter: 'blur(20px) saturate(180%)',
        WebkitBackdropFilter: 'blur(20px) saturate(180%)',
        border: '1px solid rgba(15,23,42,0.08)',
        boxShadow: '0 8px 32px rgba(15,23,42,0.14)',
      }}
    >
      {/* ── Header ── */}
      <div className="flex items-start justify-between gap-2 px-4 pt-3.5">
        <div className="min-w-0">
          <div className="text-[15px] font-semibold tracking-tight">Pakistan</div>
          <div className="mt-0.5 text-xs text-slate-600" title={mode === 'day' ? 'Daily means of hourly PM2.5, Pakistan time' : undefined}>{formattedDate}</div>
          {notice && <div className="mt-1.5 rounded-md bg-amber-50 px-2 py-1 text-xs text-amber-800">{notice}</div>}
        </div>
        <button
          onClick={() => setHidden(true)}
          className="-mr-1.5 -mt-1 rounded-lg p-1.5 text-slate-500 hover:bg-slate-900/5 hover:text-slate-900 transition-colors"
          aria-label="Hide Pakistan summary to the right"
        >
          <ChevronRight size={16} />
        </button>
      </div>

      {/* ── Headline (always visible): how many stations are unhealthy, then the five worst cities ── */}
      {nearby && (
        <div className="px-4 pt-3">
          <div className="mb-1.5 text-xs font-semibold text-slate-600">Near you</div>
          {nearby.station ? (
            <AqiCard
              className="shadow-none"
              pm25={nearby.station.pm25}
              title={nearby.station.name}
              subtitle={`${nearby.station.city}, ${nearby.distKm != null ? (nearby.distKm < 1 ? 'under 1' : Math.round(nearby.distKm)) : ''} km away`}
              caption={readingLabel}
            />
          ) : (
            <p className="text-[13px] text-slate-700">No monitor within {nearby.radiusKm} km of your location.</p>
          )}
        </div>
      )}

      {!obs && (
        <div className="px-4 pt-3 pb-4" aria-busy="true" aria-label="Loading stations">
          <Skeleton className="h-10 w-3/4" />
          <Skeleton className="mt-3 h-2 w-full rounded-full" />
          <Skeleton className="mt-5 h-3 w-24" />
          {[0, 1, 2, 3, 4].map(i => <Skeleton key={i} className="mt-3 h-9 w-full" />)}
        </div>
      )}

      {obs && (
        <div className="px-4 pt-3 pb-3.5">
          <div className="flex items-center gap-2.5">
            <AnimatedNumber value={unhealthyCount} className="text-[40px] leading-none font-semibold tabular-nums tracking-tight" />
            <span className="text-sm leading-snug text-slate-700">of {obs.count} stations {forecast ? 'forecast' : 'are'} Unhealthy or worse</span>
          </div>

          {/* Composition at a glance: same colours as the map markers; hover a segment for its count */}
          <div
            className="mt-3 flex h-2 gap-px overflow-hidden rounded-full"
            role="img"
            aria-label={BAND_KEYS.filter(k => obs.bands[k] > 0).map(k => `${obs.bands[k]} ${bandLabel(k)}`).join(', ')}
          >
            {BAND_KEYS.map(k => obs.bands[k] > 0 ? (
              <div
                key={k}
                title={`${obs.bands[k]} ${bandLabel(k)}`}
                style={{ width: `${(obs.bands[k] / total) * 100}%`, background: bandColor(k) }}
              />
            ) : null)}
          </div>

          {/* Five worst cities, each flies the map to the city */}
          <div className="mt-4 text-xs font-semibold text-slate-600">
            Worst {rankedCities.length === 5 ? 'five ' : ''}cities
          </div>
          <div className="text-xs text-slate-500">With more than {MIN_CITY_MONITORS - 1} monitors {forecast ? 'forecast' : 'reporting'}</div>
          {rankedCities.length === 0 && (
            <p className="mt-1 text-[13px] text-slate-600">No city has that many monitors {forecast ? 'forecast' : 'reporting'} for this day.</p>
          )}
          <ul className="mt-1 -mx-2">
            {rankedCities.map(c => {
              const b = classifyPm25(c.avg)
              return (
                <li key={c.city}>
                  <button
                    onClick={() => onFlyTo?.(c.lon, c.lat, 10.5)}
                    disabled={!onFlyTo}
                    aria-label={`Fly to ${c.city}`}
                    className="group flex w-full items-center gap-3 rounded-lg px-2 py-1.5 text-left hover:bg-slate-900/[0.05] focus-visible:bg-slate-900/[0.05] transition-colors"
                  >
                    <span
                      className="min-w-[44px] shrink-0 rounded-full px-2.5 py-0.5 text-center text-xs font-semibold tabular-nums"
                      style={{ background: b.color, color: b.textColor }}
                      title={b.label}
                    >
                      <AnimatedNumber value={Math.round(c.avg)} />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13px] font-medium text-slate-900">{c.city}</span>
                      <span className="block text-xs text-slate-600">{c.count} station{c.count > 1 ? 's' : ''}, {b.label}</span>
                    </span>
                    <ChevronRight size={16} className="shrink-0 text-slate-400 group-hover:text-slate-700" aria-hidden />
                  </button>
                </li>
              )
            })}
          </ul>
        </div>
      )}

      <div>
            {/* ── Model switch: the satellite models describe past days, not forecasts ── */}
            {!forecast && <div className="px-4 pt-3">
              <div className="flex items-center gap-1 rounded-xl bg-slate-900/[0.06] p-1" role="group" aria-label="Prediction model">
                {([['backbone', 'Satellite'], ['support_aware', 'Enhanced']] as const).map(([key, label]) => (
                  <button
                    key={key}
                    onClick={() => onModelChange(key)}
                    aria-pressed={model === key}
                    className={`relative flex-1 rounded-lg py-1.5 text-[13px] font-medium transition-colors ${model === key ? 'text-slate-900' : 'text-slate-600 hover:text-slate-900'}`}
                  >
                    {model === key && (
                      <m.span
                        layoutId="model-pill"
                        transition={{ type: 'spring', stiffness: 400, damping: 32 }}
                        className="absolute inset-0 rounded-lg bg-white shadow-sm"
                      />
                    )}
                    <span className="relative">{label}</span>
                  </button>
                ))}
                <button
                  onClick={() => setShowModelHelp(v => !v)}
                  className="rounded-lg p-1.5 text-slate-500 hover:text-slate-900"
                  aria-label="Explain model modes"
                  aria-expanded={showModelHelp}
                >
                  <Info size={14} />
                </button>
              </div>
              {showModelHelp && (
                <div className="mt-2 space-y-1 text-xs leading-snug text-slate-700">
                  <div><span className="font-semibold">Satellite:</span> {MODEL_HELP.backbone}</div>
                  <div><span className="font-semibold">Enhanced:</span> {MODEL_HELP.support_aware}</div>
                </div>
              )}
            </div>}

            <div className="pb-1 pt-3">
              <div>
                  {obs && (
                    <div className="px-4 pb-2 text-xs text-slate-600">
                      Station mean {Math.round(obs.mean)} µg/m³ across {obs.count} stations (unweighted, not an area or population average){mode === 'day' ? '' : `, peak ${obs.max} µg/m³`}.
                      {detail && <span className="mt-1 block">{detail}</span>}
                    </div>
                  )}
            {evidence && (
              <div className="grid grid-cols-2 gap-2 px-4 pt-1">
                <div className="rounded-xl bg-slate-900/[0.04] px-3 py-2.5">
                  <div className="text-base font-semibold tabular-nums">{evidence.fires}</div>
                  <div className={`text-xs ${evidence.firesWarn ? 'text-amber-700' : 'text-slate-600'}`}>{evidence.firesLabel}</div>
                </div>
                <div className="rounded-xl bg-slate-900/[0.04] px-3 py-2.5">
                  <div className="text-base font-semibold tabular-nums">{evidence.ramps}</div>
                  <div className="text-xs text-slate-600">Forecast ramp events</div>
                </div>
              </div>
            )}
            {!forecast && <div className="grid grid-cols-2 gap-2 px-4 pt-3">
              <div className="rounded-xl bg-slate-900/[0.04] px-3 py-2.5">
                <div className="text-xs text-slate-600">Modelled area average</div>
                <div className="mt-0.5 text-base font-semibold tabular-nums">
                  {predictionStats?.mean != null ? `${Math.round(predictionStats.mean)} µg/m³` : '—'}
                </div>
                <div className="text-xs text-slate-600">{modelLabel}</div>
                {coverage != null && <div className="text-xs text-slate-600">{coverage}% grid coverage</div>}
              </div>
              <div className="rounded-xl bg-slate-900/[0.04] px-3 py-2.5">
                <div className="text-xs text-slate-600">Matched-station bias</div>
                <div className="mt-0.5 text-base font-semibold tabular-nums">
                  {matched ? `${matched.bias > 0 ? '+' : ''}${matched.bias.toFixed(1)} µg/m³` : '—'}
                </div>
                <div className="text-xs text-slate-600">{matched ? `MAE ${matched.mae.toFixed(1)} across ${matched.n} stations` : 'no matched comparison'}</div>
              </div>
            </div>}

            <div className="px-4 py-3 text-xs text-slate-500">
              {!forecast && runReport?.model_version ? `Model ${runReport.model_version}. ` : ''}{BAND_SCALE_LABEL}.
            </div>
              </div>
            </div>
      </div>
    </m.section>
    )}
    </AnimatePresence>

    {/* Handle that brings the card back from the right edge */}
    <AnimatePresence>
      {hidden && (
        <m.button
          key="handle"
          onClick={() => setHidden(false)}
          aria-label="Show Pakistan summary"
          initial={{ x: 48, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: 48, opacity: 0 }}
          transition={{ type: 'spring', stiffness: 420, damping: 34 }}
          className="absolute top-3 right-0 z-10 flex items-center gap-1.5 rounded-l-xl py-2.5 pl-3 pr-2.5 text-[13px] font-medium text-slate-900"
          style={{
            background: 'rgba(255,255,255,0.82)',
            backdropFilter: 'blur(20px) saturate(180%)',
            WebkitBackdropFilter: 'blur(20px) saturate(180%)',
            boxShadow: '0 8px 32px rgba(15,23,42,0.14)',
          }}
        >
          <ChevronLeft size={16} aria-hidden />
          Pakistan
        </m.button>
      )}
    </AnimatePresence>
    </>
  )
}
