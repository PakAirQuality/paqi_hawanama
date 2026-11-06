import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ACTION, DOC, PK_OUTLINE } from '@/lib/chat/trajectoryFixture'

// A Mapbox GL stand-in that records what the hook asks of it, and a browser that says it can draw one

const maps: FakeMap[] = []

class FakeMap {
  handlers: Record<string, ((...a: unknown[]) => void)[]> = {}
  sources: Record<string, { data: GeoJSON.FeatureCollection; setData: (d: GeoJSON.FeatureCollection) => void }> = {}
  layers: string[] = []
  layerSpecs: Record<string, Record<string, unknown>> = {}
  images = new Set<string>()
  filters: Record<string, unknown> = {}
  config: Record<string, unknown> = {}
  controls: string[] = []
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
  addControl(c: object) { this.controls.push(c.constructor.name) }
  getCanvas() { return this.canvas }
  getStyle() { return { imports: [{ id: 'basemap' }], layers: this.layers.map(id => ({ id })) } }
  setConfigProperty(_: string, key: string, value: unknown) { this.config[key] = value }
  getSource(id: string) { return this.sources[id] }
  addSource(id: string, spec: { data: GeoJSON.FeatureCollection }) {
    const src = { data: spec.data, setData: (d: GeoJSON.FeatureCollection) => { src.data = d } }
    this.sources[id] = src
  }
  getLayer(id: string) { return this.layers.includes(id) ? { id } : undefined }
  addLayer(layer: { id: string }) { this.layers.push(layer.id); this.layerSpecs[layer.id] = layer as unknown as Record<string, unknown> }
  hasImage(id: string) { return this.images.has(id) }
  addImage(id: string) { this.images.add(id) }
  setFilter(id: string, f: unknown) { this.filters[id] = f }
  getFilter(id: string) { return this.filters[id] ?? (this.layerSpecs[id] as { filter?: unknown } | undefined)?.filter }
  resize() { this.resized += 1 }
  remove() { this.removed = true }
}

vi.mock('mapbox-gl', () => ({
  default: {
    accessToken: '',
    Map: FakeMap,
    Popup: class { setLngLat() { return this } setHTML() { return this } addTo() { return this } remove() {} },
    NavigationControl: class NavigationControl {},
    ScaleControl: class ScaleControl {},
    AttributionControl: class AttributionControl {},
  },
}))
vi.mock('@/lib/webgl', () => ({ canRenderMap: () => true, MAP_UNAVAILABLE_TEXT: {} }))
// the real basemap tuning runs against the fake map (its config calls are asserted); the flame icon needs a 2D canvas
vi.mock('@/components/ops-pipeline/mapViz', async (importOriginal) => ({ ...(await importOriginal<object>()), ensureFlame: () => {} }))

