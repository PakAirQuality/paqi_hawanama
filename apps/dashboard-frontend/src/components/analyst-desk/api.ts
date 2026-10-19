// API functions for Analyst Desk — calls FastAPI backend

import type {
  ForecastResponse,
  WatchlistResponse,
  SummaryResponse,
  CurrentStation,
} from './types'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://hawanama-152782825429.asia-south1.run.app"

// Public read-only routes; no credential is ever sent from the browser.
const headers: Record<string, string> = {}

const DESK_PREFIX = `${API_BASE}/api/v1/ops/analyst-desk`

export async function fetchForecast(date: string): Promise<ForecastResponse> {
  const res = await fetch(`${DESK_PREFIX}/forecasts?date=${date}`, {
    headers,
    cache: 'no-store',
  })
  if (!res.ok) throw new Error(`Failed to load forecast for ${date}`)
  return res.json()
}

export async function fetchWatchlist(date: string): Promise<WatchlistResponse> {
  const res = await fetch(`${DESK_PREFIX}/watchlists?date=${date}`, {
    headers,
    cache: 'no-store',
  })
  if (!res.ok) throw new Error(`Failed to load watchlists for ${date}`)
  return res.json()
}

export async function fetchSummary(date: string): Promise<SummaryResponse> {
  const res = await fetch(`${DESK_PREFIX}/summaries?date=${date}&level=all`, {
    headers,
    cache: 'no-store',
  })
  if (!res.ok) throw new Error(`Failed to load summary for ${date}`)
  return res.json()
}

export async function fetchAvailableDates(): Promise<{ dates: string[]; count: number }> {
  const res = await fetch(`${DESK_PREFIX}/dates`, {
    headers,
    cache: 'no-store',
  })
  if (!res.ok) throw new Error('Failed to load available forecast dates')
  return res.json()
}

export async function fetchCurrentStations(): Promise<{ stations: CurrentStation[] }> {
  const res = await fetch(`${API_BASE}/api/v1/stations`, {
    headers,
    cache: 'no-store',
  })
  if (!res.ok) throw new Error('Failed to load current stations')
  return res.json()
}

export type FiresStatus = 'ok' | 'empty' | 'partial' | 'stale' | 'unavailable'

export interface FiresSource {
  source: string
  status: 'ok' | 'error'
  rows?: number
  error?: string | null
}

export interface FiresGeoJSON {
  type: "FeatureCollection"
  /** Pakistan day the detections belong to (may differ from requested_date when status is 'stale') */
  date: string
  requested_date?: string
  status?: FiresStatus
  count?: number
  layer?: string
  tz?: string
  day_basis?: 'acq_pkt' | 'acq_utc'
  sources?: FiresSource[] | null
  last_successful_fetch?: string | null
  /** Hours since last_successful_fetch, computed by the API */
  fetched_age_hours?: number | null
  observation_period?: { start: string; end: string } | null
  note?: string
  features: Array<{
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
  }>
}

export async function fetchFires(date: string): Promise<FiresGeoJSON> {
  const res = await fetch(`${DESK_PREFIX}/fires?date=${date}`, {
    headers,
    cache: 'no-store',
  })
  if (!res.ok) throw new Error(`Failed to load fires for ${date}`)
  return res.json()
}

export interface PM25Reading {
  timestamp_utc: string
  timestamp_pk: string
  pm25: number
}

export async function fetchStationPM25History(stationId: string, hours = 24): Promise<PM25Reading[]> {
  const res = await fetch(`${API_BASE}/api/v1/dashboard/stations/${stationId}/history/pm25?hours=${hours}`, {
    headers,
    cache: 'no-store',
  })
  if (!res.ok) throw new Error(`Failed to load PM2.5 history for ${stationId}`)
  return res.json()
}

export async function fetchStationDailyHistory(stationId: string, days = 30): Promise<PM25Reading[]> {
  const res = await fetch(`${API_BASE}/api/v1/dashboard/stations/${stationId}/history/pm25/daily?days=${days}`, {
    headers,
    cache: 'no-store',
  })
  if (!res.ok) throw new Error(`Failed to load daily PM2.5 history for ${stationId}`)
  return res.json()
}

export async function fetchOverview(date?: string): Promise<Record<string, unknown>> {
  const params = date ? `?date=${date}` : ''
  const res = await fetch(`${DESK_PREFIX}/overview${params}`, {
    headers,
    cache: 'no-store',
  })
  if (!res.ok) throw new Error('Failed to load forecast overview')
  return res.json()
}
