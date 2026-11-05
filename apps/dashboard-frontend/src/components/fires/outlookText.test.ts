import { describe, expect, it } from 'vitest'
import { leadSentence, leadTitle } from './outlookText'
import type { OutlookLead } from './api'

const lead = (over: Partial<OutlookLead>): OutlookLead => ({
  lead: 'D+1', day: '2026-11-06', status: 'ok', wind_850: { from_deg: 315, from_compass: 'NW', speed_ms: 4.8, n_hours: 24 }, wind_10m: null,
  fires_200km: 300, band: 'high', upwind_load_mw: 1534.1, fires_reachable: 255, by_country: { Pakistan: 255 }, ...over,
})

describe('outlook text', () => {
  it('titles leads and writes the one-line sentence', () => {
    expect(leadTitle(lead({ day: '2026-11-05', lead: 'D+0' }), '2026-11-05')).toBe('Today')
    expect(leadTitle(lead({}), '2026-11-05')).toBe('Tomorrow')
    expect(leadTitle(lead({ lead: 'D+2', day: '2026-11-07' }), '2026-11-05')).toBe('7 Nov')
    expect(leadSentence(lead({}))).toBe('NW wind, 4.8 m/s; 1,534 MW upwind (255 in Pakistan)')
    expect(leadSentence(lead({ fires_reachable: 0, by_country: {}, upwind_load_mw: 0 }))).toBe('NW wind, 4.8 m/s; 0 MW upwind (no reachable fires in the cone)')
    expect(leadSentence(lead({ status: 'no_forecast', wind_850: null }))).toBe('No forecast wind for this day.')
  })
})
