import { describe, expect, it } from 'vitest'
import { fitProjection, outlinePath, scaleBarKm, toPath } from './trajectoryMap'

const pts = [{ lon: 74.36, lat: 31.52 }, { lon: 71.9, lat: 32.1 }, { lon: 70.9, lat: 30.3 }]

describe('fitProjection', () => {
  it('keeps every point inside the padded view and the centre in the middle', () => {
    const proj = fitProjection(pts, 320, 220, 20)
    for (const p of pts) {
      const { x, y } = proj.project(p)
      expect(x).toBeGreaterThanOrEqual(19.5)
      expect(x).toBeLessThanOrEqual(300.5)
      expect(y).toBeGreaterThanOrEqual(19.5)
      expect(y).toBeLessThanOrEqual(200.5)
    }
    const c = proj.project(proj.centre)
    expect(c.x).toBeCloseTo(160)
    expect(c.y).toBeCloseTo(110)
  })

  it('is true to scale: one degree east is shorter than one degree north at 31°N', () => {
    const proj = fitProjection(pts, 320, 220)
    const o = proj.project({ lon: 72, lat: 31 })
    const east = proj.project({ lon: 73, lat: 31 })
    const north = proj.project({ lon: 72, lat: 32 })
    expect((east.x - o.x) / (o.y - north.y)).toBeCloseTo(Math.cos((proj.centre.lat * Math.PI) / 180), 2)
  })

  it('never zooms into a single point', () => {
    const proj = fitProjection([{ lon: 74.36, lat: 31.52 }], 320, 220)
    expect(proj.kmToUnits(100)).toBeLessThan(200)
    expect(scaleBarKm(proj)).toBeGreaterThanOrEqual(20)
  })
})

describe('paths', () => {
  it('writes a polyline and closed outlines', () => {
    const proj = fitProjection(pts, 320, 220)
    expect(toPath(pts, proj)).toMatch(/^M[\d.]+ [\d.]+ L[\d.]+ [\d.]+ L[\d.]+ [\d.]+$/)
    const fc = { type: 'FeatureCollection' as const, features: [
      { type: 'Feature' as const, geometry: { type: 'Polygon', coordinates: [[[71, 31], [72, 31], [72, 32], [71, 31]]] } },
      { type: 'Feature' as const, geometry: { type: 'MultiPolygon', coordinates: [[[[73, 31], [74, 31], [74, 32], [73, 31]]]] } },
    ] }
    const d = outlinePath(fc, proj)
    expect(d.split('Z').filter(Boolean)).toHaveLength(2)
    expect(outlinePath(undefined, proj)).toBe('')
  })
})

describe('document helpers', () => {
  it('reads the member paths, the bounds of everything and the ensemble sentence', async () => {
    const { DOC } = await import('./trajectoryFixture')
    const { allPoints, boundsOf, ensembleLine, levelOrder, memberPaths } = await import('./trajectoryMap')
    const members = memberPaths(DOC)
    expect(Object.keys(members).sort()).toEqual(['1000', '850', '925'])
    expect(levelOrder(members)).toEqual(['1000', '925', '850'])
    expect(members['925']).toHaveLength(2)
    expect(members['925'][0][0]).toEqual({ lon: 74.36, lat: 31.77 })
    const [[w, s], [e, n]] = boundsOf(allPoints(DOC))
    expect(w).toBeCloseTo(74.36 - 4.6, 2); expect(e).toBeCloseTo(74.36, 2)
    expect(s).toBeCloseTo(31.52 - 1.2 - 0.25, 2); expect(n).toBeCloseTo(31.52 + 1.8 + 0.25, 2)
    expect(boundsOf([{ lon: 74, lat: 31 }])).toEqual([[73.25, 30.25], [74.75, 31.75]])
    expect(ensembleLine(DOC)).toBe('At 24 h, 2 of 2 members (~700 m) were over Pakistan Punjab · spread 31 km.')
    expect(ensembleLine(DOC, '1000')).toBe('At 24 h, 1 of 2 members (~100 m) were over Pakistan Punjab, 1 over Indian Punjab · spread 44 km.')
    expect(ensembleLine({ ...DOC, direction: 'forward' }, '850')).toMatch(/^At 24 h, \d of 2 members \(~\d+ m\) will be over/)   // no 850 regions in the fixture: the first level with any
    expect(ensembleLine({ ...DOC, ensemble: undefined })).toBe('')
  })
})
