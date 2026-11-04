import { describe, expect, it } from 'vitest'
import type { CurrentStation, ForecastEntry, NowcastResponse, NowcastStation } from '@/components/analyst-desk/types'
import { availableHours, availableLeads, daysBetween, forecastReadings, hourStep, isForecastLead, isHourStep, latestReading, leadForDaysAhead, liveReadings, nowcastAgeMin, nowcastReadings, nowcastValidTime, parseViewParam, rampCount, sameStep, stationForecastDays, stationNowcastPoints, stepKey, targetDate } from './timeline'

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

// ── Hourly nowcast ──

const ncStation = (over: Partial<NowcastStation> = {}): NowcastStation => ({
  sensor_id: 1, station_id: 'pk-1', member_station_ids: ['pk-1', 'old-1'], station_name: 'Korangi', city: 'Karachi',
  latitude: 24.8, longitude: 67.1, basis: 'model', forecastable: true, last_obs: 80, obs_age_h: 1, n_valid_24h: 20,
  leads: [
    { lead_hours: 3, valid_time: '2026-11-04T12:00:00+00:00', pm25: 85, q75: 95, q90: 110 },
    { lead_hours: 6, valid_time: '2026-11-04T15:00:00+00:00', pm25: 90, q75: 100, q90: 120 },
    { lead_hours: 12, valid_time: '2026-11-04T21:00:00+00:00', pm25: 140, q75: 160, q90: 190 },
    { lead_hours: 24, valid_time: '2026-11-05T09:00:00+00:00', pm25: 100, q75: 120, q90: 150 },
  ],
  ...over,
})

const nowcast = (stations: NowcastStation[] = [ncStation()]): NowcastResponse => ({
  init_time: '2026-11-04T09:00:00+00:00', generated_at: '2026-11-04T09:21:00+00:00', model_tag: 'v1',
  leads: [3, 6, 12, 24], n_stations: stations.length, data_quality: {}, stations,
})

describe('hour steps', () => {
  it('are told apart from days and keyed stably', () => {
    expect(isHourStep(hourStep(6))).toBe(true)
    expect(isHourStep('now')).toBe(false)
    expect(isHourStep(2)).toBe(false)
    expect(isForecastLead(hourStep(6))).toBe(false)
    expect(stepKey(hourStep(6))).toBe('h6')
    expect(stepKey(2)).toBe('2')
    expect(stepKey('now')).toBe('now')
    expect(sameStep(hourStep(12), { kind: 'hour', h: 12 })).toBe(true)
    expect(sameStep(hourStep(12), hourStep(3))).toBe(false)
  })

  it('come from and go to the view URL parameter', () => {
    expect(parseViewParam('h6')).toEqual({ hour: 6 })
    expect(parseViewParam('h7')).toBeNull()
    expect(parseViewParam('h24')).toBeNull() // published by the API, hidden in the UI
    expect(parseViewParam('2')).toEqual({ daysAhead: 2 })
    expect(parseViewParam('today')).toEqual({ today: true })
    expect(parseViewParam(null)).toBeNull()
  })
})

describe('availableHours', () => {
  it('lists the leads still ahead of now, in order', () => {
    expect(availableHours(nowcast(), '2026-11-04T10:00:00Z')).toEqual([3, 6, 12])
  })

  it('drops leads whose hour has passed, so a stalled job never shows old numbers as the future', () => {
    expect(availableHours(nowcast(), '2026-11-04T16:00:00Z')).toEqual([12])
    expect(availableHours(nowcast(), '2026-11-06T00:00:00Z')).toEqual([])
  })

  it('ignores leads with no values anywhere', () => {
    const prior = ncStation({ basis: 'prior', forecastable: false, leads: ncStation().leads.map(l => ({ ...l, pm25: null, q75: null, q90: null })) })
    expect(availableHours(nowcast([prior]), '2026-11-04T10:00:00Z')).toEqual([])
    expect(availableHours(null, '2026-11-04T10:00:00Z')).toEqual([])
  })

  it('reports when each lead is for and how old the cycle is', () => {
    expect(nowcastValidTime(nowcast(), 12)).toBe('2026-11-04T21:00:00+00:00')
    expect(nowcastValidTime(nowcast(), 6)).toBe('2026-11-04T15:00:00+00:00')
    expect(nowcastAgeMin(nowcast(), '2026-11-04T10:30:00Z')).toBe(90)
  })
})

describe('nowcastReadings', () => {
  it('returns one lead in the shape the map uses, with its basis', () => {
    expect(nowcastReadings(nowcast(), 12)).toEqual([
      { name: 'Korangi', city: 'Karachi', pm25: 140, lat: 24.8, lon: 67.1, station_id: 'pk-1', basis: 'model', obs_available: true },
    ])
  })

  it('leaves out stations with no value and falls back to a member id', () => {
    const rows = [
      ncStation({ station_id: null, member_station_ids: ['m-1'], basis: 'neighbours', forecastable: false }),
      ncStation({ station_id: 'pk-2', basis: 'prior', forecastable: false, leads: ncStation().leads.map(l => ({ ...l, pm25: null })) }),
    ]
    const out = nowcastReadings(nowcast(rows), 3)
    expect(out).toHaveLength(1)
    expect(out[0]).toMatchObject({ station_id: 'm-1', basis: 'neighbours', obs_available: false })
  })
})

describe('stationNowcastPoints', () => {
  it('finds a station by its id, by a member id, or by name and city', () => {
    const pts = stationNowcastPoints(nowcast(), { station_id: 'old-1', name: 'x', city: 'y' })
    expect(pts.map(p => p.lead)).toEqual([3, 6, 12])
    expect(pts[2]).toEqual({ lead: 12, valid_time: '2026-11-04T21:00:00+00:00', pm25: 140, high: 190, basis: 'model' })
    expect(stationNowcastPoints(nowcast(), { name: 'Korangi', city: 'Karachi' })).toHaveLength(3)
    expect(stationNowcastPoints(nowcast(), { station_id: 'nope', name: 'Korangi', city: 'Lahore' })).toEqual([])
  })

  it('skips leads with no value', () => {
    const s = ncStation({ leads: ncStation().leads.map(l => (l.lead_hours === 3 ? { ...l, pm25: null } : l)) })
    expect(stationNowcastPoints(nowcast([s]), { station_id: 'pk-1', name: 'Korangi', city: 'Karachi' }).map(p => p.lead)).toEqual([6, 12])
  })
})
