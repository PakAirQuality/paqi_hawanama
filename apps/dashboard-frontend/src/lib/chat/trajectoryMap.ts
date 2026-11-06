// Geometry for the trajectory mini-map drawn inside a chat answer: a plain equirectangular
// projection fitted to the paths, and GeoJSON outlines turned into SVG path strings.

export interface LonLat { lon: number; lat: number }

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
