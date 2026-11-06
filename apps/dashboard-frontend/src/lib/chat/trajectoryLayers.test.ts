import { describe, expect, it, vi } from 'vitest'
import { DOC } from './trajectoryFixture'

vi.mock('mapbox-gl', () => ({ default: { Popup: class {} } }))
vi.mock('@/components/ops-pipeline/mapViz', () => ({ ensureFlame: () => {} }))

const { bearingDeg, trajectoryGeo } = await import('./trajectoryLayers')

describe('bearingDeg', () => {
  it('points north, east and north-west', () => {
    expect(bearingDeg({ lon: 74, lat: 31 }, { lon: 74, lat: 32 })).toBeCloseTo(0, 5)
    expect(bearingDeg({ lon: 74, lat: 31 }, { lon: 75, lat: 31 })).toBeCloseTo(90, 0)
    const nw = bearingDeg({ lon: 74, lat: 31 }, { lon: 73, lat: 32 })
    expect(nw).toBeGreaterThan(315); expect(nw).toBeLessThan(325)
  })
})

describe('trajectoryGeo', () => {
  const geo = trajectoryGeo(DOC)

  it('turns members and central paths into lines carrying their level and colour', () => {
    expect(geo.members.features).toHaveLength(6)
    expect(geo.members.features[0].properties).toEqual({ level: '1000', colour: '#1d4ed8' })
    expect(geo.central.features.map(f => f.properties?.level)).toEqual(['1000', '925', '850'])
    expect((geo.central.features[1].geometry as GeoJSON.LineString).coordinates).toHaveLength(73)
  })

  it('places a 6-hourly point with the hover text, marks at 24/48/72 h and an arrow into the origin for a backward run', () => {
    const pts = geo.points.features.filter(f => f.properties?.level === '925')
    expect(pts.map(f => f.properties?.age_h)).toEqual([6, 12, 18, 24, 30, 36, 42, 48, 54, 60, 66, 72])
    const p24 = pts.find(f => f.properties?.age_h === 24)!
    expect(p24.properties).toMatchObject({ height: '~700 m', region: 'Pakistan Punjab', district: 'Sheikhupura', members: '2 Pakistan Punjab' })
    expect(String(p24.properties?.when)).toMatch(/PKT$/)
    expect(geo.marks.features.map(f => f.properties?.label)).toEqual(['24 h', '48 h', '72 h', '24 h', '48 h', '72 h', '24 h', '48 h', '72 h'])
    const arrow = geo.arrows.features.find(f => f.properties?.level === '925')!
    expect((arrow.geometry as GeoJSON.Point).coordinates).toEqual([74.36, 31.52])         // at the origin
    expect(arrow.properties?.bearing).toBeGreaterThan(100); expect(arrow.properties?.bearing).toBeLessThan(140)   // the air moves south-east into Lahore
  })

  it('puts the arrow at the far end for a forward run and carries the fires and the origin', () => {
    const fwd = trajectoryGeo({ ...DOC, direction: 'forward' })
    const arrow = fwd.arrows.features.find(f => f.properties?.level === '925')!
    const end = DOC.paths['925'][72]
    expect((arrow.geometry as GeoJSON.Point).coordinates).toEqual([end.lon, end.lat])
    expect(geo.fires.features.map(f => f.properties?.district)).toEqual(['Hafizabad', 'Sargodha'])
    expect(geo.fires.features[0].properties?.country).toBe('Pakistan')
    expect(geo.origin.features[0].properties?.label).toBe('Lahore')
  })

  it('copes with a document without an ensemble', () => {
    const plain = { ...DOC, ensemble: undefined }
    expect(trajectoryGeo(plain).members.features).toHaveLength(0)
  })
})
