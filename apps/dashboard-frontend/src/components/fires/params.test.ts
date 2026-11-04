import { describe, expect, it } from 'vitest'
import { defaultSeason, parseFiresParams, serializeFiresParams } from './params'
import { trackerFireLink } from './mapLink'
import { shiftDateOnly } from '@/lib/time'

describe('fires params', () => {
  it('defaults and validates', () => {
    const p = parseFiresParams('', { today: '2026-11-05' })
    expect(p).toEqual({ region: 'pakistan', season: 'rice', city: null, date: '2026-11-04' })
    expect(defaultSeason('2026-05-01')).toBe('wheat')
    const bad = parseFiresParams('?region=Narnia&season=monsoon&date=2030-01-01', { today: '2026-11-05', districts: [{ name: 'Sheikhpura' }] })
    expect(bad).toEqual({ region: 'pakistan', season: 'rice', city: null, date: '2026-11-04' })
    const d = parseFiresParams('?region=Sheikhpura&season=wheat&city=Lahore&date=2026-10-20', { today: '2026-11-05', districts: [{ name: 'Sheikhpura' }] })
    expect(d).toEqual({ region: 'Sheikhpura', season: 'wheat', city: 'Lahore', date: '2026-10-20' })
  })
  it('serialises only what differs from the defaults', () => {
    expect(serializeFiresParams({ region: 'pakistan', season: 'rice', city: null, date: '2026-11-04' }, '2026-11-05')).toBe('')
    expect(serializeFiresParams({ region: 'punjab', season: 'wheat', city: 'Lahore', date: '2026-10-20' }, '2026-11-05')).toBe('?region=punjab&season=wheat&city=Lahore&date=2026-10-20')
  })
  it('shifts dates zone-safely and builds tracker links', () => {
    expect(shiftDateOnly('2026-11-01', -1)).toBe('2026-10-31')
    expect(shiftDateOnly('2026-02-28', 1)).toBe('2026-03-01')
    expect(trackerFireLink({ date: '2026-11-03', lat: 31.5, lon: 74.3 })).toBe('/?date=2026-11-03&layers=fires&focus=31.5000%2C74.3000%2C9')
  })
})
