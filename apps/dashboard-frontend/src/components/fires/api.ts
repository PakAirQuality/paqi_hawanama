// Fire trends page: fetchers and response types for /api/v1/fires (public, read-only, cached).

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? ''
export const FIRES_API = `${API_BASE}/api/v1/fires`

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

/** Retry only server errors; 400/404/429 are final (429 would only make the limit worse). */
export function retryServerErrorsOnly(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status < 500) return false
  return failureCount < 2
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${FIRES_API}${path}`)
  if (!res.ok) {
    let detail = `Request failed (${res.status})`
    try {
      const body = await res.json()
      if (typeof body?.detail === 'string') detail = body.detail
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail)
  }
  return res.json() as Promise<T>
}

export type SeasonId = 'rice' | 'wheat'
/** all = every satellite flown that day (deduplicated); n20 = NOAA-20 only, the series comparable across years. */
export type Basis = 'all' | 'n20'

export interface FiresMeta {
  store_built_at: string | null
  today_pkt: string
  store_schema_version?: number
  seasons: Record<SeasonId, { key: string; label: string; start: string; end: string }>
  season_window_note?: string
  current_season: SeasonId | null
  reference_years: number[]
  bases?: Record<Basis, string>
  consistent_satellite?: string
  n20_basis_available?: boolean
  regions: { id: string; label: string; kind: string; api: string }[]
  provinces: string[]
  districts: { name: string; province: string }[]
  archive: {
    first_day: string | null
    last_day: string | null
    gaps: Record<SeasonId, Record<string, [string, string][]>>
    suspect_days_by_year: Record<string, number>
    low_confidence_from: string | null
    pkt_from?: string | null
    days_without_pass_by_year?: Record<string, Record<string, number>>
  }
  satellites_by_year: Record<string, string[]>
  pass_times: { day: string; night: string }
  dedup_rule: Record<string, unknown> | null
  definitions: Record<string, string>
  notes: string[]
}

export interface SeasonYear {
  year: number
  role: 'current' | 'last' | 'reference'
  fires: (number | null)[]
  r7: (number | null)[]
  cum?: (number | null)[]
  total: number | null
  total_to_date: number | null
  days_with_data: number
  days_missing: number
  days_no_pass?: number
  suspect_days: number
  first_day_with_data: string | null
  complete?: boolean
  timing?: { p10: string | null; p50: string | null; p90: string | null; days_unobserved?: number; note?: string } | null
}

export interface HeadlineComparison {
  last_year: { year: number; fires: number; pct_change: number | null; days_with_data: number } | null
  reference: {
    years: number[]
    used_years: number[]
    rows: { year: number; fires: number | null; days_with_data: number; used: boolean }[]
    mean: number | null
    min: number | null
    max: number | null
    pct_change: number | null
    higher_than_n_of: [number, number] | null
    rank_text: string | null
  }
}

export interface SeasonsResponse {
  region: { kind: string; name: string; label: string }
  basis?: Basis
  basis_label?: string
  season: { id: SeasonId; key: string; label: string; year: number; start: string; end: string; end_effective: string; complete: boolean }
  days: string[]
  today_index: number | null
  years: SeasonYear[]
  headline: HeadlineComparison & {
    basis?: Basis
    window: { start: string; end: string; days: number; days_with_data: number; days_missing: number; compared_dates: string | null }
    fires: number
    fires_per_day: number | null
    frp_mw: number
    day: number
    night: number
    night_share: number | null
    /** Year-on-year figures on NOAA-20 alone; present when the store carries the series and basis is 'all'. */
    comparison_n20?: HeadlineComparison & { basis: Basis; basis_label: string; fires: number; days_with_data: number; note: string }
  }
  method: { r7: string; comparison: string; cum?: string; timing?: string; basis?: string }
  caveats: string[]
  store_built_at: string | null
  note?: string
}

export interface DistrictRow {
  district: string
  province: string | null
  fires: number
  fires_last: number
  pct_change: number | null
  frp_mw: number
  night_share: number | null
  days_active: number
  lat: number | null
  lon: number | null
}

export interface DistrictsResponse {
  season: { id: SeasonId; year: number; start: string; end: string; end_effective: string }
  window: { start: string; end: string; days: number; days_with_data: number; compared_dates: string | null }
  last_year: number
  region: { kind: string; name: string; label: string }
  basis?: Basis
  rows: DistrictRow[]
  districts_total: number
  totals: { fires: number; fires_last: number } | null
  note?: string
  caveats: string[]
}

export type SplitKey = 'pakistan' | 'indian_punjab' | 'haryana' | 'other'
/** pakistan_punjab is a subset of pakistan, carried so the two Punjabs can be read side by side. */
export type SplitSeriesKey = SplitKey | 'pakistan_punjab'

export interface SplitResponse {
  season: { id: SeasonId; year: number; start: string; end: string; end_effective: string }
  basis?: Basis
  days: string[]
  series: Record<SplitSeriesKey, (number | null)[]>
  totals: Record<SplitSeriesKey, number>
  shares: Record<SplitKey, number | null>
  labels: Record<SplitSeriesKey, string>
  days_missing: number
  note?: string
  caveats: string[]
}

export interface PersistentRow {
  lat: number
  lon: number
  days_active: number
  fires: number
  frp_mean_mw: number | null
  night_share: number | null
  district: string | null
  country: string | null
}

export interface PersistentResponse {
  area: { kind: string; name: string }
  region: { kind: string; name: string; label: string }
  window: { start_pkt_day: string; end_pkt_day: string; days: number }
  fires_in_area: number
  min_days: number
  window_days: number
  cells_total: number
  persistent_cells: number
  one_off_share: number | null
  rows: PersistentRow[]
  label: string
  message?: string
}

export interface City {
  id: number
  name: string
  province: string | null
  lat: number
  lon: number
  stations: number
}

export interface RingStats {
  fires: number
  detections: number
  frp_mw: number | null
  by_country: Record<string, number>
}

export interface UpwindFire {
  lat: number
  lon: number
  frp_mw: number | null
  km: number | null
  bearing_deg: number | null
  direction: string | null
  country: string
  province: string | null
  district: string | null
  confidence: string
  satellite: string
  acq_pkt: string | null
  transport_h_at_10m_wind: number | null
}

export interface ExposureResponse {
  status: 'ok' | 'no_file' | 'unavailable'
  message?: string
  city: string
  day: string
  lat?: number
  lon?: number
  radius_km?: number
  rings?: Record<string, RingStats>
  top_districts_in_radius?: { district: string; fires: number }[]
  wind?: { source: string; from_deg: number | null; from_compass: string | null; speed_ms: number | null; n_observations: number; note: string }
  upwind?: {
    cone_half_width_deg: number
    from_deg: number
    from_compass: string | null
    fires_200km: number
    frp_mw_200km: number | null
    frp_mw_cos_weighted: number | null
    fires_100km: number
    frp_mw_100km: number | null
    by_country: Record<string, number>
  } | null
  top_upwind_fires?: UpwindFire[]
  nearest_fire?: UpwindFire | null
  passes?: { status?: string; day_basis?: string; satellites?: string[]; observation_period?: { start: string; end: string } | null }
  caveats?: string[]
}

export interface LinkRow {
  day: string
  pm25: number | null
  n_stations: number | null
  fires_100: number | null
  frp_100: number | null
  frp_200: number | null
  frp_upwind: number | null
  wind_from: number | null
  wind_ms: number | null
  wind_obs: number
  flag: boolean
  pm25_prior3?: number
}

export interface Correlation {
  n: number
  pearson: number | null
  spearman: number | null
  strength: string
}

export interface Pm25LinkResponse {
  status: 'ok' | 'unavailable'
  message?: string
  city: string
  window?: { start_pkt_day: string; end_pkt_day: string; days: number }
  days?: number
  days_with_pm25?: number
  days_with_upwind?: number
  upwind_p75_mw?: number | null
  correlations?: Record<'frp_upwind' | 'frp_200', Record<'lag0' | 'lag1' | 'lag2', Correlation>>
  candidate_episodes?: string[]
  /** @deprecated older name of candidate_episodes */
  fire_influenced_days?: string[]
  rows?: LinkRow[]
  summary?: string
  caveats?: string[]
}

export const fetchFiresMeta = () => getJson<FiresMeta>('/meta')
export const fetchSeasons = (region: string, season: SeasonId, basis: Basis = 'all') =>
  getJson<SeasonsResponse>(`/seasons?region=${encodeURIComponent(region)}&season=${season}&basis=${basis}`)
export const fetchDistricts = (season: SeasonId, region: string, basis: Basis = 'all') =>
  getJson<DistrictsResponse>(`/districts?season=${season}&region=${encodeURIComponent(region)}&limit=60&basis=${basis}`)
export const fetchSplit = (season: SeasonId, basis: Basis = 'all') => getJson<SplitResponse>(`/split?season=${season}&basis=${basis}`)
export const fetchPersistent = (region: string) =>
  getJson<PersistentResponse>(`/persistent?region=${encodeURIComponent(region)}&min_days=10&limit=30`)
export const fetchCities = () => getJson<{ cities: City[]; count: number }>('/cities')
export const fetchExposure = (city: string, date: string) =>
  getJson<ExposureResponse>(`/exposure?city=${encodeURIComponent(city)}&date=${date}&radius_km=100`)
export const fetchPm25Link = (city: string, end: string) =>
  getJson<Pm25LinkResponse>(`/pm25-link?city=${encodeURIComponent(city)}&end=${end}&days=60`)

export type OutlookBand = 'none' | 'low' | 'elevated' | 'high' | 'very_high'

export interface OutlookWind { from_deg: number | null; from_compass: string | null; speed_ms: number | null; n_hours: number }

export interface OutlookLead {
  lead: string
  day: string
  status: 'ok' | 'no_forecast'
  wind_850: OutlookWind | null
  wind_10m: OutlookWind | null
  fires_200km: number
  band: OutlookBand | null
  upwind_load_mw: number | null
  cone_frp_mw?: number
  cone_frp_mw_10m?: number | null
  fires_in_cone?: number
  fires_reachable?: number
  reach_km?: number
  by_country?: Record<string, number>
  top_fires?: { lat: number; lon: number; frp_mw: number; km: number; direction: string | null; district: string | null; country: string; transport_h: number }[]
}

export interface OutlookAlert { city: string; province?: string | null; band: OutlookBand; upwind_load_mw: number; from_compass: string | null }

export interface CityOutlookResponse {
  status: 'ok' | 'stale' | 'unavailable'
  message?: string
  generated_at?: string
  model?: string
  fires_as_of?: { days: string[]; observation_period?: { start: string; end: string } | null; satellites?: string[] }
  city?: string
  leads?: OutlookLead[]
  others_at_alert_d1?: OutlookAlert[]
  caveats?: string[]
}

export const fetchCityOutlook = (city: string) => getJson<CityOutlookResponse>(`/outlook?city=${encodeURIComponent(city)}`)
