/**
 * Colour map for the PM2.5 estimate surface: an air-quality style ramp (as on CAMS and Windy)
 * from clean blue through green and yellow to red and plum.
 */

type Stops = [number, [number, number, number]][]

const hex = (h: string): [number, number, number] => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)]

const STOPS: Stops = ['#8ccfe6', '#5fb8a8', '#9ccc65', '#f2d64a', '#f39c3d', '#e0544a', '#a62f6e', '#5a1d5c']
  .map((c, i, all) => [i / (all.length - 1), hex(c)])

/** Colour at t (0 to 1), as [r, g, b]. */
export function paletteRgb(t: number): [number, number, number] {
  if (!(t > 0)) return STOPS[0][1]
  if (t >= 1) return STOPS[STOPS.length - 1][1]
  for (let i = 1; i < STOPS.length; i++) {
    const [t1, c1] = STOPS[i]
    if (t <= t1) {
      const [t0, c0] = STOPS[i - 1]
      const k = (t - t0) / (t1 - t0)
      return [
        Math.round(c0[0] + (c1[0] - c0[0]) * k),
        Math.round(c0[1] + (c1[1] - c0[1]) * k),
        Math.round(c0[2] + (c1[2] - c0[2]) * k),
      ]
    }
  }
  return STOPS[STOPS.length - 1][1]
}

/** CSS gradient through the colour map, lowest on the left. */
export function paletteGradient(): string {
  return `linear-gradient(to right, ${STOPS.map(([t, c]) => `rgb(${c.join(' ')}) ${Math.round(t * 100)}%`).join(', ')})`
}

let lut: Uint8ClampedArray | null = null
/** 256-entry lookup table (RGB triplets), for painting many pixels quickly. */
export function paletteLut(): Uint8ClampedArray {
  if (!lut) {
    lut = new Uint8ClampedArray(256 * 3)
    for (let i = 0; i < 256; i++) lut.set(paletteRgb(i / 255), i * 3)
  }
  return lut
}

export const PALETTE_STOPS = STOPS
