// Geometry and wording shared by the two trajectory renderers inside a chat answer (the Mapbox
// map and the SVG fallback): the level styles, the member paths and bounds of a document, the
// ensemble sentence, and for the SVG a plain equirectangular projection and outline paths.

import type { TrajectoryDoc } from '@/components/fires/api'

export interface LonLat { lon: number; lat: number }

export interface LevelStyle { key: string; label: string; colour: string }

export const LEVELS: LevelStyle[] = [
  { key: '1000', label: '~100 m', colour: '#1d4ed8' },
  { key: '925', label: '~700 m', colour: '#0f766e' },
  { key: '850', label: '~1,400 m', colour: '#b45309' },
]
export const LEVEL_KEYS = LEVELS.map(l => l.key)
export const FIRE_COLOUR = '#ea580c'
export const MARK_HOURS = [24, 48, 72]
export const REGIONS = ['Pakistan Punjab', 'other Pakistan', 'Indian Punjab', 'Haryana', 'elsewhere']

export const levelStyle = (key: string): LevelStyle => LEVELS.find(l => l.key === key) ?? { key, label: `${key} hPa`, colour: '#475569' }

/** The ensemble members of each level as lon/lat polylines (empty when the document has none). */
export function memberPaths(doc: TrajectoryDoc): Record<string, LonLat[][]> {
  const out: Record<string, LonLat[][]> = {}
  for (const [lv, members] of Object.entries(doc.ensemble?.members ?? {})) {
    out[lv] = members.filter(m => m.length > 1).map(m => m.map(([lat, lon]) => ({ lon, lat })))
  }
  return out
}

/** Level keys of a per-level record in drawing order (lowest level first); JavaScript would list numeric keys ascending. */
export function levelOrder(rec: Record<string, unknown>): string[] {
  return [...LEVEL_KEYS.filter(k => k in rec), ...Object.keys(rec).filter(k => !LEVEL_KEYS.includes(k))]
}

/** Origin and the central paths: what the small preview is fitted to (members may run off its edge). */
export function centralPoints(doc: TrajectoryDoc): LonLat[] {
  const all: LonLat[] = [{ lon: doc.origin.lon, lat: doc.origin.lat }]
  for (const path of Object.values(doc.paths)) for (const p of path) all.push({ lon: p.lon, lat: p.lat })
  return all
}

/** Origin, central paths and members: everything the expanded view must contain. */
export function allPoints(doc: TrajectoryDoc): LonLat[] {
  const all: LonLat[] = [{ lon: doc.origin.lon, lat: doc.origin.lat }]
  for (const path of Object.values(doc.paths)) for (const p of path) all.push({ lon: p.lon, lat: p.lat })
  for (const members of Object.values(memberPaths(doc))) for (const m of members) for (const p of m) all.push(p)
  return all
}

