import { describe, expect, it } from 'vitest'
import type { CurrentStation, ForecastEntry } from '@/components/analyst-desk/types'
import { availableLeads, daysBetween, forecastReadings, isForecastLead, latestReading, leadForDaysAhead, liveReadings, rampCount, stationForecastDays, targetDate } from './timeline'

const entry = (over: Partial<ForecastEntry> = {}): ForecastEntry => ({
  sensor_id: 1, station_name: 'Korangi', latitude: 24.8, longitude: 67.1, city_name: 'Karachi', state_name: 'Sindh',
  init_date: '2026-11-01', lead_days: 1, target_date: '2026-11-02', pm25_forecast: 86, pm25_q75: 100, pm25_q90: 114,
  ramp_detected: false, source_ifs: true, source_cams: true, source_geos_cf: true, mos_applied: true,
  risk_band: 'unhealthy', episode_state: 'stable', confidence: 'high', priority: 'monitor', ...over,
})

const live = (over: Partial<CurrentStation> = {}): CurrentStation => ({
  id: 'a1', name: 'GCU', latitude: 31.5, longitude: 74.3, city: 'Lahore', pm25: 200, aqi_raw: 250,
  aqi_category: 'very_unhealthy', last_reading: '2026-11-01T10:00:00Z', ...over,
})

describe('availableLeads', () => {
  const today = '2026-11-01'

  it('lists the forecast days ahead of today, in order', () => {
    const rows = [entry({ lead_days: 3, target_date: '2026-11-04' }), entry(), entry({ lead_days: 2, target_date: '2026-11-03' })]
    expect(availableLeads(rows, today)).toEqual([1, 2, 3])
  })

  it('offers nothing from a stalled forecast, so old numbers never pass as future ones', () => {
    expect(availableLeads([entry({ init_date: '2026-05-06', target_date: '2026-05-07' })], today)).toEqual([])
  })

  it('drops days that have already arrived, keeping those still ahead', () => {
    const rows = [entry({ target_date: '2026-11-01' }), entry({ lead_days: 2, target_date: '2026-11-02' })]
    expect(availableLeads(rows, today)).toEqual([2])
  })

  it('ignores a day with no forecast values', () => {
    expect(availableLeads([entry({ pm25_forecast: null })], today)).toEqual([])
  })

  it('ignores lead times the timeline has no place for', () => {
    expect(availableLeads([entry({ lead_days: 7, target_date: '2026-11-08' })], today)).toEqual([])
  })
})

describe('leadForDaysAhead', () => {
  const rows = [entry({ target_date: '2026-11-02' }), entry({ lead_days: 2, target_date: '2026-11-03' })]

  it('counts from today, not from the forecast run', () => {
    expect(leadForDaysAhead(rows, '2026-11-01', 1)).toBe(1)
    // The next morning, before that day's run: tomorrow is the run's second day
    expect(leadForDaysAhead(rows, '2026-11-02', 1)).toBe(2)
  })

  it('finds nothing for a day the run does not cover', () => {
    expect(leadForDaysAhead(rows, '2026-11-02', 3)).toBeNull()
    expect(leadForDaysAhead([], '2026-11-02', 1)).toBeNull()
  })
})

describe('daysBetween', () => {
  it('counts whole days, across a month end', () => {
    expect(daysBetween('2026-10-31', '2026-11-02')).toBe(2)
    expect(daysBetween('2026-11-02', '2026-11-02')).toBe(0)
  })
})

