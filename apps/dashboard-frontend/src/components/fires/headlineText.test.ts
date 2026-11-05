import { describe, expect, it } from 'vitest'
import { headlineParts, headlineSentence } from './headlineText'
import type { SeasonsResponse } from './api'

function resp(over: Partial<SeasonsResponse['headline']> = {}, season: Partial<SeasonsResponse['season']> = {}, basis: SeasonsResponse['basis'] = 'all'): SeasonsResponse {
  return {
    region: { kind: 'country', name: 'Pakistan', label: 'Pakistan' },
    basis,
    season: { id: 'rice', key: 'k', label: 'l', year: 2026, start: '2026-09-15', end: '2026-11-30', end_effective: '2026-11-03', complete: false, ...season },
    days: [], today_index: 49, years: [], method: { r7: '', comparison: '' }, caveats: [], store_built_at: null,
    headline: {
      window: { start: '2026-09-15', end: '2026-11-03', days: 50, days_with_data: 19, days_missing: 31, compared_dates: '16 Oct – 3 Nov' },
      fires: 12726, fires_per_day: 669.8, frp_mw: 118342, day: 11230, night: 1390, night_share: 0.11,
      last_year: { year: 2025, fires: 13700, pct_change: -7, days_with_data: 19 },
      reference: { years: [2020, 2021, 2022, 2023, 2024, 2025], used_years: [2020, 2021, 2022, 2023, 2024, 2025], rows: [], mean: 29600, min: 1, max: 2, pct_change: -57, higher_than_n_of: [0, 6], rank_text: 'lower than every reference year' },
      ...over,
    },
  }
}

const N20 = {
  basis: 'n20' as const, basis_label: 'NOAA-20 only', fires: 8100, days_with_data: 19, note: '',
  last_year: { year: 2025, fires: 9000, pct_change: -10, days_with_data: 19 },
  reference: { years: [2020], used_years: [2020, 2025], rows: [], mean: 16000, min: 1, max: 2, pct_change: -49, higher_than_n_of: [1, 6] as [number, number], rank_text: 'higher than 1 of the 6 reference years' },
}

describe('headline', () => {
  it('builds the in-season sentence with gaps, last year and the reference mean (old store: no NOAA-20 block)', () => {
    const p = headlineParts(resp(), 'Pakistan')
    expect(headlineSentence(p, 'Pakistan')).toBe(
      'So far this season (16 Oct – 3 Nov, the 19 days with data) Pakistan has seen 12,726 fire detections, 7% fewer than the same dates in 2025 and 57% fewer than the 2020–2025 average on those dates (lower than every reference year).'
    )
    expect(p.basisNote).toBeNull()
    expect(p.subline).toContain('indicative only')
  })
  it('takes the year-on-year clauses from the NOAA-20-only block when the store carries it', () => {
    const p = headlineParts(resp({ comparison_n20: N20 }), 'Pakistan')
    expect(headlineSentence(p, 'Pakistan')).toBe(
      'So far this season (16 Oct – 3 Nov, the 19 days with data) Pakistan has seen 12,726 fire detections, 10% fewer than the same dates in 2025 and 49% fewer than the 2020–2025 average on those dates (NOAA-20 only) (higher than 1 of the 6 reference years).'
    )
    expect(p.subline).toContain('hold the satellite fixed')
  })
  it('on the n20 basis the count itself is NOAA-20 and no extra note is added', () => {
    const p = headlineParts(resp({}, {}, 'n20'), 'Pakistan')
    expect(p.basisNote).toBeNull()
    expect(p.subline).toContain('from NOAA-20 alone')
  })
  it('drops the gap note, the missing last year, and says "about the same" under 1%', () => {
    const p = headlineParts(resp({ window: { start: '2026-09-15', end: '2026-11-03', days: 50, days_with_data: 50, days_missing: 0, compared_dates: '15 Sep – 3 Nov' }, last_year: null,
      reference: { years: [2020], used_years: [2024, 2025], rows: [], mean: 12700, min: 1, max: 2, pct_change: 0, higher_than_n_of: [1, 2], rank_text: 'higher than 1 of the 2 reference years' } }), 'Sindh')
    expect(headlineSentence(p, 'Sindh')).toBe('So far this season (15 Sep – 3 Nov) Sindh has seen 12,726 fire detections, about the same as the 2024–2025 average on those dates (higher than 1 of the 2 reference years).')
  })
  it('names the crop basis in the unit and the subline', () => {
    const p = headlineParts(resp({ comparison_n20: { ...N20, basis: 'crop_n20' } }, {}, 'crop'), 'Punjab')
    expect(p.unit).toBe('likely crop-residue fire detections')
    expect(p.subline).toContain('unvalidated classification')
    expect(p.basisNote).toBe('NOAA-20 only')
  })
  it('names a complete season', () => {
    const p = headlineParts(resp({}, { complete: true, start: '2026-04-15', end: '2026-05-31' }), 'Punjab')
    expect(p.lead).toBe('In the 2026 season (15 Apr – 31 May, the 19 days with data)')
    expect(p.subline).toContain('deduplicated detection clusters')
  })
})
