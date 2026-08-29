// TypeScript interfaces for the Analyst Desk forecast data

export interface ForecastEntry {
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
  type: 'zoom_to_city' | 'zoom_to_station' | 'set_horizon' | 'filter_network' | 'show_station_trend'
  city?: string
  sensor_id?: number
  station_id?: string
  station_name?: string
  lat?: number
  lng?: number
  horizon?: number
  network?: string | null  // null = show all / clear filter
  hours?: number
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  actions?: CopilotAction[]
  streaming?: boolean
}
