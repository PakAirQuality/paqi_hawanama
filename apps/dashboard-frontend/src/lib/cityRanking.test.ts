import { describe, expect, it } from 'vitest'
import { worstRankedCities } from './cityRanking'

const city = (name: string, count: number) => ({ name, count })

describe('worstRankedCities', () => {
  it('leaves out cities with 5 monitors or fewer', () => {
    const out = worstRankedCities([city('One', 1), city('Five', 5), city('Six', 6), city('Fifty', 50)])
    expect(out.map(c => c.name)).toEqual(['Six', 'Fifty'])
  })

  it('keeps the order it was given', () => {
    const out = worstRankedCities([city('Worst', 8), city('Skip', 2), city('Next', 7)])
    expect(out.map(c => c.name)).toEqual(['Worst', 'Next'])
  })

  it('stops at five, counted after filtering', () => {
    const cities = [city('Small', 1), ...['A', 'B', 'C', 'D', 'E', 'F', 'G'].map(n => city(n, 10))]
    expect(worstRankedCities(cities).map(c => c.name)).toEqual(['A', 'B', 'C', 'D', 'E'])
  })

  it('returns an empty list when no city qualifies', () => {
    expect(worstRankedCities([city('Small', 5)])).toEqual([])
    expect(worstRankedCities([])).toEqual([])
  })
})