/** [[west, south], [east, north]] of the points, never thinner than MIN_SPAN_DEG. */
export function boundsOf(points: LonLat[]): [[number, number], [number, number]] {
  let w = Infinity, s = Infinity, e = -Infinity, n = -Infinity
  for (const p of points) { w = Math.min(w, p.lon); e = Math.max(e, p.lon); s = Math.min(s, p.lat); n = Math.max(n, p.lat) }
  if (!Number.isFinite(w)) return [[60, 20], [80, 38]]
  if (e - w < MIN_SPAN_DEG) { const c = (e + w) / 2; w = c - MIN_SPAN_DEG / 2; e = c + MIN_SPAN_DEG / 2 }
  if (n - s < MIN_SPAN_DEG) { const c = (n + s) / 2; s = c - MIN_SPAN_DEG / 2; n = c + MIN_SPAN_DEG / 2 }
  return [[w, s], [e, n]]
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`

/** "At 24 h, 21 of 27 members (~700 m) were over Pakistan Punjab, 6 over Indian Punjab · spread 60 km." */
export function ensembleLine(doc: TrajectoryDoc, level = '925', age = '24'): string {
  const ens = doc.ensemble
  if (!ens) return ''
  const lv = ens.regions_at?.[age]?.[level] ? level : Object.keys(ens.regions_at?.[age] ?? {})[0]
  if (!lv) return ''
  const regions = ens.regions_at[age][lv]
  const entries = Object.entries(regions).sort((a, b) => b[1] - a[1])
  if (!entries.length) return ''
  const n = ens.n_members?.[lv] ?? entries.reduce((a, [, k]) => a + k, 0)
  const [first, ...rest] = entries
  const verb = doc.direction === 'backward' ? 'were' : 'will be'
  const parts = [`${first[1]} of ${plural(n, 'member')} (${levelStyle(lv).label}) ${verb} over ${first[0]}`, ...rest.map(([r, k]) => `${k} over ${r}`)]
  const spread = ens.spread_km?.[age]?.[lv]
  return `At ${age} h, ${parts.join(', ')}${spread != null ? ` · spread ${spread} km` : ''}.`
}

export interface Projection {
  width: number
  height: number
  /** degrees of latitude per SVG unit */
  scale: number
  centre: LonLat
  cosLat: number
  project: (p: LonLat) => { x: number; y: number }
  /** SVG units for a distance in kilometres (east–west) */
  kmToUnits: (km: number) => number
}

const KM_PER_DEG = 111.195
const MIN_SPAN_DEG = 1.5

/** Fit the view to the given points with padding (SVG units); keeps the aspect ratio true at the centre latitude. */
export function fitProjection(points: LonLat[], width: number, height: number, padding = 18): Projection {
  const lats = points.map(p => p.lat)
  const lons = points.map(p => p.lon)
  const latMin = Math.min(...lats), latMax = Math.max(...lats)
  const lonMin = Math.min(...lons), lonMax = Math.max(...lons)
  const centre = { lat: (latMin + latMax) / 2, lon: (lonMin + lonMax) / 2 }
  const cosLat = Math.max(0.2, Math.cos((centre.lat * Math.PI) / 180))
  const spanLat = Math.max(MIN_SPAN_DEG, latMax - latMin)
  const spanLon = Math.max(MIN_SPAN_DEG, (lonMax - lonMin) * cosLat)
  const innerW = Math.max(1, width - 2 * padding)
  const innerH = Math.max(1, height - 2 * padding)
  const scale = Math.max(spanLat / innerH, spanLon / innerW) // degrees per unit
  const project = (p: LonLat) => ({
    x: width / 2 + ((p.lon - centre.lon) * cosLat) / scale,
    y: height / 2 - (p.lat - centre.lat) / scale,
  })
  return { width, height, scale, centre, cosLat, project, kmToUnits: km => km / KM_PER_DEG / scale }
}

export function toPath(points: LonLat[], proj: Projection): string {
  return points
    .map((p, i) => {
      const { x, y } = proj.project(p)
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)} ${y.toFixed(1)}`
    })
    .join(' ')
}

type Ring = number[][]
interface GeoFeature { type: 'Feature'; geometry: { type: string; coordinates: unknown } }
export interface GeoCollection { type: 'FeatureCollection'; features: GeoFeature[] }

/** Every polygon ring of a FeatureCollection as one SVG path string (rings closed with Z). */
export function outlinePath(fc: GeoCollection | undefined, proj: Projection): string {
  if (!fc) return ''
  const parts: string[] = []
  const ring = (r: Ring) => {
    if (r.length < 3) return
    parts.push(
      r.map(([lon, lat], i) => {
        const { x, y } = proj.project({ lon, lat })
        return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)} ${y.toFixed(1)}`
      }).join(' ') + 'Z',
    )
  }
  for (const f of fc.features) {
    const g = f.geometry
    if (g.type === 'Polygon') (g.coordinates as Ring[]).forEach(ring)
    else if (g.type === 'MultiPolygon') (g.coordinates as Ring[][]).forEach(poly => poly.forEach(ring))
  }
  return parts.join(' ')
}

/** A round scale-bar length (km) that fits in about a third of the width. */
export function scaleBarKm(proj: Projection): number {
  const target = (proj.width / 3) * proj.scale * KM_PER_DEG
  const steps = [10, 20, 50, 100, 200, 500, 1000]
  let best = steps[0]
  for (const s of steps) if (s <= target) best = s
  return best
}
