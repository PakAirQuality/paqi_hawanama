import { describe, expect, it } from 'vitest'
import { dedupDetections, type DetectionLike } from './fireDedup'

const det = (lon: number, lat: number, sat: string, time: string, frp: number, confidence = 'n'): DetectionLike => ({
  geometry: { coordinates: [lon, lat] },
  properties: { satellite: sat, acq_datetime_utc: time, frp, confidence },
})

describe('dedupDetections (fire report §5.1)', () => {
  it('merges two satellites seeing one field within 1 km and 90 minutes, keeping the stronger', () => {
    const a = det(74.0, 31.0, 'N20', '2026-11-05T08:00:00Z', 3)
    const b = det(74.004, 31.002, 'N21', '2026-11-05T08:50:00Z', 7)
    const r = dedupDetections([a, b])
    expect(r.detections).toBe(2)
    expect(r.fires).toHaveLength(1)
    expect(r.fires[0]).toBe(b)
    expect(r.groups[0].size).toBe(2)
  })

  it('never merges pixels of the same satellite', () => {
    const r = dedupDetections([det(74.0, 31.0, 'N20', '2026-11-05T08:00:00Z', 3), det(74.001, 31.0, 'N20', '2026-11-05T08:00:00Z', 4)])
    expect(r.fires).toHaveLength(2)
  })

  it('keeps passes more than 90 minutes apart or more than 1 km apart separate', () => {
    const late = dedupDetections([det(74.0, 31.0, 'N20', '2026-11-05T08:00:00Z', 3), det(74.0, 31.0, 'N21', '2026-11-05T09:31:00Z', 3)])
    expect(late.fires).toHaveLength(2)
    const far = dedupDetections([det(74.0, 31.0, 'N20', '2026-11-05T08:00:00Z', 3), det(74.02, 31.0, 'N21', '2026-11-05T08:10:00Z', 3)])
    expect(far.fires).toHaveLength(2)
  })

  it('is transitive: a pixel between two others joins all three', () => {
    const r = dedupDetections([
      det(74.0, 31.0, 'N20', '2026-11-05T08:00:00Z', 1),
      det(74.008, 31.0, 'N21', '2026-11-05T08:30:00Z', 1),
      det(74.016, 31.0, 'N20', '2026-11-05T08:00:00Z', 1),
    ])
    expect(r.groups).toHaveLength(1)
  })

  it('counts a group as a fire when any member is high or nominal; low-only groups are not fires', () => {
    const low = dedupDetections([det(74.0, 31.0, 'N20', '2026-11-05T08:00:00Z', 3, 'l')])
    expect(low.fires).toHaveLength(0)
    expect(low.groups).toHaveLength(1)
    const mixed = dedupDetections([det(74.0, 31.0, 'N20', '2026-11-05T08:00:00Z', 9, 'l'), det(74.0, 31.0, 'N21', '2026-11-05T08:20:00Z', 1, 'h')])
    expect(mixed.fires).toHaveLength(1)
    expect(mixed.fires[0].properties?.frp).toBe(9) // the primary is the strongest member, whatever its confidence
  })
})
