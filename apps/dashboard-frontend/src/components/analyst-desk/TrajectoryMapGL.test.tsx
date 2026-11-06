import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ACTION, DOC } from '@/lib/chat/trajectoryFixture'

// A Mapbox GL stand-in that records what the hook asks of it, and a browser that says it can draw one

const maps: FakeMap[] = []

class FakeMap {
  handlers: Record<string, ((...a: unknown[]) => void)[]> = {}
  sources: Record<string, { data: GeoJSON.FeatureCollection; setData: (d: GeoJSON.FeatureCollection) => void }> = {}
  layers: string[] = []
  images = new Set<string>()
  filters: Record<string, unknown> = {}
  options: Record<string, unknown>
  removed = false
  resized = 0
  canvas = document.createElement('canvas')
  constructor(options: Record<string, unknown>) {
    this.options = options
    maps.push(this)
  }
  on(ev: string, a: unknown, b?: unknown) {
    const fn = (typeof a === 'function' ? a : b) as (...x: unknown[]) => void
    ;(this.handlers[ev] ??= []).push(fn)
  }
  once(ev: string, fn: (...a: unknown[]) => void) { this.on(ev, fn) }
  fire(ev: string, payload?: unknown) { for (const h of this.handlers[ev] ?? []) h(payload) }
  addControl() {}
  getCanvas() { return this.canvas }
  getStyle() { return { imports: [], layers: this.layers.map(id => ({ id })) } }
  setConfigProperty() {}
  getSource(id: string) { return this.sources[id] }
  addSource(id: string, spec: { data: GeoJSON.FeatureCollection }) {
    const src = { data: spec.data, setData: (d: GeoJSON.FeatureCollection) => { src.data = d } }
    this.sources[id] = src
  }
  getLayer(id: string) { return this.layers.includes(id) ? { id } : undefined }
  addLayer(layer: { id: string }) { this.layers.push(layer.id) }
  hasImage(id: string) { return this.images.has(id) }
  addImage(id: string) { this.images.add(id) }
  setFilter(id: string, f: unknown) { this.filters[id] = f }
  resize() { this.resized += 1 }
  remove() { this.removed = true }
}

vi.mock('mapbox-gl', () => ({
  default: {
    accessToken: '',
    Map: FakeMap,
    Popup: class { setLngLat() { return this } setHTML() { return this } addTo() { return this } remove() {} },
    NavigationControl: class {},
    ScaleControl: class {},
  },
}))
vi.mock('@/lib/webgl', () => ({ canRenderMap: () => true, MAP_UNAVAILABLE_TEXT: {} }))
vi.mock('@/components/ops-pipeline/mapViz', () => ({ useBasemapTuning: () => {}, ensureFlame: () => {} }))

// jsdom has no 2D canvas either: the arrow images come back empty, which is fine for the test
beforeEach(() => {
  maps.length = 0
  HTMLCanvasElement.prototype.getContext = (() => null) as unknown as HTMLCanvasElement['getContext']
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({ ok: url.includes('/trajectory?'), status: url.includes('/trajectory?') ? 200 : 404, json: async () => DOC })))
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

async function mount() {
  const { TrajectoryMiniMap } = await import('./TrajectoryMiniMap')
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const utils = render(<QueryClientProvider client={qc}><TrajectoryMiniMap action={ACTION} /></QueryClientProvider>)
  await waitFor(() => expect(maps).toHaveLength(1))
  return utils
}

describe('TrajectoryMapGL', () => {
  it('fits the map to the paths and draws members, paths, points, marks, arrows, fires and the origin once loaded', async () => {
    await mount()
    const map = maps[0]
    expect(screen.getByTestId('trajectory-map-gl').getAttribute('aria-label')).toBe('Where the air reaching Lahore had been')
    const [[w, s], [e, n]] = map.options.bounds as [[number, number], [number, number]]
    expect(w).toBeLessThan(70.2); expect(e).toBeGreaterThanOrEqual(74.36); expect(s).toBeLessThan(30.4); expect(n).toBeGreaterThan(33.5)
    expect(map.options.cooperativeGestures).toBe(true)
    expect(map.layers).toHaveLength(0)                                   // nothing before the style has loaded
    map.fire('load')
    await waitFor(() => expect(map.layers).toContain('traj-origin-label'))
    expect(map.sources['traj-members'].data.features).toHaveLength(6)
    expect(map.sources['traj-central'].data.features).toHaveLength(3)
    expect(map.sources['traj-points'].data.features).toHaveLength(36)    // 12 six-hourly points per level
    expect(map.sources['traj-marks'].data.features).toHaveLength(9)      // 24/48/72 h on every level, filtered to one
    expect(map.sources['traj-arrows'].data.features).toHaveLength(3)
    expect(map.sources['traj-fires'].data.features).toHaveLength(2)
    expect(map.sources['traj-origin'].data.features[0].properties?.label).toBe('Lahore')
    expect(map.layers.indexOf('traj-members-line')).toBeLessThan(map.layers.indexOf('traj-central-line'))
    expect(map.images.has('traj-arrow-925')).toBe(true)
    expect(map.filters['traj-members-line']).toEqual(['in', ['get', 'level'], ['literal', ['1000', '925', '850']]])
    expect(map.filters['traj-marks']).toEqual(['==', ['get', 'level'], '925'])
  })

  it('updates the level filter from the toggles and removes the map when the figure unmounts', async () => {
    const { unmount } = await mount()
    const map = maps[0]
    map.fire('load')
    await waitFor(() => expect(map.filters['traj-points']).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: '~700 m' }))
    await waitFor(() => expect(map.filters['traj-points']).toEqual(['in', ['get', 'level'], ['literal', ['1000', '850']]]))
    expect(map.filters['traj-marks']).toEqual(['==', ['get', 'level'], '1000'])
    unmount()
    expect(map.removed).toBe(true)
  })

  it('falls back to the SVG when the graphics context is lost', async () => {
    await mount()
    const map = maps[0]
    map.canvas.dispatchEvent(new Event('webglcontextlost', { cancelable: true }))
    await waitFor(() => expect(screen.getByTestId('trajectory-map-svg')).toBeTruthy())
    expect(map.removed).toBe(true)
  })
})
