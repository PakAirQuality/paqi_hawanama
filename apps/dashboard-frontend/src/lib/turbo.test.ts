import { describe, expect, it } from 'vitest'
import { rangeTicks, SURFACE_RANGE, turboGradient, turboRgb } from './turbo'

describe('turboRgb', () => {
  it('matches the colours the API paints at the ends of the ramp', () => {
    // Values from the API's own formula (TURBO_CMAP[0] and TURBO_CMAP[255])
    expect(turboRgb(0)).toEqual([35, 23, 27])
    expect(turboRgb(1)).toEqual([144, 12, 0])
  })

  it('matches a colour read from a real surface tile', () => {
    // A tile pixel of 100,253,111 is the API's TURBO_CMAP entry for grey level 111
    expect(turboRgb(111 / 255)).toEqual([100, 253, 111])
  })

  it('holds values outside 0 to 1 at the ends', () => {
    expect(turboRgb(-1)).toEqual(turboRgb(0))
    expect(turboRgb(2)).toEqual(turboRgb(1))
  })
})

describe('legend helpers', () => {
  it('builds a left-to-right gradient that ends on the ramp’s last colour', () => {
    const g = turboGradient(4)
    expect(g.startsWith('linear-gradient(to right, rgb(35 23 27) 0%')).toBe(true)
    expect(g.endsWith('rgb(144 12 0) 100%)')).toBe(true)
  })

  it('places ticks evenly across the surface range', () => {
    expect(rangeTicks(SURFACE_RANGE)).toEqual([20, 60, 100, 140, 180])
  })
})
