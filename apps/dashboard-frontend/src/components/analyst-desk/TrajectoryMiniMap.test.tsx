import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TrajectoryMiniMap } from './TrajectoryMiniMap'
import { ChatMessage } from './ChatMessage'
import { ACTION, DOC, PK_OUTLINE } from '@/lib/chat/trajectoryFixture'

// jsdom has no WebGL, so these tests exercise the SVG renderer; TrajectoryMapGL.test.tsx covers the map

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

const svgOf = (container: HTMLElement) => container.querySelector('[data-testid="trajectory-map-svg"]') as SVGSVGElement

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.includes('/trajectory?')) return { ok: true, status: 200, json: async () => DOC }
    if (url.endsWith('.geojson')) return { ok: true, status: 200, json: async () => PK_OUTLINE }
    return { ok: false, status: 404, json: async () => ({ detail: 'nope' }) }
  }))
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('TrajectoryMiniMap', () => {
  it('fetches the document and draws three paths, the members, the fires, the hour marks and the caption', async () => {
    const { container } = wrap(<TrajectoryMiniMap action={ACTION} />)
    await waitFor(() => expect(screen.getByTestId('trajectory-map')).toBeTruthy())
    const svg = svgOf(container)
    expect(svg.getAttribute('aria-label')).toBe('Where the air reaching Lahore had been')
    expect(svg.querySelectorAll('marker')).toHaveLength(3)
    expect(svg.querySelectorAll('path[marker-start]')).toHaveLength(3)             // backward: the arrow points into the origin
    expect(svg.querySelectorAll('path.traj-member')).toHaveLength(6)               // two members per level, thin, under the paths
    expect(svg.querySelectorAll('circle[fill="#ea580c"]')).toHaveLength(2)           // the two fires along the path
    expect(screen.getByText('24 h')).toBeTruthy()
    expect(screen.getByText('72 h')).toBeTruthy()
    expect(screen.getByText('Lahore')).toBeTruthy()
    expect(container.textContent).toContain('· 6 members')
    expect(container.textContent).toContain('33 h Pakistan Punjab, 39 h other Pakistan')
    expect(container.textContent).toContain('At 24 h the air was to the NW (2 of 3 levels agree)')
    expect(container.textContent).toContain('At 24 h, 2 of 2 members (~700 m) were over Pakistan Punjab · spread 31 km.')
    expect(container.textContent).toContain('not a probability')
    expect(container.textContent).toContain('fires within 25 km (2)')
    // the caption is one line; the method sits behind a closed disclosure
    const details = container.querySelector('details') as HTMLDetailsElement
    expect(details.open).toBe(false)
    expect(details.textContent).toContain('How to read this map')
    expect(details.textContent).toContain('Kinematic trajectory on ECMWF IFS 0.25° winds. A plausibility screen')
    expect(details.textContent).not.toContain('position error')
    expect(details.textContent).toContain('33 h Pakistan Punjab, 39 h other Pakistan')
    const caption = details.parentElement as HTMLElement
    expect(caption.querySelector('p')?.textContent).toBe('At 24 h, 2 of 2 members (~700 m) were over Pakistan Punjab · spread 31 km.')
    const calls = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.map(c => String(c[0]))
    expect(calls.find(u => u.includes('/trajectory?'))).toContain('lat=31.52&lon=74.36&at=2026-11-05T23%3A00%3A00&direction=backward&hours=72&label=Lahore')
  })

  it('hides a level and its members when its toggle is pressed, and never hides the last one', async () => {
    const { container } = wrap(<TrajectoryMiniMap action={ACTION} />)
    await waitFor(() => expect(svgOf(container)).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: '~100 m' }))
    expect(screen.getByRole('button', { name: '~100 m' }).getAttribute('aria-pressed')).toBe('false')
    expect(svgOf(container).querySelectorAll('path[marker-start]')).toHaveLength(2)
    expect(svgOf(container).querySelectorAll('path.traj-member')).toHaveLength(4)
    fireEvent.click(screen.getByRole('button', { name: '~700 m' }))
    fireEvent.click(screen.getByRole('button', { name: '~1,400 m' }))                // the last level stays on
    expect(svgOf(container).querySelectorAll('path[marker-start]')).toHaveLength(1)
    expect(screen.getByRole('button', { name: '~1,400 m' }).getAttribute('aria-pressed')).toBe('true')
  })

  it('opens the expanded view when the map itself is clicked, with the method shown, closed by Escape', async () => {
    const { container } = wrap(<TrajectoryMiniMap action={ACTION} />)
    await waitFor(() => expect(svgOf(container)).toBeTruthy())
    expect(screen.getByText('Tap to expand')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Open the map' }))
    const dialog = screen.getByRole('dialog')
    expect(dialog.getAttribute('aria-label')).toBe('Where the air reaching Lahore had been')
    expect(dialog.querySelectorAll('[data-testid="trajectory-map-svg"]')).toHaveLength(1)
    expect((dialog.querySelector('details') as HTMLDetailsElement).open).toBe(true)
    expect(document.body.style.overflow).toBe('hidden')
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(document.body.style.overflow).toBe('')
  })

  it('also opens from the header icon and from the keyboard', async () => {
    const { container } = wrap(<TrajectoryMiniMap action={ACTION} />)
    await waitFor(() => expect(svgOf(container)).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: 'Expand the map' }))
    expect(screen.getByRole('dialog')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    fireEvent.keyDown(screen.getByRole('button', { name: 'Open the map' }), { key: 'Enter' })
    expect(screen.getByRole('dialog')).toBeTruthy()
  })

  it('shows the failure and a retry button when the engine is unavailable', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 422, json: async () => ({ detail: 'On-demand trajectories cover arrivals in the last 88 days' }) })))
    wrap(<TrajectoryMiniMap action={ACTION} />)
    await waitFor(() => expect(screen.getByText(/Map unavailable: On-demand trajectories/)).toBeTruthy())
    expect(screen.getByRole('button', { name: 'Retry' })).toBeTruthy()
  })

  it('still draws a document without an ensemble (older runs, HYSPLIT)', async () => {
    const plain = { ...DOC, ensemble: undefined }
    vi.stubGlobal('fetch', vi.fn(async (url: string) => ({ ok: true, status: 200, json: async () => (url.includes('/trajectory?') ? plain : PK_OUTLINE) })))
    const { container } = wrap(<TrajectoryMiniMap action={ACTION} />)
    await waitFor(() => expect(svgOf(container)).toBeTruthy())
    expect(svgOf(container).querySelectorAll('path.traj-member')).toHaveLength(0)
    expect(container.textContent).not.toContain('members')
  })

  it('is drawn inside a finished assistant message and never offered as a chip', async () => {
    const message = { id: 'm1', role: 'assistant' as const, content: 'The air came from the north-west.', actions: [ACTION, { type: 'zoom_to_city' as const, city: 'Lahore' }], status: 'ok' as const }
    wrap(<ChatMessage message={message} animate={false} canRunAction={() => true} onActionClick={() => {}} />)
    await waitFor(() => expect(screen.getByTestId('trajectory-map')).toBeTruthy())
    expect(screen.getByRole('button', { name: /Show Lahore/ })).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Where the air came from/ })).toBeNull()
  })
})
