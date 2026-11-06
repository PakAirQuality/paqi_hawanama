/**
 * Which region a fire is in, with the fire report's labels (§1, §10.2): Pakistan, Indian Punjab,
 * Haryana, or other (the rest of the FIRMS box: Rajasthan, Jammu and Kashmir, Afghanistan, Iran).
 */

import { isInsidePakistan, loadPakBoundary } from '@/components/analyst-desk/pakistan'

export type FireRegion = 'Pakistan' | 'Indian Punjab' | 'Haryana' | 'other'

type Rings = number[][][]
let india: { name: 'Indian Punjab' | 'Haryana'; polys: Rings[] }[] | null = null
let loading: Promise<void> | null = null

/** Loads the Pakistan border and the Indian Punjab and Haryana outlines (once). */
export function loadFireRegions(): Promise<void> {
  loading ??= Promise.all([
    loadPakBoundary(),
    fetch('/india_pb_hr.geojson').then(r => r.json()).then((fc: GeoJSON.FeatureCollection) => {
      india = fc.features.flatMap(f => {
        const shape = String(f.properties?.shapeName ?? '')
        const name = shape.startsWith('Punjab') ? 'Indian Punjab' as const : shape.startsWith('Har') ? 'Haryana' as const : null
        const g = f.geometry
        if (!name || !g) return []
        const polys: Rings[] = g.type === 'Polygon' ? [g.coordinates] : g.type === 'MultiPolygon' ? g.coordinates : []
        return [{ name, polys }]
      })
    }).catch(() => { india = [] }),
  ]).then(() => undefined)
  return loading
}

function inRing(x: number, y: number, ring: number[][]): boolean {
  let inside = false
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j]
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside
  }
  return inside
}

/** Region of a point; call after loadFireRegions(). */
export function fireRegion(lng: number, lat: number): FireRegion {
  if (isInsidePakistan(lng, lat)) return 'Pakistan'
  for (const r of india ?? []) {
    if (r.polys.some(p => inRing(lng, lat, p[0]) && !p.slice(1).some(h => inRing(lng, lat, h)))) return r.name
  }
  return 'other'
}
