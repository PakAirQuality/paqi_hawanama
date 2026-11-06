/**
 * The latest surface wind field (u/v packed into an image's red and green channels), loaded once
 * for the wind particle layer and the smoke plumes.
 */

export interface WindMeta {
  width: number
  height: number
  lat_min: number
  lat_max: number
  lon_min: number
  lon_max: number
  u_min: number
  u_max: number
  v_min: number
  v_max: number
  generated_at: string
  attribution: string
}

export interface WindField {
  image: HTMLImageElement
  meta: WindMeta
  /** Wind (m/s, u eastward, v northward) at a point, bilinear; null outside the field */
  sample: (lon: number, lat: number) => { u: number; v: number } | null
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? ''
let cached: Promise<WindField | null> | null = null

export function loadWindField(): Promise<WindField | null> {
  if (cached) return cached
  cached = (async () => {
    try {
      const [texture, metadata] = await Promise.all([
        fetch(`${API_BASE}/api/v1/data-sources/wind/texture`),
        fetch(`${API_BASE}/api/v1/data-sources/wind/metadata`),
      ])
      if (!texture.ok || !metadata.ok) return null
      const [blob, meta] = await Promise.all([texture.blob(), metadata.json() as Promise<WindMeta>])
      const image = new Image()
      image.crossOrigin = 'anonymous'
      await new Promise<void>((resolve, reject) => {
        image.onload = () => resolve()
        image.onerror = () => reject(new Error('Failed to decode wind texture'))
        image.src = URL.createObjectURL(blob)
      })
      const canvas = document.createElement('canvas')
      canvas.width = meta.width; canvas.height = meta.height
      const ctx = canvas.getContext('2d', { willReadFrequently: true })
      if (!ctx) return null
      ctx.drawImage(image, 0, 0)
      const px = ctx.getImageData(0, 0, meta.width, meta.height).data
      const n = meta.width * meta.height
      const U = new Float32Array(n), V = new Float32Array(n)
      const uR = meta.u_max - meta.u_min, vR = meta.v_max - meta.v_min
      for (let i = 0; i < n; i++) {
        U[i] = (px[i * 4] / 255) * uR + meta.u_min
        V[i] = (px[i * 4 + 1] / 255) * vR + meta.v_min
      }
      const sample = (lon: number, lat: number) => {
        // Row 0 is the northern edge
        const fx = ((lon - meta.lon_min) / (meta.lon_max - meta.lon_min)) * (meta.width - 1)
        const fy = ((meta.lat_max - lat) / (meta.lat_max - meta.lat_min)) * (meta.height - 1)
        if (!(fx >= 0 && fy >= 0 && fx <= meta.width - 1 && fy <= meta.height - 1)) return null
        const x0 = Math.floor(fx), y0 = Math.floor(fy)
        const x1 = Math.min(x0 + 1, meta.width - 1), y1 = Math.min(y0 + 1, meta.height - 1)
        const tx = fx - x0, ty = fy - y0
        const at = (A: Float32Array) => {
          const a = A[y0 * meta.width + x0], b = A[y0 * meta.width + x1]
          const c = A[y1 * meta.width + x0], d = A[y1 * meta.width + x1]
          return (a * (1 - tx) + b * tx) * (1 - ty) + (c * (1 - tx) + d * tx) * ty
        }
        return { u: at(U), v: at(V) }
      }
      return { image, meta, sample }
    } catch (err) {
      console.warn('Wind field unavailable:', err)
      cached = null // allow a retry later
      return null
    }
  })()
  return cached
}

/**
 * Where air starting at a point drifts over the next hours on this (fixed) wind field, one point an hour.
 * A rough guide to where smoke goes, not a dispersion model.
 */
export function driftPath(field: WindField, lon: number, lat: number, hours = 12, stepH = 1): [number, number][] {
  const path: [number, number][] = [[lon, lat]]
  let x = lon, y = lat
  for (let t = 0; t < hours; t += stepH) {
    const w = field.sample(x, y)
    if (!w) break
    const sec = stepH * 3600
    x += (w.u * sec) / (111320 * Math.cos((y * Math.PI) / 180))
    y += (w.v * sec) / 110540
    path.push([x, y])
  }
  return path
}
