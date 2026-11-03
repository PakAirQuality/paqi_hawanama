// The Tracker's timeline: past days, then today's live readings, then the forecast days.

import type { CurrentStation, ForecastEntry } from '@/components/analyst-desk/types'
import type { StationReading } from '@/components/ops-pipeline/types'

export type ForecastLead = 1 | 2 | 3
/** Today or a forecast day; a past day is a plain YYYY-MM-DD date. */
export type FutureStep = 'now' | ForecastLead
export type TimelineStep = string | FutureStep

export const isForecastLead = (step: TimelineStep | null): step is ForecastLead => typeof step === 'number'
const isLead = (n: number): n is ForecastLead => n === 1 || n === 2 || n === 3

/** Forecast days still ahead of `today`. A stalled forecast job then shows nothing, not old numbers. */
export function availableLeads(forecasts: ForecastEntry[], today: string): ForecastLead[] {
  const leads = new Set<ForecastLead>()
  for (const f of forecasts) {
    if (f.pm25_forecast != null && f.target_date > today && isLead(f.lead_days)) leads.add(f.lead_days)
  }
  return [...leads].sort()
}

export function targetDate(forecasts: ForecastEntry[], lead: ForecastLead): string | null {
  return forecasts.find(f => f.lead_days === lead)?.target_date ?? null
}

/** Whole days from one YYYY-MM-DD to another. */
export const daysBetween = (from: string, to: string) => Math.round((Date.parse(to) - Date.parse(from)) / 86_400_000)

/** The forecast day that many days after `today`. Leads count from the run, which may be a day old. */
export function leadForDaysAhead(forecasts: ForecastEntry[], today: string, days: number): ForecastLead | null {
  for (const lead of [1, 2, 3] as const) {
    const date = targetDate(forecasts, lead)
    if (date && daysBetween(today, date) === days) return lead
  }
  return null
}

/** One forecast day as map readings; a station listed twice counts once. */
export function forecastReadings(forecasts: ForecastEntry[], lead: ForecastLead): StationReading[] {
  const seen = new Set<string>()
  const out: StationReading[] = []
  for (const f of forecasts) {
    if (f.lead_days !== lead || f.pm25_forecast == null || f.latitude == null || f.longitude == null) continue
    const key = `${f.station_name}|${f.city_name}`
    if (seen.has(key)) continue
    seen.add(key)
    out.push({
      name: f.station_name, city: f.city_name, pm25: f.pm25_forecast, lat: f.latitude, lon: f.longitude,
      station_id: f.station_id ?? undefined,
      basis: f.forecast_basis ?? undefined,
      obs_available: f.obs_available ?? undefined,
    })
  }
  return out
}

export interface StationForecastDay {
  date: string
  lead: ForecastLead
  pm25: number
  /** 90th percentile of the forecast */
  high: number | null
  /** model | neighbours | prior (absent for forecasts made before Nov 2026) */
  basis?: string
}

/** Stations in a forecast day with and without a live observation behind them. */
export function obsCoverage(forecasts: ForecastEntry[], lead: ForecastLead): { total: number; withObs: number; known: boolean } {
  let total = 0, withObs = 0, known = false
  for (const f of forecasts) {
    if (f.lead_days !== lead || f.pm25_forecast == null) continue
    total++
    if (f.obs_available != null) known = true
    if (f.obs_available === true) withObs++
  }
  return { total, withObs, known }
}

/** One station's forecast days still ahead of `today`, soonest first. */
export function stationForecastDays(forecasts: ForecastEntry[], today: string, name: string, city: string): StationForecastDay[] {
  const days = new Map<ForecastLead, StationForecastDay>()
  for (const f of forecasts) {
    if (f.station_name !== name || f.city_name !== city || f.pm25_forecast == null || f.target_date <= today) continue
    if (!isLead(f.lead_days) || days.has(f.lead_days)) continue
    days.set(f.lead_days, { date: f.target_date, lead: f.lead_days, pm25: f.pm25_forecast, high: f.pm25_q90, basis: f.forecast_basis ?? undefined })
  }
  return [...days.values()].sort((a, b) => a.lead - b.lead)
}

/** Latest hourly readings as map readings. */
export function liveReadings(stations: CurrentStation[]): StationReading[] {
  return stations
    .filter(s => s.pm25 != null && s.latitude != null && s.longitude != null)
    .map(s => ({ name: s.name, city: s.city, pm25: s.pm25 as number, lat: s.latitude, lon: s.longitude, station_id: s.id }))
}

/** Stations where the forecast expects a sharp rise that day. */
export function rampCount(forecasts: ForecastEntry[], lead: ForecastLead): number {
  return forecasts.filter(f => f.lead_days === lead && f.ramp_detected).length
}

/** Newest reading's timestamp, or null when none carry one. */
export function latestReading(stations: CurrentStation[]): string | null {
  return stations.map(s => s.last_reading).filter(Boolean).sort().at(-1) ?? null
}
