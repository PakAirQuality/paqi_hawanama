// The turbo colour ramp the API paints the PM2.5 surface with (TURBO_CMAP in apps/api/app/routers/_tile_utils.py),
// so the map's legend matches the tiles exactly.

/** Value range of the national surface: PM25_VMIN and PM25_VMAX in apps/api/app/routers/ops_pipeline.py */
export const SURFACE_RANGE = { min: 20, max: 180 } as const
/** Value range of the 1 km city layers: URBAN_VMIN and URBAN_VMAX in apps/api/app/routers/ops_downscaler.py */
export const CITY_RANGE = { min: 5, max: 80 } as const

const clamp = (v: number) => Math.max(0, Math.min(255, Math.round(v)))

/** Turbo colour at t (0 to 1), as [r, g, b]. */
export function turboRgb(t: number): [number, number, number] {
  t = Math.max(0, Math.min(1, t))
  const r = 34.61 + t * (1172.33 - t * (10793.56 - t * (33300.12 - t * (38394.49 - t * 14825.05))))
  const g = 23.31 + t * (557.33 + t * (1225.33 - t * (3574.96 - t * (1073.77 + t * 707.56))))
  const b = 27.2 + t * (3211.1 - t * (15327.97 - t * (27814 - t * (22569.18 - t * 6838.66))))
  return [clamp(r), clamp(g), clamp(b)]
}

/** A CSS gradient through the ramp, left (lowest) to right (highest). */
export function turboGradient(stops = 16): string {
  const parts = Array.from({ length: stops }, (_, i) => {
    const t = i / (stops - 1)
    return `rgb(${turboRgb(t).join(' ')}) ${Math.round(t * 100)}%`
  })
  return `linear-gradient(to right, ${parts.join(', ')})`
}

/** Evenly spaced tick values across a range, ends included. */
export function rangeTicks(range: { min: number; max: number }, count = 5): number[] {
  return Array.from({ length: count }, (_, i) => Math.round(range.min + ((range.max - range.min) * i) / (count - 1)))
}
