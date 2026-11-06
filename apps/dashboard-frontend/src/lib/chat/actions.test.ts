import { describe, expect, it } from 'vitest'
import { actionLabel, cityCentre, extractActions, parseAction } from './actions'

describe('parseAction', () => {
  it('accepts each known action', () => {
    expect(parseAction({ type: 'zoom_to_city', city: 'Lahore' })).toEqual({ type: 'zoom_to_city', city: 'Lahore' })
    expect(parseAction({ type: 'zoom_to_station', lat: 31.5, lng: 74.3 })).toEqual({ type: 'zoom_to_station', lat: 31.5, lng: 74.3 })
    expect(parseAction({ type: 'set_horizon', horizon: 3 })).toEqual({ type: 'set_horizon', horizon: 3 })
    expect(parseAction({ type: 'filter_network', network: 'PAQI' })).toEqual({ type: 'filter_network', network: 'PAQI' })
    expect(parseAction({ type: 'filter_network', network: null })).toEqual({ type: 'filter_network', network: null })
    expect(parseAction({ type: 'show_station_trend', station_id: 'abc', hours: 48 })).toEqual({ type: 'show_station_trend', station_id: 'abc', hours: 48 })
    expect(parseAction({ type: 'show_trajectory', lat: 31.52, lon: 74.36, at: '2026-11-05T23:00:00', hours: 72, direction: 'backward', label: 'Lahore', engine: 'kinematic_ecmwf_ifs025', extra: 1 }))
      .toEqual({ type: 'show_trajectory', lat: 31.52, lon: 74.36, at: '2026-11-05T23:00:00', hours: 72, direction: 'backward', label: 'Lahore', engine: 'kinematic_ecmwf_ifs025' })
  })

  it('rejects a trajectory outside the box, without a time, or with an odd direction', () => {
    expect(parseAction({ type: 'show_trajectory', lat: 51.5, lon: 0.1, at: '2026-11-05T23:00:00', hours: 72, direction: 'backward' })).toBeNull()
    expect(parseAction({ type: 'show_trajectory', lat: 31.5, lon: 74.4, hours: 72, direction: 'backward' })).toBeNull()
    expect(parseAction({ type: 'show_trajectory', lat: 31.5, lon: 74.4, at: 'yesterday', hours: 72, direction: 'backward' })).toBeNull()
    expect(parseAction({ type: 'show_trajectory', lat: 31.5, lon: 74.4, at: '2026-11-05T23:00:00', hours: 500, direction: 'backward' })).toBeNull()
    expect(parseAction({ type: 'show_trajectory', lat: 31.5, lon: 74.4, at: '2026-11-05T23:00:00', hours: 72, direction: 'sideways' })).toBeNull()
  })

  it('drops fields it does not know', () => {
    expect(parseAction({ type: 'zoom_to_city', city: 'Lahore', href: 'https://evil.example', __proto__: {} })).toEqual({ type: 'zoom_to_city', city: 'Lahore' })
  })

  it.each([
    ['nothing', undefined],
    ['a string', 'zoom_to_city'],
    ['an unknown type', { type: 'delete_everything' }],
    ['a city that is missing', { type: 'zoom_to_city' }],
    ['a city that is not text', { type: 'zoom_to_city', city: 7 }],
    ['an absurdly long city', { type: 'zoom_to_city', city: 'x'.repeat(500) }],
    ['a latitude off the planet', { type: 'zoom_to_station', lat: 900, lng: 74 }],
    ['a station with no way to find it', { type: 'zoom_to_station', lat: 31 }],
    ['a NaN coordinate', { type: 'zoom_to_station', lat: NaN, lng: 74 }],
    ['a negative horizon', { type: 'set_horizon', horizon: -1 }],
    ['a fractional horizon', { type: 'set_horizon', horizon: 1.5 }],
    ['a trend with no station', { type: 'show_station_trend', hours: 24 }],
  ])('rejects %s', (_, raw) => {
    expect(parseAction(raw)).toBeNull()
  })

  it('ignores an out-of-range trend length instead of passing it on', () => {
    expect(parseAction({ type: 'show_station_trend', station_id: 'abc', hours: 999999 })).toEqual({ type: 'show_station_trend', station_id: 'abc' })
  })
})

describe('extractActions', () => {
  it('removes tags from the text and returns the actions', () => {
    const { clean, actions } = extractActions('Look here {{ACTION:{"type":"zoom_to_city","city":"Lahore"}}} now')
    expect(clean).toBe('Look here  now')
    expect(actions).toEqual([{ type: 'zoom_to_city', city: 'Lahore' }])
  })

  it('removes tags that fail validation without showing them', () => {
    const { clean, actions } = extractActions('A {{ACTION:{"type":"nope"}}}B {{ACTION:{bad json}}}C')
    expect(clean).toBe('A B C')
    expect(actions).toEqual([])
  })

  it.each(['{', '{{', '{{ACT', '{{ACTION:', '{{ACTION:{"type":"zoom'])('hides a tag still arriving: %s', tail => {
    expect(extractActions(`Done ${tail}`).clean).toBe('Done ')
  })

  it('leaves ordinary braces alone', () => {
    expect(extractActions('Use {x} here').clean).toBe('Use {x} here')
  })
})

describe('actionLabel', () => {
  it('describes what pressing the button will do', () => {
    expect(actionLabel({ type: 'zoom_to_city', city: 'Multan' })).toBe('Show Multan')
    expect(actionLabel({ type: 'set_horizon', horizon: 0 })).toBe('Show today')
    expect(actionLabel({ type: 'filter_network', network: null })).toBe('Show all networks')
    expect(actionLabel({ type: 'show_station_trend', hours: 168 })).toBe('7d trend')
    expect(actionLabel({ type: 'show_station_trend' })).toBe('24h trend')
  })
})

describe('cityCentre', () => {
  const stations = [
    { city: 'Lahore', lat: 31, lon: 74 },
    { city: ' lahore ', lat: 33, lon: 76 },
    { city: 'Lahore', lat: null, lon: 80 },
    { city: 'Multan', lat: 30, lon: 71 },
  ]

  it('averages the stations with a position, ignoring case and spacing', () => {
    expect(cityCentre(stations, 'LAHORE')).toEqual({ lng: 75, lat: 32 })
  })

  it('returns null for a city it has no stations for', () => {
    expect(cityCentre(stations, 'Quetta')).toBeNull()
    expect(cityCentre([{ city: 'Quetta', lat: null, lon: null }], 'Quetta')).toBeNull()
  })
})
