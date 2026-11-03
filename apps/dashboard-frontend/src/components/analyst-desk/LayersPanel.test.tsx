import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { LayersPanel } from './LayersPanel'

afterEach(cleanup)

const sources = [
  { key: 'kilns', label: 'Brick Kilns', color: '#d97706', on: false },
  { key: 'power_plants', label: 'Power Plants', color: '#ef4444', on: true },
  { key: 'sugar_mills', label: 'Sugar Mills', color: '#10b981', on: false },
]

const props = () => ({
  showStations: true, onToggleStations: vi.fn(),
  showSatellite: true, onToggleSatellite: vi.fn(),
  showFires: false, onToggleFires: vi.fn(),
  showWind: false, onToggleWind: vi.fn(),
  showPopulation: false, onTogglePopulation: vi.fn(),
  sources, onToggleSource: vi.fn(),
})

describe('LayersPanel', () => {
  it('lists every emission source with its own switch', () => {
    render(<LayersPanel {...props()} />)
    for (const label of ['Brick Kilns', 'Power Plants', 'Sugar Mills']) expect(screen.getByRole('button', { name: label })).toBeTruthy()
  })

  it('switches only the source that was tapped', () => {
    const p = props()
    render(<LayersPanel {...p} />)
    fireEvent.click(screen.getByRole('button', { name: 'Sugar Mills' }))
    expect(p.onToggleSource).toHaveBeenCalledExactlyOnceWith('sugar_mills')
    expect(p.onToggleFires).not.toHaveBeenCalled()
  })

  it('shows which sources are on', () => {
    render(<LayersPanel {...props()} />)
    expect(screen.getByRole('button', { name: 'Power Plants' }).getAttribute('aria-pressed')).toBe('true')
    expect(screen.getByRole('button', { name: 'Brick Kilns' }).getAttribute('aria-pressed')).toBe('false')
  })
})
