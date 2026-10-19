// Build-time lookups backed by src/static/*.json. Server components only: never import from a 'use client' file.
import cities from '@/static/cities.json'
import stations from '@/static/stations.json'

export interface StaticCity {
  slug: string
  name: string
  state: string | null
  country: string | null
  station_count: number
  lat: number | null
  lon: number | null
}

export interface StaticStation {
  id: string
  name: string
  city: string | null
  state: string | null
  country: string | null
  city_slug: string | null
  lat: number | null
  lon: number | null
}

export const allCities = cities as StaticCity[]
export const allStations = stations as StaticStation[]

const cityBySlug = new Map(allCities.map((c) => [c.slug, c]))
const stationById = new Map(allStations.map((s) => [s.id, s]))

export function findCity(slug: string): StaticCity | undefined {
  return cityBySlug.get(slug)
}

export function findStation(id: string): StaticStation | undefined {
  return stationById.get(id)
}

export function stationsInCity(cityName: string | null): StaticStation[] {
  if (!cityName) return []
  return allStations.filter((s) => s.city === cityName)
}
