import { describe, expect, it } from 'vitest'
import { briefKey, isBriefResponse, requestBody, voiceTarget, type VoiceTarget } from './voiceBrief'
import { availableHours, nowcastValidTime } from './timeline'
import type { NowcastResponse } from '@/components/analyst-desk/types'
import type { StationReading } from '@/components/ops-pipeline/types'

const NOW = Date.parse('2026-11-06T20:00:00Z')
const HERE = { lat: 31.457, lng: 74.41 }
const hbfc: StationReading = { name: 'HBFC Society', city: 'Lahore', pm25: 178.7, lat: 31.457165, lon: 74.410659, station_id: 'hbfc' }
const far: StationReading = { name: 'Karachi', city: 'Karachi', pm25: 60, lat: 24.86, lon: 67.0, station_id: 'khi' }

function nowcast(leads: { h: number; at: string; pm25: number | null }[], over: Partial<NowcastResponse['stations'][number]> = {}): NowcastResponse {
  return {
    init_time: '2026-11-06T18:00:00Z', generated_at: '', model_tag: '', leads: [3, 6, 12], n_stations: 1, data_quality: {},
    stations: [{
      sensor_id: 1, station_id: 'hbfc', member_station_ids: [], station_name: 'HBFC Society', city: 'Lahore',
      latitude: 31.457, longitude: 74.41, basis: 'model', forecastable: true, last_obs: 170, obs_age_h: 1, n_valid_24h: 22,
      leads: leads.map(l => ({ lead_hours: l.h, valid_time: l.at, pm25: l.pm25, q75: null, q90: null })),
      ...over,
    }],
  }
}

describe('voiceTarget', () => {
  const base = { location: HERE, stations: [hbfc, far], liveFailed: false, nowcast: null, now: NOW }

  it('picks the nearest monitor', () => {
    const r = voiceTarget(base)
    expect(r.availability).toBe('ready')
    expect(r.target?.station).toBe('HBFC Society')
    expect(r.target?.distKm).toBeLessThan(1)
  })

  it('says what is missing instead of failing', () => {
    expect(voiceTarget({ ...base, location: null }).availability).toBe('no-location')
    expect(voiceTarget({ ...base, location: null, outside: true }).availability).toBe('outside')
    // A location inside Pakistan wins over an older "outside" result
    expect(voiceTarget({ ...base, outside: true }).availability).toBe('ready')
    expect(voiceTarget({ ...base, location: { lat: NaN, lng: 74 } }).availability).toBe('no-location')
    expect(voiceTarget({ ...base, stations: undefined }).availability).toBe('waiting')
    expect(voiceTarget({ ...base, stations: undefined, liveFailed: true }).availability).toBe('no-data')
    expect(voiceTarget({ ...base, stations: [] }).availability).toBe('no-monitor')
    expect(voiceTarget({ ...base, stations: [far] }).availability).toBe('no-monitor') // over 50 km
  })

  it('skips monitors with a broken value or position', () => {
    const broken = [
      { ...hbfc, name: 'NaN value', pm25: NaN },
      { ...hbfc, name: 'Negative', pm25: -5 },
      { ...hbfc, name: 'No position', lat: undefined as unknown as number },
      { ...hbfc, name: 'Text value', pm25: '90' as unknown as number },
    ]
    expect(voiceTarget({ ...base, stations: broken }).availability).toBe('no-monitor')
    expect(voiceTarget({ ...base, stations: [...broken, { ...hbfc, lat: 31.46 }] }).target?.station).toBe('HBFC Society')
  })

  it('takes the nowcast value nearest 6 hours ahead', () => {
    const nc = nowcast([
      { h: 3, at: '2026-11-06T21:00:00Z', pm25: 172 }, // 1 h ahead: too soon
      { h: 6, at: '2026-11-07T00:00:00Z', pm25: 174 }, // 4 h ahead
      { h: 12, at: '2026-11-07T06:00:00Z', pm25: 120 }, // 10 h ahead
    ])
    expect(voiceTarget({ ...base, nowcast: nc }).target?.next).toEqual({ pm25: 174, hours: 4 })
  })

  it('drops an outlook with bad times or values, or a malformed nowcast', () => {
    const bad = nowcast([
      { h: 6, at: 'not a date', pm25: 150 },
      { h: 12, at: '2026-11-07T02:00:00Z', pm25: null },
    ])
    expect(voiceTarget({ ...base, nowcast: bad }).target?.next).toBeNull()
    const noLeads = nowcast([], { leads: undefined as unknown as [] })
    expect(voiceTarget({ ...base, nowcast: noLeads }).target?.next).toBeNull()
    const noStations = { ...nowcast([]), stations: undefined } as unknown as NowcastResponse
    expect(voiceTarget({ ...base, nowcast: noStations }).availability).toBe('ready')
    expect(voiceTarget({ ...base, nowcast: nowcast([{ h: 6, at: '2026-11-07T00:00:00Z', pm25: 1 }]), now: NaN }).target?.next).toBeNull()
  })
})

