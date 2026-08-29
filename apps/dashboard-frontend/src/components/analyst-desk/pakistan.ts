/**
 * Pakistan boundary point-in-polygon test.
 * Loads the country GeoJSON once and provides isInsidePakistan().
 */

type Ring = [number, number][]
let pakMultiPoly: Ring[][][] | null = null
let loadPromise: Promise<void> | null = null

export async function loadPakBoundary(): Promise<void> {
  if (pakMultiPoly) return
  if (loadPromise) return loadPromise
  loadPromise = (async () => {
    try {
      const res = await fetch('/pakistan_country.geojson')
      const data = await res.json()
      const geom = data.features[0].geometry
      pakMultiPoly = geom.type === 'MultiPolygon'
        ? geom.coordinates
        : [geom.coordinates]
    } catch {
      pakMultiPoly = []
    }
  })()
  return loadPromise
}

function pointInRing(lng: number, lat: number, ring: Ring): boolean {
  let inside = false
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i]
    const [xj, yj] = ring[j]
    if ((yi > lat) !== (yj > lat) && lng < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) {
      inside = !inside
    }
  }
  return inside
}

export function isInsidePakistan(lng: number, lat: number): boolean {
  if (!pakMultiPoly) return false
  for (const polygon of pakMultiPoly) {
    if (pointInRing(lng, lat, polygon[0])) {
      let inHole = false
      for (let h = 1; h < polygon.length; h++) {
        if (pointInRing(lng, lat, polygon[h])) { inHole = true; break }
      }
      if (!inHole) return true
    }
  }
  return false
}

export function isPakBoundaryLoaded(): boolean {
  return pakMultiPoly != null && pakMultiPoly.length > 0
}
