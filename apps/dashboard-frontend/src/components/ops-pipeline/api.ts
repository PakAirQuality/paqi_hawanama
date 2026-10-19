// API functions for Ops Pipeline

import type {
  PipelineSummary,
  RunsResponse,
  RunReport,
  PredictionsResponse,
  PredictionData,
  TileDatesResponse,
  ModelDetails,
  ModelHistoryResponse,
  ModelHistoryEntry,
  FeaturesListResponse,
  FeatureDatesResponse,
  StationDailyResponse,
} from './types'

export const API_BASE = "https://hawanama-152782825429.asia-south1.run.app"

// The dashboard is a public read-only site: every route it calls is public and
// rate-limited server-side. Never put a credential here; NEXT_PUBLIC_* values are
// compiled into the browser bundle.
const headers: Record<string, string> = {}

export async function fetchPipelineSummary(): Promise<PipelineSummary> {
  const res = await fetch(`${API_BASE}/api/v1/ops/pipeline/summary`, {
    headers,
    cache: 'no-store'
  })
  if (!res.ok) throw new Error("Failed to load pipeline summary")
  return res.json()
}

export async function fetchRuns(limit: number = 30): Promise<RunsResponse> {
  const res = await fetch(`${API_BASE}/api/v1/ops/pipeline/runs?limit=${limit}`, {
    headers,
    cache: 'no-store'
  })
  if (!res.ok) throw new Error("Failed to load runs")
  return res.json()
}

export async function fetchRunReport(date: string): Promise<RunReport> {
  const res = await fetch(`${API_BASE}/api/v1/ops/pipeline/runs/${date}`, {
    headers,
    cache: 'no-store'
  })
  if (!res.ok) throw new Error(`Failed to load run report for ${date}`)
  return res.json()
}

// Job triggers and execution listings are operator actions; they stay on the API behind
// TASKS_API_SECRET for Cloud Scheduler and the ops CLI, and are not reachable from here.

export async function fetchPredictions(limit: number = 30): Promise<PredictionsResponse> {
  const res = await fetch(`${API_BASE}/api/v1/ops/pipeline/predictions?limit=${limit}`, {
    headers,
    cache: 'no-store'
  })
  if (!res.ok) throw new Error("Failed to load predictions list")
  return res.json()
}

export async function fetchPredictionData(date: string, model: 'backbone' | 'support_aware' = 'backbone'): Promise<PredictionData> {
  const q = model !== 'backbone' ? `?model=${model}` : ''
  const res = await fetch(`${API_BASE}/api/v1/ops/pipeline/predictions/${date}${q}`, {
    headers,
    cache: 'no-store'
  })
  if (!res.ok) throw new Error(`Failed to load prediction data for ${date}`)
  return res.json()
}

export async function fetchTileDates(limit: number = 365): Promise<TileDatesResponse> {
  const res = await fetch(`${API_BASE}/api/v1/ops/pipeline/tiles/dates?limit=${limit}`, {
    headers,
    cache: 'no-store'
  })
  if (!res.ok) throw new Error("Failed to load tile dates")
  return res.json()
}

export function getTileJsonUrl(date: string): string {
  return `${API_BASE}/api/v1/ops/pipeline/tiles/${date}/tilejson`
}

export function getTileUrl(date: string, z: number, x: number, y: number): string {
  return `${API_BASE}/api/v1/ops/pipeline/tiles/${date}/${z}/${x}/${y}.png`
}

export function getPointQueryUrl(date: string, lat: number, lon: number): string {
  return `${API_BASE}/api/v1/ops/pipeline/tiles/${date}/point?lat=${lat}&lon=${lon}`
}

export async function fetchModelDetails(): Promise<ModelDetails> {
  const res = await fetch(`${API_BASE}/api/v1/ops/pipeline/model-details`, {
    headers,
    cache: 'no-store'
  })
  if (!res.ok) throw new Error("Failed to load model details")
  return res.json()
}

export async function fetchModelHistory(limit: number = 30): Promise<ModelHistoryResponse> {
  const res = await fetch(`${API_BASE}/api/v1/ops/pipeline/model-history?limit=${limit}`, {
    headers,
    cache: 'no-store'
  })
  if (!res.ok) throw new Error("Failed to load model history")
  return res.json()
}

