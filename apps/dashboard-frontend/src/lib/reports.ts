/**
 * Reports page client: bounded, explicit requests against /api/v1/reports/* and a CSV
 * builder that reproduces exactly what the table and chart show.
 */

import { pktLocalToIso } from '@/lib/time'

export const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'https://hawanama-152782825429.asia-south1.run.app'

export const LIMITS = { maxStations: 25, maxDays: 31 }

export const POLLUTANTS: Array<{ key: string; label: string; unit: string }> = [
  { key: 'pm25', label: 'PM2.5', unit: 'µg/m³' },
  { key: 'pm10', label: 'PM10', unit: 'µg/m³' },
  { key: 'no2', label: 'NO₂', unit: 'µg/m³' },
  { key: 'so2', label: 'SO₂', unit: 'µg/m³' },
  { key: 'co', label: 'CO', unit: 'µg/m³' },
  { key: 'o3', label: 'O₃', unit: 'µg/m³' },
]

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: 'no-store' })
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (typeof body?.detail === 'string') detail = body.detail
    } catch { /* keep status text */ }
    throw new Error(detail)
  }
  return res.json() as Promise<T>
}

export interface ProvinceOption { label: string; province: string; country: string }

/** /meta/provinces returns "Province, Country" strings; split them so filters are explicit. */
export async function getProvinces(): Promise<ProvinceOption[]> {
  const list = await getJson<string[]>('/api/v1/meta/provinces')
  return list.map((label) => {
    const idx = label.lastIndexOf(', ')
    return idx > 0
      ? { label, province: label.slice(0, idx), country: label.slice(idx + 2) }
      : { label, province: label, country: 'Pakistan' }
  })
}

export interface CityOption { city: string; province: string; country: string; station_count: number; aliases?: string[] }

export async function getCities(province: string, country: string): Promise<CityOption[]> {
  const q = new URLSearchParams({ province, country })
  const data = await getJson<{ cities: CityOption[] }>(`/api/v1/reports/cities?${q}`)
  return data.cities
}

export interface StationOption {
  station_id: string
  station_name: string
  provider: string
  last_observation: string | null
  last_pm25: number | null
  duplicate_name: boolean
}

export async function getStations(city: string, province: string, country: string): Promise<StationOption[]> {
  const q = new URLSearchParams({ province, country })
  const data = await getJson<{ stations: StationOption[] }>(`/api/v1/reports/cities/${encodeURIComponent(city)}/stations?${q}`)
  return data.stations
}

export interface StationRow {
  station_id: string
  station_name: string
  timestamp_utc: string
  timestamp_pk: string
  qc_state: string
  [pollutant: string]: string | number | null
}

export interface StationReport {
  kind: 'stations'
  meta: {
    start_utc: string; end_utc: string; start_pk: string; end_pk: string; tz: string
    aggregation: string; parameters: string[]; units: Record<string, string>
    stations: Array<{ station_id: string; name: string; provider: string }>
    expected_hours_per_station: number; row_count: number; truncated: boolean
    limits: { max_stations: number; max_days: number }; qc_note: string
  }
  rows: StationRow[]
}

export interface CityRow { timestamp_utc: string; timestamp_pk: string; pm25: number; stations_used: number }

export interface CityReport {
  kind: 'city'
  meta: { city: string; province: string | null; country: string | null; start_utc: string; end_utc: string; tz: string; aggregation: string; stations_in_scope: number; units: Record<string, string> }
  rows: CityRow[]
}

export type Report = StationReport | CityReport

export interface ReportRequest {
  province: string
  country: string
  city: string
  mode: 'stations' | 'city'
  stationIds: string[]
  parameters: string[]
  /** YYYY-MM-DD and HH:MM in Pakistan time */
  startDate: string; startTime: string
  endDate: string; endTime: string
}

