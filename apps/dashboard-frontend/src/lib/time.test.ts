import { describe, expect, it } from 'vitest'
import { updatedAgo, formatPkt, formatPktShort, hourLabel } from './time'

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

describe('12-hour Pakistan times', () => {
  it('formats a night pass with am, not as a bare 01:21', () => {
    expect(formatPkt('2026-11-05T20:21:00Z')).toBe('6 Nov 2026, 1:21 am PKT')
    expect(formatPkt('2026-11-06T09:00:00Z')).toBe('6 Nov 2026, 2:00 pm PKT')
  })
  it('gives a short weekday label for the timeline', () => {
    expect(formatPktShort('2026-11-06T09:00:00Z')).toBe('Fri 2:00 pm')
  })
  it('names hours of the day', () => {
    expect(hourLabel(0)).toBe('12 am')
    expect(hourLabel('09')).toBe('9 am')
    expect(hourLabel(12)).toBe('12 pm')
    expect(hourLabel(23)).toBe('11 pm')
  })
})