describe('forecastReadings', () => {
  it('returns one forecast day in the shape the map uses', () => {
    expect(forecastReadings([entry(), entry({ lead_days: 2, pm25_forecast: 90 })], 1)).toEqual([
      { name: 'Korangi', city: 'Karachi', pm25: 86, lat: 24.8, lon: 67.1 },
    ])
  })

  it('carries the station id, so a forecast station opens with its history', () => {
    expect(forecastReadings([entry({ station_id: 'pk-12' })], 1)[0].station_id).toBe('pk-12')
  })

  it('counts a station listed twice once', () => {
    expect(forecastReadings([entry({ sensor_id: 1 }), entry({ sensor_id: 2 })], 1)).toHaveLength(1)
  })

  it('keeps stations with the same name in different cities', () => {
    expect(forecastReadings([entry(), entry({ city_name: 'Lahore' })], 1)).toHaveLength(2)
  })

  it('skips rows with no value or position', () => {
    const rows = [entry({ pm25_forecast: null }), entry({ latitude: null }), entry({ longitude: null })]
    expect(forecastReadings(rows, 1)).toEqual([])
  })
})

describe('stationForecastDays', () => {
  const rows = [
    entry({ lead_days: 3, target_date: '2026-11-05', pm25_forecast: 120, pm25_q90: 170 }),
    entry({ lead_days: 1, target_date: '2026-11-03', pm25_forecast: 86, pm25_q90: 114 }),
    entry({ lead_days: 2, target_date: '2026-11-04', pm25_forecast: 95, pm25_q90: 130 }),
    entry({ station_name: 'Elsewhere', pm25_forecast: 500 }),
    entry({ city_name: 'Lahore', pm25_forecast: 501 }),
  ]

  it('lists one station’s days, soonest first', () => {
    expect(stationForecastDays(rows, '2026-11-02', 'Korangi', 'Karachi')).toEqual([
      { date: '2026-11-03', lead: 1, pm25: 86, high: 114 },
      { date: '2026-11-04', lead: 2, pm25: 95, high: 130 },
      { date: '2026-11-05', lead: 3, pm25: 120, high: 170 },
    ])
  })

  it('leaves out days that have arrived, so a morning-old run does not show today as a forecast', () => {
    expect(stationForecastDays(rows, '2026-11-03', 'Korangi', 'Karachi').map(d => d.date)).toEqual(['2026-11-04', '2026-11-05'])
  })

  it('counts a day listed twice once', () => {
    expect(stationForecastDays([rows[1], { ...rows[1], pm25_forecast: 999 }], '2026-11-02', 'Korangi', 'Karachi')).toHaveLength(1)
  })

  it('finds nothing for a station without a forecast', () => {
    expect(stationForecastDays(rows, '2026-11-02', 'Nowhere', 'Karachi')).toEqual([])
  })
})

describe('liveReadings', () => {
  it('maps latest readings onto the map shape', () => {
    expect(liveReadings([live()])).toEqual([{ name: 'GCU', city: 'Lahore', pm25: 200, lat: 31.5, lon: 74.3, station_id: 'a1' }])
  })

  it('leaves out stations with no reading', () => {
    expect(liveReadings([live({ pm25: null })])).toEqual([])
  })
})

describe('helpers', () => {
  it('counts ramp warnings for the chosen day only', () => {
    const rows = [entry({ ramp_detected: true }), entry({ lead_days: 2, ramp_detected: true }), entry()]
    expect(rampCount(rows, 1)).toBe(1)
  })

  it('finds a forecast day’s date', () => {
    expect(targetDate([entry({ lead_days: 2, target_date: '2026-11-03' })], 2)).toBe('2026-11-03')
    expect(targetDate([], 1)).toBeNull()
  })

  it('finds the newest reading', () => {
    const stations = [live(), live({ last_reading: '2026-11-01T12:00:00Z' }), live({ last_reading: '' })]
    expect(latestReading(stations)).toBe('2026-11-01T12:00:00Z')
    expect(latestReading([])).toBeNull()
  })

  it('tells forecast steps from today and past days', () => {
    expect(isForecastLead(2)).toBe(true)
    expect(isForecastLead('now')).toBe(false)
    expect(isForecastLead('2026-10-31')).toBe(false)
    expect(isForecastLead(null)).toBe(false)
  })
})
