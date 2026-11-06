// A small trajectory document for tests: three central paths, two ensemble members per level,
// two fires along the way. Shaped like the API's GET /api/v1/fires/trajectory response.

import type { TrajectoryDoc } from '@/components/fires/api'

export const ACTION = { type: 'show_trajectory' as const, lat: 31.52, lon: 74.36, at: '2026-11-05T23:00:00', direction: 'backward' as const, hours: 72, label: 'Lahore' }

const point = (age: number, lat: number, lon: number, region: string) => ({
  age_h: age, time_utc: `2026-11-0${age <= -24 ? 3 : 5}T06:00:00`, lat, lon, height_agl_m: 700, z_msl_m: 800, speed_ms: 4, region, district: age === -24 ? 'Sheikhupura' : null,
})
const path = (dlat: number, dlon: number) => Array.from({ length: 73 }, (_, i) => point(-i, 31.52 + (dlat * i) / 72, 74.36 + (dlon * i) / 72, i < 30 ? 'Pakistan Punjab' : 'other Pakistan'))
const member = (dlat: number, dlon: number, off: number): [number, number][] => Array.from({ length: 73 }, (_, i) => [31.52 + off + (dlat * i) / 72, 74.36 + (dlon * i) / 72])

export const DOC: TrajectoryDoc = {
  engine: 'kinematic_ecmwf_ifs025', status: 'kinematic', direction: 'backward', hours: 72, levels_hpa: [1000, 925, 850],
  origin: { lat: 31.52, lon: 74.36, label: 'Lahore' }, at_utc: '2026-11-05T23:00:00', at_pkt: '2026-11-06 04:00 PKT', uses_forecast: false,
  wind_source: 'w', paths: { '1000': path(0.5, -2.5), '925': path(1.8, -3.4), '850': path(-1.2, -4.6) },
  left_domain: {}, residence_hours: { '925': { 'Pakistan Punjab': 33, 'other Pakistan': 39, 'Indian Punjab': 0, Haryana: 0, elsewhere: 0 } },
  sectors: { '24': { n: 3, modal: 'NW', agreement: 0.67, by_level: {}, distance_km: {} } },
  ensemble: {
    n_members: { '1000': 2, '925': 2, '850': 2 }, offsets: { horizontal_deg: 0.25, vertical_hpa: 25 },
    members: { '1000': [member(0.5, -2.5, 0.25), member(0.5, -2.5, -0.25)], '925': [member(1.8, -3.4, 0.25), member(1.8, -3.4, -0.25)], '850': [member(-1.2, -4.6, 0.25), member(-1.2, -4.6, -0.25)] },
    sectors: { '24': { '925': { n: 2, modal: 'NW', agreement: 1, counts: { NW: 2 } }, all: { n: 6, modal: 'NW', agreement: 0.83, counts: { NW: 5, W: 1 } } } },
    regions_at: { '24': { '925': { 'Pakistan Punjab': 2 }, '1000': { 'Pakistan Punjab': 1, 'Indian Punjab': 1 } } },
    spread_km: { '24': { '925': 31, '1000': 44 } },
    left_domain: { '1000': 0, '925': 0, '850': 0 },
  },
  fires: { strict: { n_points: 28, n_fires: 28, frp_mw: 300 }, loose: { n_fires: 2, frp_mw: 120, points: [
    { lat: 32.0, lon: 73.2, frp: 90, district: 'Hafizabad', country: 'PK', source_class: 'crop' },
    { lat: 32.2, lon: 72.8, frp: 30, district: 'Sargodha', country: 'PK', source_class: 'crop' } ] } },
  caveats: [],
}

export const PK_OUTLINE = { type: 'FeatureCollection', features: [{ type: 'Feature', geometry: { type: 'Polygon', coordinates: [[[70, 30], [75, 30], [75, 33], [70, 33], [70, 30]]] } }] }
