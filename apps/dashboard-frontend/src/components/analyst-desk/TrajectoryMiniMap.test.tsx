import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TrajectoryMiniMap } from './TrajectoryMiniMap'
import { ChatMessage } from './ChatMessage'

const ACTION = { type: 'show_trajectory' as const, lat: 31.52, lon: 74.36, at: '2026-11-05T23:00:00', direction: 'backward' as const, hours: 72, label: 'Lahore' }

const point = (age: number, lat: number, lon: number, region: string) => ({
  age_h: age, time_utc: 't', lat, lon, height_agl_m: 700, z_msl_m: 800, speed_ms: 4, region, district: null,
})
const path = (dlat: number, dlon: number) => Array.from({ length: 73 }, (_, i) => point(-i, 31.52 + (dlat * i) / 72, 74.36 + (dlon * i) / 72, i < 30 ? 'Pakistan Punjab' : 'other Pakistan'))
const DOC = {
  engine: 'kinematic_ecmwf_ifs025', status: 'kinematic', direction: 'backward', hours: 72, levels_hpa: [1000, 925, 850],
  origin: { lat: 31.52, lon: 74.36, label: 'Lahore' }, at_utc: '2026-11-05T23:00:00', at_pkt: '2026-11-06 04:00 PKT', uses_forecast: false,
  wind_source: 'w', paths: { '1000': path(0.5, -2.5), '925': path(1.8, -3.4), '850': path(-1.2, -4.6) },
  left_domain: {}, residence_hours: { '925': { 'Pakistan Punjab': 33, 'other Pakistan': 39, 'Indian Punjab': 0, Haryana: 0, elsewhere: 0 } },
  sectors: { '24': { n: 3, modal: 'NW', agreement: 0.67, by_level: {}, distance_km: {} } },
  fires: { strict: { n_points: 28, n_fires: 28, frp_mw: 300 }, loose: { n_fires: 2, frp_mw: 120, points: [
    { lat: 32.0, lon: 73.2, frp: 90, district: 'Hafizabad', country: 'PK', source_class: 'crop' },
    { lat: 32.2, lon: 72.8, frp: 30, district: 'Sargodha', country: 'PK', source_class: 'crop' } ] } },
  caveats: [],
}
const PK = { type: 'FeatureCollection', features: [{ type: 'Feature', geometry: { type: 'Polygon', coordinates: [[[70, 30], [75, 30], [75, 33], [70, 33], [70, 30]]] } }] }

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.includes('/trajectory?')) return { ok: true, status: 200, json: async () => DOC }
    if (url.endsWith('.geojson')) return { ok: true, status: 200, json: async () => PK }
    return { ok: false, status: 404, json: async () => ({ detail: 'nope' }) }
  }))
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('TrajectoryMiniMap', () => {
  it('fetches the document and draws three paths, the fires, the hour marks and the caption', async () => {
    const { container } = wrap(<TrajectoryMiniMap action={ACTION} />)
    await waitFor(() => expect(screen.getByTestId('trajectory-map')).toBeTruthy())
    const svg = container.querySelector('svg')!
    expect(svg.getAttribute('aria-label')).toBe('Where the air reaching Lahore had been')
    expect(svg.querySelectorAll('marker')).toHaveLength(3)
    expect(svg.querySelectorAll('path[marker-start]')).toHaveLength(3)             // backward: the arrow points into the origin
    expect(svg.querySelectorAll('circle[fill="#ea580c"]')).toHaveLength(2)           // the two fires along the path
    expect(screen.getByText('24 h')).toBeTruthy()
    expect(screen.getByText('72 h')).toBeTruthy()
    expect(screen.getByText('Lahore')).toBeTruthy()
    expect(container.textContent).toContain('33 h Pakistan Punjab, 39 h other Pakistan')
    expect(container.textContent).toContain('At 24 h the air was to the NW (2 of 3 levels agree)')
    expect(container.textContent).toContain('fires within 25 km of the path (2)')
    const calls = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.map(c => String(c[0]))
    expect(calls.find(u => u.includes('/trajectory?'))).toContain('lat=31.52&lon=74.36&at=2026-11-05T23%3A00%3A00&direction=backward&hours=72&label=Lahore')
  })

  it('shows the failure and a retry button when the engine is unavailable', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 422, json: async () => ({ detail: 'On-demand trajectories cover arrivals in the last 88 days' }) })))
    wrap(<TrajectoryMiniMap action={ACTION} />)
    await waitFor(() => expect(screen.getByText(/Map unavailable: On-demand trajectories/)).toBeTruthy())
    expect(screen.getByRole('button', { name: 'Retry' })).toBeTruthy()
  })

  it('is drawn inside a finished assistant message and never offered as a chip', async () => {
    const message = { id: 'm1', role: 'assistant' as const, content: 'The air came from the north-west.', actions: [ACTION, { type: 'zoom_to_city' as const, city: 'Lahore' }], status: 'ok' as const }
    wrap(<ChatMessage message={message} animate={false} canRunAction={() => true} onActionClick={() => {}} />)
    await waitFor(() => expect(screen.getByTestId('trajectory-map')).toBeTruthy())
    expect(screen.getByRole('button', { name: /Show Lahore/ })).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Where the air came from/ })).toBeNull()
  })
})
