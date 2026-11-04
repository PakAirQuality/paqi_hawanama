import { describe, expect, it } from 'vitest'
import { axisTicks, endLabelOffsets, lastNonNullIndex, niceMax, toChartRows } from './seasonAlign'
import type { SeasonsResponse } from './api'

const days = Array.from({ length: 61 }, (_, i) => {
  const d = new Date(Date.UTC(2026, 9, 1 + i))
  return `${String(d.getUTCMonth() + 1).padStart(2, '0')}-${String(d.getUTCDate()).padStart(2, '0')}`
})

describe('seasonAlign', () => {
  it('keeps gaps as nulls and aligns years by day of season', () => {
    const data = { days, years: [
      { year: 2026, role: 'current', fires: days.map((_, i) => (i < 15 ? null : i)), r7: days.map((_, i) => (i < 18 ? null : i)), total: 1, total_to_date: 1, days_with_data: 46, days_missing: 15, suspect_days: 0, first_day_with_data: null },
      { year: 2025, role: 'last', fires: days.map(() => 1), r7: days.map(() => 2), total: 1, total_to_date: 1, days_with_data: 61, days_missing: 0, suspect_days: 0, first_day_with_data: null },
    ] } as unknown as SeasonsResponse
    const rows = toChartRows(data)
    expect(rows).toHaveLength(61)
    expect(rows[0].label).toBe('1 Oct')
    expect(rows[60].label).toBe('30 Nov')
    expect(rows[14].y2026).toBeNull()
    expect(rows[18].y2026).toBe(18)
    expect(rows[5].y2025).toBe(2)
    expect(lastNonNullIndex(data.years[0].r7)).toBe(60)
    expect(niceMax(data.years)).toBe(100)
  })
  it('ticks on the 1st and 15th and the last day', () => {
    expect(axisTicks(days)).toEqual([0, 14, 31, 45, 60])
  })
  it('separates end labels that would collide and leaves distant ones alone', () => {
    const off = endLabelOffsets([{ key: 'a', value: 100 }, { key: 'b', value: 102 }, { key: 'c', value: 500 }], 1000, 300, 11)
    expect(off.a).toBe(0)
    expect(off.b).toBeCloseTo(1000 / 300 * 11 - 2, 5)
    expect(off.c).toBe(0)
    const top = endLabelOffsets([{ key: 'a', value: 995 }, { key: 'b', value: 998 }], 1000, 300, 11)
    expect(998 + top.b).toBeLessThanOrEqual(1000)
  })
})
