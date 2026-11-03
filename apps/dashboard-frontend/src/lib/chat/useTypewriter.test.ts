import { describe, expect, it } from 'vitest'
import { nextReveal, wordEnd } from './useTypewriter'

const FRAME = 16

function secondsToFinish(length: number) {
  let cursor = 0
  let frames = 0
  while (cursor < length && frames < 100_000) {
    const next = nextReveal(length, cursor, FRAME)
    expect(next).toBeGreaterThan(cursor)
    cursor = next
    frames++
  }
  return (frames * FRAME) / 1000
}

describe('nextReveal', () => {
  it('finishes exactly at the end', () => {
    expect(nextReveal(5, 5, FRAME)).toBe(5)
    expect(nextReveal(5, 9, FRAME)).toBe(5)
    expect(nextReveal(0, 0, FRAME)).toBe(0)
    expect(nextReveal(5, 4.9, 1000)).toBe(5)
  })

  it('always moves forward, even on a very short frame', () => {
    expect(nextReveal(100, 0, 0)).toBeGreaterThan(0)
  })

  it('takes a readable time over a typical answer', () => {
    const seconds = secondsToFinish(400)
    expect(seconds).toBeGreaterThan(3)
    expect(seconds).toBeLessThan(5)
  })

  it('keeps a very long answer from taking too long', () => {
    expect(secondsToFinish(5000)).toBeLessThan(5)
  })

  it('does not drag out a short answer', () => {
    expect(secondsToFinish(40)).toBeLessThan(1)
  })
})

describe('wordEnd', () => {
  it('finishes the word it is in', () => {
    expect(wordEnd('Calm winds', 2)).toBe(4)
    expect('Calm winds trapped'.slice(0, wordEnd('Calm winds trapped', 6))).toBe('Calm winds')
  })

  it('does not stall on one very long word', () => {
    expect(wordEnd('x'.repeat(500), 100)).toBe(100)
  })

  it('never runs past the end', () => {
    expect(wordEnd('Calm', 2)).toBe(2)
  })
})