describe('malformed nowcast elsewhere on the Tracker', () => {
  it('does not throw', () => {
    const noStations = { ...nowcast([]), stations: undefined } as unknown as NowcastResponse
    expect(nowcastValidTime(noStations, 3)).toBeNull()
    expect(availableHours(noStations, '2026-11-06T20:00:00Z')).toEqual([])
    const noLeads = nowcast([], { leads: undefined as unknown as [] })
    expect(availableHours(noLeads, '2026-11-06T20:00:00Z')).toEqual([])
  })
})

describe('requestBody', () => {
  const t: VoiceTarget = { station: 'HBFC Society', city: 'Lahore', distKm: 0.4, pm25: 178.7, next: { pm25: 174, hours: 4 } }

  it('sends the reading and outlook', () => {
    expect(requestBody(t, 'ur')).toEqual({ lang: 'ur', station: 'HBFC Society', city: 'Lahore', pm25: 178.7, next_pm25: 174, next_hours: 4 })
  })

  it('cleans names the server would refuse', () => {
    const b = requestBody({ ...t, station: 'Bad <name> {x}\n$1', city: 'Lahore`' }, 'en')
    expect(b.station).toBe('Bad name x 1')
    expect(b.city).toBe('Lahore')
    expect(requestBody({ ...t, station: 'x'.repeat(200) }, 'en').station).toHaveLength(80)
  })

  it('never sends an empty station', () => {
    expect(requestBody({ ...t, station: '  ' }, 'en').station).toBe('Lahore')
    expect(requestBody({ ...t, station: '<>', city: '' }, 'en').station).toBe('the nearest monitor')
    expect(requestBody({ ...t, station: undefined as unknown as string }, 'en').station).toBe('Lahore')
  })

  it('keeps numbers inside the accepted ranges', () => {
    const b = requestBody({ ...t, distKm: 80, pm25: 2500, next: { pm25: -3, hours: 40 } }, 'en')
    expect(b).toMatchObject({ pm25: 1000, next_pm25: 0, next_hours: 24 })
    expect(b).not.toHaveProperty('distance_km')
    const nan = requestBody({ ...t, distKm: NaN, pm25: NaN, next: { pm25: NaN, hours: 6 } }, 'en')
    expect(nan.pm25).toBe(0)
    expect(nan).not.toHaveProperty('next_pm25')
  })
})

describe('isBriefResponse', () => {
  it('accepts only a playable reply', () => {
    expect(isBriefResponse({ text: 'Hi', mime: 'audio/wav', audio: 'UklGRg==' })).toBe(true)
    for (const bad of [null, undefined, 'x', 42, [], {}, { text: 'Hi', mime: 'audio/wav', audio: '' }, { text: 'Hi', audio: 'x' }, { detail: 'error' }]) {
      expect(isBriefResponse(bad)).toBe(false)
    }
  })
})

describe('briefKey', () => {
  it('matches equal rounded readings and tells outlooks apart', () => {
    const a: VoiceTarget = { station: 'S', city: 'C', distKm: 2.2, pm25: 100.2 }
    // Distance is not spoken, so visitors at any distance from the monitor share one recording
    expect(briefKey(a)).toBe(briefKey({ ...a, distKm: 30, pm25: 99.6 }))
    expect(briefKey(a)).not.toBe(briefKey({ ...a, next: { pm25: 150, hours: 6 } }))
  })
})
