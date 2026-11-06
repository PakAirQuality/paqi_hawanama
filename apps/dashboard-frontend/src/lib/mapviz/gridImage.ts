/**
 * Paints a PM2.5 grid into an image Mapbox can stretch over its corner coordinates.
 *
 * Mapbox stretches an image source linearly in Web Mercator, so output rows are evenly spaced in
 * Mercator y and each pixel samples the (latitude-regular) grid bilinearly at its own latitude.
 * Missing cells are skipped and the neighbours renormalised, so coastlines and borders fade softly.
 */

import { paletteLut } from './colormap'

export interface GridRaster {
  /** Row-major values, southern row first */
  values: ArrayLike<number | null>
  rows: number
  cols: number
  west: number
  south: number
  east: number
  north: number
  /** true: values sit on the bounds' lines (first and last row/column on the edges); false: cell centres */
  points: boolean
}

export interface GridImage {
  url: string
  coordinates: [[number, number], [number, number], [number, number], [number, number]]
}

const D2R = Math.PI / 180
export const mercY = (lat: number) => Math.log(Math.tan(Math.PI / 4 + (lat * D2R) / 2))
const invMercY = (y: number) => (2 * Math.atan(Math.exp(y)) - Math.PI / 2) / D2R

/** Draws the grid; `clip` (lon/lat polygons) trims it to an outline such as the country border. */
export function renderGridImage(g: GridRaster, range: { min: number; max: number }, opts: { scale?: number; maxWidth?: number; clip?: number[][][][]; nearest?: boolean } = {}): GridImage | null {
  if (typeof document === 'undefined' || g.rows < 2 || g.cols < 2) return null
  const lut = paletteLut()
  const W = Math.min(opts.maxWidth ?? 1400, Math.round(g.cols * (opts.scale ?? 5)))
  const yN = mercY(g.north), yS = mercY(g.south)
  const H = Math.max(2, Math.round((W * (yN - yS)) / ((g.east - g.west) * D2R)))

  const img = new ImageData(W, H)
  const px = img.data
  const span = range.max - range.min
  const v = g.values
  for (let y = 0; y < H; y++) {
    const lat = invMercY(yN - ((y + 0.5) / H) * (yN - yS))
    const fr = g.points ? ((lat - g.south) / (g.north - g.south)) * (g.rows - 1) : ((lat - g.south) / (g.north - g.south)) * g.rows - 0.5
    const r0 = Math.floor(fr), ty = fr - r0
    for (let x = 0; x < W; x++) {
      const lon = g.west + ((x + 0.5) / W) * (g.east - g.west)
      const fc = g.points ? ((lon - g.west) / (g.east - g.west)) * (g.cols - 1) : ((lon - g.west) / (g.east - g.west)) * g.cols - 0.5
      const c0 = Math.floor(fc), tx = fc - c0
      let wSum = 0, vSum = 0
      if (opts.nearest) {
        // Square cells: every pixel takes its own cell's value, no blending
        const r = Math.round(fr), c = Math.round(fc)
        const val = r >= 0 && r < g.rows && c >= 0 && c < g.cols ? v[r * g.cols + c] : null
        if (val != null && !Number.isNaN(val)) { wSum = 1; vSum = val }
      } else for (let dr = 0; dr < 2; dr++) {
        const r = r0 + dr
        if (r < 0 || r >= g.rows) continue
        const wy = dr ? ty : 1 - ty
        for (let dc = 0; dc < 2; dc++) {
          const c = c0 + dc
          if (c < 0 || c >= g.cols) continue
          const val = v[r * g.cols + c]
          if (val == null || Number.isNaN(val)) continue
          const w = wy * (dc ? tx : 1 - tx)
          wSum += w
          vSum += w * val
        }
      }
      if (wSum < 0.15) continue
      const t = Math.max(0, Math.min(1, (vSum / wSum - range.min) / span))
      const k = Math.round(t * 255) * 3
      const o = (y * W + x) * 4
      px[o] = lut[k]; px[o + 1] = lut[k + 1]; px[o + 2] = lut[k + 2]
      px[o + 3] = Math.round(255 * Math.min(1, wSum / 0.6))
    }
  }

  const canvas = document.createElement('canvas')
  canvas.width = W; canvas.height = H
  const ctx = canvas.getContext('2d')
  if (!ctx) return null
  if (opts.clip?.length) {
    const tmp = document.createElement('canvas')
    tmp.width = W; tmp.height = H
    tmp.getContext('2d')!.putImageData(img, 0, 0)
    const X = (lon: number) => ((lon - g.west) / (g.east - g.west)) * W
    const Y = (lat: number) => ((yN - mercY(lat)) / (yN - yS)) * H
    ctx.beginPath()
    for (const poly of opts.clip) for (const ring of poly) {
      ring.forEach(([lon, lat], i) => (i ? ctx.lineTo(X(lon), Y(lat)) : ctx.moveTo(X(lon), Y(lat))))
      ctx.closePath()
    }
    ctx.clip('evenodd')
    ctx.drawImage(tmp, 0, 0)
  } else {
    ctx.putImageData(img, 0, 0)
  }
  return {
    url: canvas.toDataURL('image/png'),
    coordinates: [[g.west, g.north], [g.east, g.north], [g.east, g.south], [g.west, g.south]],
  }
}

