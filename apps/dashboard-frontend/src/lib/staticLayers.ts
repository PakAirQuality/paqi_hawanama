/**
 * Static evidence layers (brick-kiln inventory, emission-source inventory) loaded once per
 * page lifetime and shared by the map and the side panels. Both files are large (the kiln
 * file is ~2.8 MB raw); the previous code fetched and parsed each twice on every load.
 */

export const INVENTORY_NOTE = 'Mapped location from the inventory; not a measure of current activity or of its contribution to PM2.5.'

let kilnsPromise: Promise<GeoJSON.FeatureCollection> | null = null
let sourcesPromise: Promise<Record<string, GeoJSON.FeatureCollection>> | null = null

export function loadKilnsGeoJSON(): Promise<GeoJSON.FeatureCollection> {
  if (!kilnsPromise) {
    kilnsPromise = fetch('/brick_kilns.geojson').then((r) => {
      if (!r.ok) throw new Error(`kilns ${r.status}`)
      return r.json()
    }).catch((e) => { kilnsPromise = null; throw e })
  }
  return kilnsPromise
}

export function loadEmissionSources(): Promise<Record<string, GeoJSON.FeatureCollection>> {
  if (!sourcesPromise) {
    sourcesPromise = fetch('/emission_sources.json').then((r) => {
      if (!r.ok) throw new Error(`emission sources ${r.status}`)
      return r.json()
    }).catch((e) => { sourcesPromise = null; throw e })
  }
  return sourcesPromise
}

export const INDUSTRY_CATEGORIES = [
  { key: 'power_plants', color: '#ef4444', label: 'Power Plants' },
  { key: 'cement_plants', color: '#8b5cf6', label: 'Cement Plants' },
  { key: 'steel_sites', color: '#6366f1', label: 'Steel Sites' },
  { key: 'sugar_mills', color: '#10b981', label: 'Sugar Mills' },
  { key: 'industrial_sites', color: '#64748b', label: 'Industrial Sites' },
] as const
