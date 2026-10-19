/**
 * The one PM2.5 health classification for the dashboard.
 *
 * US EPA 2024 PM2.5 breakpoints (89 FR 16202). Keys, labels, thresholds and colours mirror
 * the API's `app/services/aqi/pm25.py` (served at /api/v1/meta/aqi-categories); a test
 * compares the two. Every marker, card, chart, summary and export must classify through
 * `classifyPm25()` / `bandKey()` and colour through `bandColor()`. No component may carry
 * its own thresholds.
 *
 * PM2.5 in µg/m³ stays the headline number; `pm25ToAqi()` gives the explicitly labelled
 * US AQI alternative. An hourly concentration gives an hourly sub-index, not the 24 h AQI.
 */

export type BandKey =
  | 'good'
  | 'moderate'
  | 'unhealthy_sensitive'
  | 'unhealthy'
  | 'very_unhealthy'
  | 'hazardous'
  | 'unknown'

export interface Band {
  key: BandKey
  label: string
  shortLabel: string
  /** inclusive upper bound in µg/m³ after truncation to 0.1; null = open ended */
  pm25Max: number | null
  aqiMin: number
  aqiMax: number
  color: string
  textColor: string
  /** Tailwind classes for pill badges */
  badge: string
}

export const AQI_BANDS: readonly Band[] = [
  { key: 'good', label: 'Good', shortLabel: 'Good', pm25Max: 9.0, aqiMin: 0, aqiMax: 50, color: '#6ecc39', textColor: '#1f2937', badge: 'bg-green-100 text-green-800' },
  { key: 'moderate', label: 'Moderate', shortLabel: 'Moderate', pm25Max: 35.4, aqiMin: 51, aqiMax: 100, color: '#f0c20c', textColor: '#1f2937', badge: 'bg-yellow-100 text-yellow-800' },
  { key: 'unhealthy_sensitive', label: 'Unhealthy for Sensitive Groups', shortLabel: 'USG', pm25Max: 55.4, aqiMin: 101, aqiMax: 150, color: '#f18017', textColor: '#ffffff', badge: 'bg-orange-100 text-orange-800' },
  { key: 'unhealthy', label: 'Unhealthy', shortLabel: 'Unhealthy', pm25Max: 125.4, aqiMin: 151, aqiMax: 200, color: '#ef7855', textColor: '#ffffff', badge: 'bg-red-100 text-red-800' },
  { key: 'very_unhealthy', label: 'Very Unhealthy', shortLabel: 'V. Unhealthy', pm25Max: 225.4, aqiMin: 201, aqiMax: 300, color: '#a070b5', textColor: '#ffffff', badge: 'bg-purple-100 text-purple-800' },
  { key: 'hazardous', label: 'Hazardous', shortLabel: 'Hazardous', pm25Max: null, aqiMin: 301, aqiMax: 500, color: '#991b1b', textColor: '#ffffff', badge: 'bg-red-200 text-red-900' },
] as const

export const UNKNOWN_BAND: Band = {
  key: 'unknown', label: 'No data', shortLabel: '—', pm25Max: null, aqiMin: 0, aqiMax: 0,
  color: '#6b7280', textColor: '#ffffff', badge: 'bg-slate-100 text-slate-600',
}

/** Ordered keys, worst last; use for distributions and legends. */
export const BAND_KEYS: readonly BandKey[] = AQI_BANDS.map((b) => b.key)

export const BAND_ORDER: Record<BandKey, number> = {
  unknown: 0, good: 1, moderate: 2, unhealthy_sensitive: 3, unhealthy: 4, very_unhealthy: 5, hazardous: 6,
}

/** Scale name to print next to any category: "US AQI (EPA 2024)". */
export const BAND_SCALE_LABEL = 'US AQI categories (EPA 2024 PM2.5 breakpoints)'

const BREAKPOINTS: ReadonlyArray<[number, number, number, number]> = [
  [0.0, 9.0, 0, 50],
  [9.1, 35.4, 51, 100],
  [35.5, 55.4, 101, 150],
  [55.5, 125.4, 151, 200],
  [125.5, 225.4, 201, 300],
  [225.5, 325.4, 301, 500],
]