/**
 * The prediction endpoint's national grid as a GridRaster (row-major, southern row and western column first).
 * The files are not all written the same way round: older days run north to south, newer ones south to north,
 * so the order is read from each file's own per-cell latitudes and longitudes, and flipped when needed.
 */
export function predictionRaster(d: { grid?: { shape?: number[]; bounds?: { west: number; east: number; south: number; north: number } }; pm25?: (number | null)[]; lats?: number[]; lons?: number[] } | null | undefined): GridRaster | null {
  const shape = d?.grid?.shape, b = d?.grid?.bounds
  if (!d?.pm25?.length || !shape || shape.length < 2 || !b) return null
  const [rows, cols] = shape
  if (rows * cols !== d.pm25.length) return null
  const lats = d.lats, lons = d.lons
  const perCell = lats?.length === d.pm25.length && lons?.length === d.pm25.length
  const northFirst = perCell && rows > 1 ? lats![0] > lats![cols] : false
  const eastFirst = perCell && cols > 1 ? lons![0] > lons![1] : false
  let values: ArrayLike<number | null> = d.pm25
  if (northFirst || eastFirst) {
    const out = new Array<number | null>(d.pm25.length)
    for (let r = 0; r < rows; r++) {
      const sr = northFirst ? rows - 1 - r : r
      for (let c = 0; c < cols; c++) out[r * cols + c] = d.pm25[sr * cols + (eastFirst ? cols - 1 - c : c)]
    }
    values = out
  }
  return { values, rows, cols, west: b.west, south: b.south, east: b.east, north: b.north, points: true }
}

/** Painted estimate images by date and model, shared by the map and the replay, so a day is painted once. */
const imageCache = new Map<string, GridImage>()
const IMAGE_CACHE_MAX = 40

/** Cache key for a prediction response: its date and model (null without a date). */
export function estimateKey(d: { date?: string; model?: string } | null | undefined): string | null {
  return d?.date ? `${d.date}:${d.model ?? 'backbone'}` : null
}

/** The cached image for `key`, painting it with `make` the first time. */
export function cachedGridImage(key: string | null, make: () => GridImage | null): GridImage | null {
  if (!key) return make()
  const hit = imageCache.get(key)
  if (hit) { imageCache.delete(key); imageCache.set(key, hit); return hit }
  const img = make()
  if (img) {
    imageCache.set(key, img)
    if (imageCache.size > IMAGE_CACHE_MAX) imageCache.delete(imageCache.keys().next().value as string)
  }
  return img
}

/** The grid's value at a point (bilinear over the cells that have one); null outside the grid or where it is empty. */
export function sampleRaster(g: GridRaster, lon: number, lat: number): number | null {
  const fc = g.points ? ((lon - g.west) / (g.east - g.west)) * (g.cols - 1) : ((lon - g.west) / (g.east - g.west)) * g.cols - 0.5
  const fr = g.points ? ((lat - g.south) / (g.north - g.south)) * (g.rows - 1) : ((lat - g.south) / (g.north - g.south)) * g.rows - 0.5
  if (!(fc >= 0 && fr >= 0 && fc <= g.cols - 1 && fr <= g.rows - 1)) return null
  const c0 = Math.floor(fc), r0 = Math.floor(fr), tx = fc - c0, ty = fr - r0
  let w = 0, v = 0
  for (let dr = 0; dr < 2; dr++) for (let dc = 0; dc < 2; dc++) {
    const r = Math.min(g.rows - 1, r0 + dr), c = Math.min(g.cols - 1, c0 + dc)
    const val = g.values[r * g.cols + c]
    if (val == null || Number.isNaN(val)) continue
    const k = (dr ? ty : 1 - ty) * (dc ? tx : 1 - tx)
    w += k; v += k * val
  }
  return w > 0.05 ? v / w : null
}
