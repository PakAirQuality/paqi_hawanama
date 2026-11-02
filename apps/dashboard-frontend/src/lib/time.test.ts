import { describe, expect, it } from 'vitest'
import { updatedAgo } from './time'

const now = new Date('2026-11-01T12:00:00Z')
const minutesAgo = (m: number) => new Date(now.getTime() - m * 60_000).toISOString()

describe('updatedAgo', () => {
  it.each([
    [0, 'Updated just now'],
    [1, 'Updated 1 min ago'],
    [15, 'Updated 15 mins ago'],
    [59, 'Updated 59 mins ago'],
    [60, 'Updated 1 hour ago'],
    [150, 'Updated 3 hours ago'],
    [47 * 60, 'Updated 47 hours ago'],
    [72 * 60, 'Updated 3 days ago'],
  ])('%i minutes old reads "%s"', (minutes, expected) => {
    expect(updatedAgo(minutesAgo(minutes), now)).toBe(expected)
  })

  it('treats a timestamp slightly in the future as current', () => {
    expect(updatedAgo(minutesAgo(-37), now)).toBe('Updated just now')
  })

  it('copes with a missing time', () => {
    expect(updatedAgo(null, now)).toBe('Updated recently')
  })
})
