import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MarkdownContent } from './MarkdownContent'

afterEach(cleanup)

describe('MarkdownContent', () => {
  it('renders headings, lists and tables as real elements', () => {
    const { container } = render(<MarkdownContent text={'### Cities\n\n- Lahore\n- Kasur\n\n| City | PM2.5 |\n|---|---|\n| Lahore | 221 |'} />)
    expect(screen.getByRole('heading', { name: 'Cities' })).toBeTruthy()
    expect(container.querySelectorAll('li')).toHaveLength(2)
    expect(screen.getByRole('columnheader', { name: 'PM2.5' })).toBeTruthy()
    expect(screen.getByRole('cell', { name: '221' })).toBeTruthy()
    expect(container.textContent).not.toMatch(/###|\|/)
  })

  it('shows HTML from an answer as text and never runs it', () => {
    const payload = '<img src=x onerror=alert(1)><script>alert(1)</script>'
    const { container } = render(<MarkdownContent text={payload} />)
    expect(container.querySelector('img, script')).toBeNull()
    expect(container.textContent).toContain('<script>')
  })

  it('opens safe links in a new tab without handing over the page', () => {
    render(<MarkdownContent text="[source](https://hawanama.org/about)" />)
    const link = screen.getByRole('link', { name: 'source' })
    expect(link.getAttribute('href')).toBe('https://hawanama.org/about')
    expect(link.getAttribute('target')).toBe('_blank')
    expect(link.getAttribute('rel')).toContain('noopener')
  })

  it('renders no link for a dangerous address', () => {
    render(<MarkdownContent text="[click me](javascript:alert(1))" />)
    expect(screen.queryByRole('link')).toBeNull()
  })

  it('makes known cities clickable and leaves other bold text alone', () => {
    const onCityClick = vi.fn()
    render(<MarkdownContent text="**Lahore** and **Hazardous**" knownCities={new Set(['Lahore'])} onCityClick={onCityClick} />)
    fireEvent.click(screen.getByRole('button', { name: 'Lahore' }))
    expect(onCityClick).toHaveBeenCalledWith('Lahore')
    expect(screen.queryByRole('button', { name: 'Hazardous' })).toBeNull()
  })
})
