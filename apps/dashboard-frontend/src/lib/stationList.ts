// The Stations page's list: the station directory joined to the latest readings.

import type { CurrentStation } from '@/components/analyst-desk/types'

export interface StationListItem {
  station_id: string
  station_name: string
  display_name: string
}

export interface StationRow {
  id: string
  name: string
  city: string
  /** City and province, e.g. "Lahore, Punjab" */
  place: string
  displayName: string
  pm25: number | null
  lastReading: string | null
}

export type StationSort = 'worst' | 'city'

/** A city's stations, or every station together when `city` is null. */
export interface StationGroup {
  city: string | null
  rows: StationRow[]
}

/** "Name, City, Province, Pakistan". Names can hold commas, so the parts count from the end. */
function placeParts(displayName: string): string[] {
  const parts = displayName.split(', ')
  return parts.length >= 3 ? parts.slice(-3, -1) : []
}

export function stationRows(stations: StationListItem[], live: CurrentStation[]): StationRow[] {
  const readings = new Map(live.map(s => [s.id, s]))
  return stations.map(s => {
    const reading = readings.get(s.station_id)
    const place = placeParts(s.display_name)
    return {
      id: s.station_id,
      name: s.station_name,
      city: place[0] || 'Other',
      place: place.join(', '),
      displayName: s.display_name,
      pm25: reading?.pm25 ?? null,
      lastReading: reading?.last_reading || null,
    }
  })
}

export const isReporting = (row: StationRow) => row.pm25 != null

/** `city` is an exact city name, or empty for every city. */
export function filterStationRows(rows: StationRow[], search: string, reportingOnly: boolean, city = ''): StationRow[] {
  const q = search.toLowerCase().trim()
  return rows.filter(r =>
    (!reportingOnly || isReporting(r)) &&
    (!city || r.city === city) &&
    (!q || r.name.toLowerCase().includes(q) || r.displayName.toLowerCase().includes(q)))
}

/** Cities to choose from, A to Z, with how many stations each has. */
export function stationCities(rows: StationRow[], reportingOnly: boolean): { city: string; count: number }[] {
  const counts = new Map<string, number>()
  for (const r of rows) {
    if (!reportingOnly || isReporting(r)) counts.set(r.city, (counts.get(r.city) ?? 0) + 1)
  }
  return [...counts.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([city, count]) => ({ city, count }))
}

const worstFirst = (a: StationRow, b: StationRow) => (b.pm25 ?? -1) - (a.pm25 ?? -1) || a.name.localeCompare(b.name)

export function groupStationRows(rows: StationRow[], sort: StationSort): StationGroup[] {
  if (!rows.length) return []
  if (sort === 'worst') return [{ city: null, rows: [...rows].sort(worstFirst) }]
  const cities = new Map<string, StationRow[]>()
  for (const row of rows) cities.set(row.city, [...(cities.get(row.city) ?? []), row])
  return [...cities.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([city, list]) => ({ city, rows: list.sort(worstFirst) }))
}

/** The highest reading now, or null when nothing is reporting. */
export function worstStation(rows: StationRow[]): StationRow | null {
  return rows.filter(isReporting).sort(worstFirst)[0] ?? null
}