function truncate1(c: number): number {
  return Math.floor(c * 10 + 1e-9) / 10
}

/** US AQI for a PM2.5 concentration (null when unusable). Above 325.4 the last segment is extrapolated. */
export function pm25ToAqi(pm25: number | null | undefined): number | null {
  if (pm25 == null || !Number.isFinite(pm25) || pm25 < 0) return null
  const c = truncate1(pm25)
  for (const [lo, hi, ilo, ihi] of BREAKPOINTS) {
    if (c >= lo && c <= hi) return Math.round(((ihi - ilo) / (hi - lo)) * (c - lo) + ilo)
  }
  const [lo, hi, ilo, ihi] = BREAKPOINTS[BREAKPOINTS.length - 1]
  return Math.round(((ihi - ilo) / (hi - lo)) * (c - lo) + ilo)
}

/** Band for a US AQI value. */
export function bandForAqi(aqi: number | null | undefined): Band {
  if (aqi == null || !Number.isFinite(aqi) || aqi < 0) return UNKNOWN_BAND
  for (const b of AQI_BANDS) if (aqi <= b.aqiMax) return b
  return AQI_BANDS[AQI_BANDS.length - 1]
}

/** Band for a PM2.5 concentration in µg/m³. */
export function classifyPm25(pm25: number | null | undefined): Band {
  return bandForAqi(pm25ToAqi(pm25))
}

export function bandKey(pm25: number | null | undefined): BandKey {
  return classifyPm25(pm25).key
}

const LEGACY: Record<string, BandKey> = {
  severe: 'hazardous',
  usg: 'unhealthy_sensitive',
  unhealthy_for_sensitive_groups: 'unhealthy_sensitive',
}

/** Accept any band key the API or stored files may still send and map it onto the canonical set. */
export function normalizeBand(key: string | null | undefined): BandKey {
  if (!key) return 'unknown'
  const k = String(key).trim().toLowerCase()
  const mapped = (LEGACY[k] ?? k) as BandKey
  return mapped in BAND_ORDER ? mapped : 'unknown'
}

export function bandByKey(key: string | null | undefined): Band {
  const k = normalizeBand(key)
  return AQI_BANDS.find((b) => b.key === k) ?? UNKNOWN_BAND
}

export function bandColor(key: string | null | undefined): string {
  return bandByKey(key).color
}

export function bandLabel(key: string | null | undefined, short = false): string {
  const b = bandByKey(key)
  return short ? b.shortLabel : b.label
}

/** Colour for a PM2.5 value (markers, bars, heatmap cells). */
export function pm25Color(pm25: number | null | undefined): string {
  return classifyPm25(pm25).color
}

/** CSS marker class used by the Mapbox HTML markers (see globals.css .aqi-marker.bg-*). */
export function markerClass(pm25: number | null | undefined): string {
  switch (classifyPm25(pm25).key) {
    case 'good': return 'bg-good'
    case 'moderate': return 'bg-moderate'
    case 'unhealthy_sensitive': return 'bg-unhealthy-sensitive'
    case 'unhealthy': return 'bg-unhealthy'
    case 'very_unhealthy': return 'bg-very-unhealthy'
    case 'hazardous': return 'bg-hazardous'
    default: return 'bg-no-reading'
  }
}

/** Count stations per band from a list of PM2.5 values. */
export function bandCounts(values: Array<number | null | undefined>): Record<BandKey, number> {
  const counts = { unknown: 0, good: 0, moderate: 0, unhealthy_sensitive: 0, unhealthy: 0, very_unhealthy: 0, hazardous: 0 }
  for (const v of values) counts[bandKey(v)] += 1
  return counts
}

/** "Unhealthy or worse" (AQI > 150): the count most summaries quote. */
export function unhealthyOrWorse(counts: Record<BandKey, number>): number {
  return counts.unhealthy + counts.very_unhealthy + counts.hazardous
}