// jsdom has no 2D canvas either: the arrow images come back empty, which is fine for the test
beforeEach(() => {
  maps.length = 0
  HTMLCanvasElement.prototype.getContext = (() => null) as unknown as HTMLCanvasElement['getContext']
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.includes('/trajectory?')) return { ok: true, status: 200, json: async () => DOC }
    if (url.endsWith('.geojson')) return { ok: true, status: 200, json: async () => PK_OUTLINE }
    return { ok: false, status: 404, json: async () => ({}) }
  }))
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
    // the preview is fitted to the origin and the central paths; the members (±0.25° wider) may run off its edge
    expect(w).toBeLessThan(70.2); expect(e).toBeGreaterThanOrEqual(74.36); expect(s).toBeLessThan(30.4); expect(n).toBeGreaterThan(33.3); expect(n).toBeLessThan(33.5)
    // the picture in the chat is a preview: nothing to drag or zoom, room for the origin label on the right
    expect(map.options.interactive).toBe(false)
    expect(map.options.cooperativeGestures).toBe(false)
    expect((map.options.fitBoundsOptions as { padding: { right: number } }).padding.right).toBeGreaterThan(50)
    expect(map.controls).toEqual(['AttributionControl', 'ScaleControl'])
    expect(map.layers).toHaveLength(0)                                   // nothing before the style has loaded
    map.fire('load')
    await waitFor(() => expect(map.layers).toContain('traj-origin-label'))
    // a faded (not monochrome) basemap with its own place names, so the small map is not a blank sheet
    expect(map.config).toMatchObject({ theme: 'faded', showPlaceLabels: false, showRoadLabels: false, showPointOfInterestLabels: false })
    expect(map.filters['hawa-cities']).toEqual(['all', ['<=', ['get', 'rank'], ['step', ['zoom'], 1, 4.5, 2]], ['!=', ['get', 'name'], 'Lahore']])
    expect(map.layers).toContain('hawa-cities')
    expect((map.layerSpecs['traj-origin-label'].layout as Record<string, unknown>)['text-variable-anchor']).toEqual(['left', 'right', 'top', 'bottom'])
    expect(map.handlers['mouseenter']).toBeUndefined()                   // no hover popups on the preview
    // the province outlines (the SVG's files) are drawn under the paths, since the basemap shows none at this zoom
    await waitFor(() => expect(map.layers).toContain('traj-adm1-line'))
    expect(map.sources['traj-adm1'].data.features).toHaveLength(2 * PK_OUTLINE.features.length)
    expect(map.layers.indexOf('traj-adm1-line')).toBeGreaterThan(map.layers.indexOf('traj-members-line'))   // added later, but in the 'middle' slot: under the paths
    expect((map.layerSpecs['traj-adm1-line'] as { slot?: string }).slot).toBe('middle')
    expect((map.layerSpecs['traj-members-line'] as { slot?: string }).slot).toBe('top')
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

  it('mounts the map once the figure is on screen, even though the document arrives after the loading skeleton', async () => {
    // a browser with IntersectionObserver: the observer must attach to the figure, which only exists once the document is in
    const observed: Element[] = []
    class FakeIO {
      cb: (entries: { isIntersecting: boolean }[]) => void
      constructor(cb: (entries: { isIntersecting: boolean }[]) => void) { this.cb = cb }
      observe(el: Element) { observed.push(el); this.cb([{ isIntersecting: true }]) }
      disconnect() {}
    }
    vi.stubGlobal('IntersectionObserver', FakeIO)
    await mount()
    expect(observed).toHaveLength(1)
    expect(observed[0].getAttribute('data-testid')).toBe('trajectory-map')
    expect(screen.getByTestId('trajectory-map-gl')).toBeTruthy()
  })

  it('opens the expanded view on a click, with a second, fully interactive map', async () => {
    await mount()
    fireEvent.click(screen.getByRole('button', { name: 'Open the map' }))
    await waitFor(() => expect(maps).toHaveLength(2))
    const [small, big] = maps
    expect(small.removed).toBe(true)                                     // the preview gives up its WebGL context
    expect(big.options.interactive).toBe(true)
    expect(big.options.cooperativeGestures).toBe(true)
    expect(big.options.fitBoundsOptions).toEqual({ padding: 60 })
    expect((big.options.bounds as number[][])[1][1]).toBeGreaterThan(33.5)      // the expanded view holds every member
    big.fire('load')
    await waitFor(() => expect(big.config).toMatchObject({ theme: 'faded', showPlaceLabels: true }))
    expect(big.controls).toEqual(['AttributionControl', 'NavigationControl', 'ScaleControl'])
    big.fire('load')
    await waitFor(() => expect(big.layers).toContain('traj-origin-label'))
    expect(big.handlers['mouseenter']).toHaveLength(2)                   // popups on the points and the fires
    expect(screen.getByRole('dialog').querySelector('[data-testid="trajectory-map-gl"]')).toBeTruthy()
  })

  it('falls back to the SVG when the graphics context is lost', async () => {
    await mount()
    const map = maps[0]
    map.canvas.dispatchEvent(new Event('webglcontextlost', { cancelable: true }))
    await waitFor(() => expect(screen.getByTestId('trajectory-map-svg')).toBeTruthy())
    expect(map.removed).toBe(true)
  })
})
