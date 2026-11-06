// TypeScript interfaces for the Analyst Desk forecast data

export interface ForecastEntry {
  station_id?: string | null
  sensor_id: number
  station_name: string
  latitude: number | null
  longitude: number | null
  city_name: string
  state_name: string
  init_date: string
  lead_days: number
  target_date: string
  pm25_forecast: number | null
  pm25_q75: number | null
  pm25_q90: number | null
  ramp_detected: boolean
  source_ifs: boolean
  source_cams: boolean
  source_geos_cf: boolean
  mos_applied: boolean
  risk_band: string
  episode_state: string
  confidence: string
  priority: string
  /** Observation availability behind this row (pipeline ≥ Nov 2026; absent in older files) */
  obs_available?: boolean
  obs_age_days?: number | null
  obs_last_date?: string | null
  obs_t0_source?: string | null
  obs_stale?: boolean
  /** model = station had an observation; neighbours = estimated from nearby observed stations; prior = model value with no station signal */
  forecast_basis?: 'model' | 'neighbours' | 'prior' | string
  in_live_map?: boolean | null
  last_reading_utc?: string | null
}

export type ForecastBasis = 'model' | 'neighbours' | 'prior'

/** One lead of the hourly nowcast (+3/+6/+12/+24 h); values are null when basis is "prior" */
export interface NowcastLeadValue {
  lead_hours: number
  /** ISO UTC instant the value is for */
  valid_time: string
  pm25: number | null
  q75: number | null
  q90: number | null
}

export interface NowcastStation {
  sensor_id: number
  station_id: string | null
  /** Hawanama station ids that map onto this site (renamed or re-keyed stations) */
  member_station_ids: string[]
  station_name: string | null
  city: string | null
  latitude: number
  longitude: number
  basis: ForecastBasis | string
  /** Enough recent hourly readings (≥12 in 24 h, newest ≤3 h old) to run the model on this station */
  forecastable: boolean
  last_obs: number | null
  obs_age_h: number | null
  n_valid_24h: number
  leads: NowcastLeadValue[]
}

/** nowcast/latest.json as published by the nowcast job every 3 h */
export interface NowcastResponse {
  init_time: string
  generated_at: string
  model_tag: string
  leads: number[]
  n_stations: number
  data_quality: Record<string, unknown>
  stations: NowcastStation[]
}

export const BASIS_LABEL: Record<string, string> = {
  model: 'From station observations',
  neighbours: 'Estimated from nearby stations (no live data here)',
  prior: 'Model estimate only (no live data nearby)',
}

export interface ForecastResponse {
  init_date: string
  horizons: number[]
  generated_at: string
  n_stations: number
  n_rows: number
  data_quality: Record<string, unknown>
  forecasts: ForecastEntry[]
  watchlist_summary?: Record<string, number>
}

export interface WatchlistEntry {
  sensor_id: number
  station_name: string
  city_name: string
  reason: string
  [key: string]: unknown
}

export interface WatchlistResponse {
  init_date: string
  generated_at: string
  watchlists: Record<string, WatchlistEntry[]>
}

export interface HorizonStats {
  n_stations: number
  pm25_median: number | null
  pm25_mean: number | null
  pm25_max: number | null
  q90_max: number | null
  worst_band: string
  frac_unhealthy: number
  n_ramp: number
  confidence: string
  n_low_confidence: number
  n_escalate: number
  n_review: number
}

export interface CitySummary {
  name: string
  group_type: string
  state_name?: string
  horizons: Record<string, HorizonStats>
  trend: string
  trend_delta: number
}

export interface SummaryResponse {
  init_date: string
  generated_at: string
  city_summaries: CitySummary[]
  province_summaries: CitySummary[]
}

export interface CurrentStation {
  id: string
  name: string
  latitude: number
  longitude: number
  city: string
  pm25: number | null
  aqi_raw: number | null
  aqi_category: string
  last_reading: string
}

export type TabType = 'overview' | 'map' | 'watchlists' | 'cities' | 'stations'

export interface StationMention {
  sensorId: number
  stationName: string
  cityName: string
}

// ── Copilot types ─────────────────────────────────────────────────────

export interface CopilotAction {
  type: 'zoom_to_city' | 'zoom_to_station' | 'set_horizon' | 'filter_network' | 'show_station_trend' | 'show_trajectory'
  city?: string
  sensor_id?: number
  station_id?: string
  station_name?: string
  lat?: number
  lng?: number
  horizon?: number
  network?: string | null  // null = show all / clear filter
  hours?: number
  // show_trajectory: the server emits it when the copilot computed a trajectory; the chat draws it
  lon?: number
  at?: string
  direction?: 'backward' | 'forward'
  label?: string
  engine?: string
}

export type ChatMessageStatus = 'ok' | 'stopped' | 'limit' | 'busy' | 'unavailable' | 'error'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  actions?: CopilotAction[]
  streaming?: boolean
  /** How an assistant reply ended; undefined while streaming and for the published brief */
  status?: ChatMessageStatus
  /** Why the reply ended early, shown under whatever text arrived */
  notice?: string
}