/** Client-side validation that mirrors the API's limits, with user-facing messages. */
export function validateRequest(r: ReportRequest): string | null {
  if (!r.province || !r.city) return 'Choose a province and a city.'
  if (r.mode === 'stations' && r.stationIds.length === 0) return 'Choose at least one station, or switch to City summary.'
  if (r.mode === 'stations' && r.stationIds.length > LIMITS.maxStations) return `At most ${LIMITS.maxStations} stations per report.`
  if (r.parameters.length === 0) return 'Choose at least one parameter.'
  if (!r.startDate || !r.endDate) return 'Choose a start and an end.'
  const s = new Date(pktLocalToIso(r.startDate, r.startTime || '00:00')).getTime()
  const e = new Date(pktLocalToIso(r.endDate, r.endTime || '00:00')).getTime()
  if (!(e > s)) return 'The end must be after the start.'
  if (e - s > LIMITS.maxDays * 86_400_000) return `The window can be at most ${LIMITS.maxDays} days.`
  if (e > Date.now() + 3_600_000) return 'The end cannot be in the future.'
  return null
}

export async function runReport(r: ReportRequest): Promise<Report> {
  const start = pktLocalToIso(r.startDate, r.startTime || '00:00')
  const end = pktLocalToIso(r.endDate, r.endTime || '00:00')
  if (r.mode === 'city') {
    const q = new URLSearchParams({ start, end, province: r.province, country: r.country })
    const data = await getJson<Omit<CityReport, 'kind'>>(`/api/v1/reports/cities/${encodeURIComponent(r.city)}/average/history?${q}`)
    return { kind: 'city', ...data }
  }
  const q = new URLSearchParams({ station_ids: r.stationIds.join(','), start, end, parameters: r.parameters.join(',') })
  const data = await getJson<Omit<StationReport, 'kind'>>(`/api/v1/reports/stations/history?${q}`)
  return { kind: 'stations', ...data }
}

// ── Statistics and CSV ──────────────────────────────────────────────────

export interface SeriesStats { mean: number | null; median: number | null; min: number | null; max: number | null; n: number; completeness: number }

export function seriesStats(values: Array<number | null | undefined>, expected: number): SeriesStats {
  const v = values.filter((x): x is number => typeof x === 'number' && Number.isFinite(x)).sort((a, b) => a - b)
  if (!v.length) return { mean: null, median: null, min: null, max: null, n: 0, completeness: 0 }
  const mean = v.reduce((a, b) => a + b, 0) / v.length
  const median = v.length % 2 ? v[(v.length - 1) / 2] : (v[v.length / 2 - 1] + v[v.length / 2]) / 2
  return { mean, median, min: v[0], max: v[v.length - 1], n: v.length, completeness: expected > 0 ? Math.min(1, v.length / expected) : 0 }
}

function csvCell(v: unknown): string {
  if (v === null || v === undefined) return ''
  const s = String(v)
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

/** CSV with a commented header that records exactly what was requested. */
export function reportToCsv(report: Report): string {
  const lines: string[] = []
  const m = report.meta as Record<string, unknown>
  lines.push(`# Hawanama report · generated ${new Date().toISOString()}`)
  lines.push(`# interval ${m.start_utc} to ${m.end_utc} (UTC) = ${(m as any).start_pk ?? ''} to ${(m as any).end_pk ?? ''} (Asia/Karachi)`)
  lines.push(`# aggregation: ${m.aggregation}`)
  if (report.kind === 'stations') {
    lines.push(`# stations: ${report.meta.stations.map((s) => `${s.name} [${s.station_id}, ${s.provider || 'unknown provider'}]`).join('; ')}`)
    lines.push(`# units: ${report.meta.parameters.map((p) => `${p}=${report.meta.units[p]}`).join(', ')}`)
    lines.push(`# qc: ${report.meta.qc_note}`)
    if (report.meta.truncated) lines.push('# WARNING: result truncated by the server row limit')
    const cols = ['station_id', 'station_name', 'timestamp_pk', 'timestamp_utc', ...report.meta.parameters, 'qc_state']
    lines.push(cols.join(','))
    for (const r of report.rows) lines.push(cols.map((c) => csvCell(r[c])).join(','))
  } else {
    lines.push(`# city: ${report.meta.city} (${report.meta.province ?? ''}, ${report.meta.country ?? ''}); stations in scope: ${report.meta.stations_in_scope}`)
    lines.push('# units: pm25=µg/m³')
    const cols = ['timestamp_pk', 'timestamp_utc', 'pm25', 'stations_used']
    lines.push(cols.join(','))
    for (const r of report.rows) lines.push(cols.map((c) => csvCell((r as unknown as Record<string, unknown>)[c])).join(','))
  }
  return lines.join('\n') + '\n'
}

export function downloadCsv(filename: string, csv: string): void {
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
