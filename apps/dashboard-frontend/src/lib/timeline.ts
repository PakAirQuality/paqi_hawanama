// The Tracker's timeline: past days, then today's live readings, then the forecast days.

import type { CurrentStation, ForecastEntry, NowcastResponse, NowcastStation } from '@/components/analyst-desk/types'
import type { StationReading } from '@/components/ops-pipeline/types'

export type ForecastLead = 1 | 2 | 3
/** Nowcast leads the Tracker shows (issued every 3 h). The API and nowcast/latest.json also carry +24 h;
 *  it is hidden here because it sits next to the D+1 daily mean and reads as a duplicate. */
export type NowcastLead = 3 | 6 | 12
export const NOWCAST_LEADS: readonly NowcastLead[] = [3, 6, 12]
/** An hourly nowcast step: the PM2.5 expected `h` hours after the cycle's init time */
export interface HourStep { kind: 'hour'; h: NowcastLead }
/** Today, an hourly nowcast step or a forecast day; a past day is a plain YYYY-MM-DD date. */
export type FutureStep = 'now' | HourStep | ForecastLead
export type TimelineStep = string | FutureStep

export const isForecastLead = (step: TimelineStep | null): step is ForecastLead => typeof step === 'number'
export const isHourStep = (step: TimelineStep | null | undefined): step is HourStep =>
  typeof step === 'object' && step !== null && step.kind === 'hour'
const isLead = (n: number): n is ForecastLead => n === 1 || n === 2 || n === 3
const isNowcastLead = (n: number): n is NowcastLead => (NOWCAST_LEADS as readonly number[]).includes(n)
export const hourStep = (h: NowcastLead): HourStep => ({ kind: 'hour', h })

/** Stable key for a step (object steps cannot be compared by identity): 'now' | 'h6' | '2' | a date */
export const stepKey = (step: TimelineStep | null | undefined): string =>
  step == null ? '' : isHourStep(step) ? `h${step.h}` : String(step)
export const sameStep = (a: TimelineStep | null | undefined, b: TimelineStep | null | undefined) => stepKey(a) === stepKey(b)

/** The `?view=` value for a step: today | h3..h12 | days ahead (given by the caller for forecast days) */
export function parseViewParam(v: string | null): { today?: true; hour?: NowcastLead; daysAhead?: number } | null {
  if (!v) return null
  if (v === 'today') return { today: true }
  const h = /^h(\d+)$/.exec(v)
  if (h) { const n = Number(h[1]); return isNowcastLead(n) ? { hour: n } : null }
  if (v === '1' || v === '2' || v === '3') return { daysAhead: Number(v) }
  return null
}

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

// ── Hourly nowcast ──

// A malformed station (no leads list) has no values rather than throwing
const leadValue = (s: NowcastStation, h: NowcastLead) => (Array.isArray(s?.leads) ? s.leads.find(l => l?.lead_hours === h) : undefined) ?? null

/** When the nowcast's values for `h` hours ahead are for (ISO UTC), or null when the cycle lacks that lead. */
export function nowcastValidTime(nowcast: NowcastResponse | null | undefined, h: NowcastLead): string | null {
  if (!nowcast || !Array.isArray(nowcast.stations)) return null
  for (const s of nowcast.stations) {
    const v = leadValue(s, h)
    if (v) return v.valid_time
  }
  return null
}

/** Nowcast leads still ahead of `nowIso` with at least one station value. A stalled job then shows nothing. */
export function availableHours(nowcast: NowcastResponse | null | undefined, nowIso: string): NowcastLead[] {
  if (!nowcast || !Array.isArray(nowcast.stations)) return []
  const now = Date.parse(nowIso)
  const out: NowcastLead[] = []
  for (const h of NOWCAST_LEADS) {
    const valid = nowcastValidTime(nowcast, h)
    if (!valid || Date.parse(valid) <= now) continue
    if (nowcast.stations.some(s => leadValue(s, h)?.pm25 != null)) out.push(h)
  }
  return out
}

/** Minutes between the cycle's init time and `nowIso`. */
export const nowcastAgeMin = (nowcast: NowcastResponse | null | undefined, nowIso: string): number | null =>
  nowcast ? Math.round((Date.parse(nowIso) - Date.parse(nowcast.init_time)) / 60_000) : null

/** The nowcast `h` hours ahead as map readings; stations with no value (basis "prior") are left out. */
export function nowcastReadings(nowcast: NowcastResponse | null | undefined, h: NowcastLead): StationReading[] {
  if (!nowcast) return []
  const out: StationReading[] = []
  for (const s of nowcast.stations) {
    const v = leadValue(s, h)
    if (!v || v.pm25 == null || s.latitude == null || s.longitude == null) continue
    out.push({
      name: s.station_name ?? '', city: s.city ?? '', pm25: v.pm25, lat: s.latitude, lon: s.longitude,
      station_id: s.station_id ?? s.member_station_ids?.[0] ?? undefined,
      basis: s.basis ?? undefined,
      obs_available: s.forecastable,
    })
  }
  return out
}

export interface StationNowcastPoint {
  lead: NowcastLead
  /** ISO UTC instant the value is for */
  valid_time: string
  pm25: number
  /** 90th percentile */
  high: number | null
  basis?: string
}

/** One station's nowcast points, soonest first. Matched by Hawanama id (own or member), else by name and city. */
export function stationNowcastPoints(
  nowcast: NowcastResponse | null | undefined,
  station: { station_id?: string | null; name: string; city: string },
): StationNowcastPoint[] {
  if (!nowcast || !Array.isArray(nowcast.stations)) return []
  const id = station.station_id?.trim()
  const byId = id ? nowcast.stations.find(s => s.station_id?.trim() === id || s.member_station_ids?.some(m => m.trim() === id)) : undefined
  const entry = byId ?? nowcast.stations.find(s => s.station_name === station.name && s.city === station.city)
  if (!entry) return []
  const out: StationNowcastPoint[] = []
  for (const h of NOWCAST_LEADS) {
    const v = leadValue(entry, h)
    if (!v || v.pm25 == null) continue
    out.push({ lead: h, valid_time: v.valid_time, pm25: v.pm25, high: v.q90, basis: entry.basis ?? undefined })
  }
  return out
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