export async function fetchModelHistoryEntry(referenceDate: string): Promise<ModelHistoryEntry> {
  const res = await fetch(`${API_BASE}/api/v1/ops/pipeline/model-history/${referenceDate}`, {
    headers,
    cache: 'no-store'
  })
  if (!res.ok) throw new Error(`Failed to load model history for ${referenceDate}`)
  return res.json()
}

export async function fetchFeaturesList(): Promise<FeaturesListResponse> {
  const res = await fetch(`${API_BASE}/api/v1/ops/pipeline/tiles/features`, {
    headers,
    cache: 'no-store'
  })
  if (!res.ok) throw new Error("Failed to load features list")
  return res.json()
}

export async function fetchFeatureDates(feature: string, limit: number = 365): Promise<FeatureDatesResponse> {
  const res = await fetch(`${API_BASE}/api/v1/ops/pipeline/tiles/features/dates?feature=${feature}&limit=${limit}`, {
    headers,
    cache: 'no-store'
  })
  if (!res.ok) throw new Error(`Failed to load dates for feature ${feature}`)
  return res.json()
}

export function getFeatureTileUrl(feature: string, date: string, z: number, x: number, y: number): string {
  return `${API_BASE}/api/v1/ops/pipeline/tiles/features/${feature}/${date}/${z}/${x}/${y}.png`
}

export function getFeaturePointQueryUrl(feature: string, date: string, lat: number, lon: number): string {
  return `${API_BASE}/api/v1/ops/pipeline/tiles/features/${feature}/${date}/point?lat=${lat}&lon=${lon}`
}

export async function fetchStationDaily(date: string, country?: string, minHours?: number): Promise<StationDailyResponse> {
  const q = new URLSearchParams()
  if (country) q.set('country', country)
  if (minHours != null) q.set('min_hours', String(minHours))
  const params = q.toString() ? `?${q}` : ''
  const res = await fetch(`${API_BASE}/api/v1/ops/pipeline/stations/daily/${date}${params}`, { headers })
  if (!res.ok) throw new Error(`Failed to load station data for ${date}`)
  return res.json()
}

export interface DailyBrief {
  date: string
  narrative: string
  station_count: number
  /** unweighted mean across reporting stations (same value as reporting_station_mean) */
  obs_mean: number | null
  reporting_station_mean?: number | null
  mean_basis?: string
  period?: { date: string; tz: string; aggregation: string }
  band_scale?: string
  /** area averages over the model grid, per model */
  grid_mean?: { backbone: number | null; support_aware: number | null }
  /** prediction sampled at station points minus observation, per model */
  matched_bias?: { backbone: { bias: number; mae: number; n: number } | null; support_aware: { bias: number; mae: number; n: number } | null }
  data_sources: {
    stations: boolean
    predictions: boolean
    watchlist: boolean
    fires: boolean
  }
}

export interface StationDirectoryItem {
  station_id: string
  name: string
  country: string
  state: string
  city: string
  lat: number
  lon: number
}

// Station shape as /api/v1/stations returns it (field names vary by row source)
type RawStation = {
  id?: string
  station_id?: string
  name: string
  country?: string
  state?: string
  city?: string
  latitude?: number
  longitude?: number
  lat?: number
  lon?: number
}

export async function fetchStationDirectory(country?: string): Promise<StationDirectoryItem[]> {
  const params = country ? `?country=${encodeURIComponent(country)}` : ''
  const res = await fetch(`${API_BASE}/api/v1/stations${params}`, { headers })
  if (!res.ok) throw new Error('Failed to load station directory')
  const data = await res.json()
  const stations = data.stations || data
  return stations.map((s: RawStation) => ({
    station_id: s.id || s.station_id,
    name: s.name,
    country: s.country || '',
    state: s.state || '',
    city: s.city || '',
    lat: s.latitude ?? s.lat,
    lon: s.longitude ?? s.lon,
  }))
}

export async function fetchDailyBrief(date: string): Promise<DailyBrief> {
  const res = await fetch(`${API_BASE}/api/v1/ops/pipeline/briefs/${date}`, { headers })
  if (!res.ok) throw new Error(`Failed to load brief for ${date}`)
  return res.json()
}
