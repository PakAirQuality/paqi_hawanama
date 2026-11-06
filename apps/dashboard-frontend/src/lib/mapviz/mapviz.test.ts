import { describe, expect, it } from 'vitest'
import { PALETTE_STOPS, paletteLut, paletteRgb } from './colormap'
import { predictionRaster } from './gridImage'


describe('air-quality colour map', () => {
  it('runs from its first to its last stop, and the lookup table matches', () => {
    expect(paletteRgb(0)).toEqual(PALETTE_STOPS[0][1])
    expect(paletteRgb(1)).toEqual(PALETTE_STOPS[PALETTE_STOPS.length - 1][1])
    expect(Array.from(paletteLut().slice(255 * 3, 256 * 3))).toEqual(PALETTE_STOPS[PALETTE_STOPS.length - 1][1])
  })
  it('ends darker than it starts (heavy pollution reads as the darkest colour)', () => {
    const lum = ([r, g, b]: number[]) => 0.2126 * r + 0.7152 * g + 0.0722 * b
    expect(lum(paletteRgb(1))).toBeLessThan(lum(paletteRgb(0)))
  })
})

describe('predictionRaster', () => {
  const grid = { shape: [2, 2], bounds: { west: 60, east: 61, south: 23, north: 24 } }
  it('keeps a grid written south to north as it is', () => {
    const r = predictionRaster({ grid, lats: [23, 23, 24, 24], lons: [60, 61, 60, 61], pm25: [1, 2, 3, 4] })!
    expect(Array.from(r.values)).toEqual([1, 2, 3, 4])
  })
  it('flips a grid written north to south (older prediction files), so the map is not drawn upside down', () => {
    const r = predictionRaster({ grid, lats: [24, 24, 23, 23], lons: [60, 61, 60, 61], pm25: [3, 4, 1, 2] })!
    expect(Array.from(r.values)).toEqual([1, 2, 3, 4])
  })
})
