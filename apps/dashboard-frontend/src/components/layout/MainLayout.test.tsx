import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MainLayout } from './MainLayout'

vi.mock('next/navigation', () => ({ usePathname: () => '/stations' }))
vi.mock('@/components/layout/FreshnessBadge', () => ({ FreshnessBadge: () => null }))

afterEach(cleanup)

describe('MainLayout', () => {
  it('links Reports to the reports site, in its own tab', () => {
    render(<MainLayout><p>Page</p></MainLayout>)
    const link = screen.getByRole('link', { name: /^Reports/ })
    expect(link.getAttribute('href')).toBe('https://reports.hawanama.org')
    expect(link.getAttribute('target')).toBe('_blank')
    expect(link.getAttribute('rel')).toContain('noopener')
  })

  it('keeps the Tracker tab inside Hawanama', () => {
    render(<MainLayout><p>Page</p></MainLayout>)
    expect(screen.getByRole('link', { name: 'Tracker' }).getAttribute('target')).toBeNull()
  })

  it('has no Fires tab (fire trends live in the reports tool)', () => {
    render(<MainLayout><p>Page</p></MainLayout>)
    expect(screen.queryByRole('link', { name: 'Fires' })).toBeNull()
  })

  it('hides Stations and Data Quality from the header', () => {
    render(<MainLayout><p>Page</p></MainLayout>)
    expect(screen.queryByRole('link', { name: 'Stations' })).toBeNull()
    expect(screen.queryByRole('link', { name: 'Data Quality' })).toBeNull()
  })

  it('still renders a hidden page when it is opened directly', () => {
    render(<MainLayout><p>Page</p></MainLayout>)
    expect(screen.getByText('Page')).toBeTruthy()
  })
})
