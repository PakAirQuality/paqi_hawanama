import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ReportsRedirect from './page'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('Reports page', () => {
  it('sends an old link on to the reports site', () => {
    const replace = vi.fn()
    vi.stubGlobal('location', { replace })
    render(<ReportsRedirect />)
    expect(replace).toHaveBeenCalledWith('https://reports.hawanama.org')
  })
})
