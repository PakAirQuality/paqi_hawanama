'use client'

// Reveals an answer as if it were being written. The API delivers a reply in a burst after a long
// silence (under a second for the whole text), so showing chunks as they land reads as a sudden
// block. Revealing at a reading pace works however the text arrives.

import { useEffect, useRef, useState } from 'react'

const CHARS_PER_SECOND = 90
const MAX_SECONDS = 4 // a long answer speeds up so nobody waits long for it to finish
const MIN_STEP = 0.25
const MAX_WORD_CHARS = 14

/** Where the reveal has got to after `elapsedMs`. Fractional, so slow frames still add up. */
export function nextReveal(length: number, cursor: number, elapsedMs: number): number {
  if (cursor >= length) return length
  const speed = Math.max(CHARS_PER_SECOND, length / MAX_SECONDS)
  return Math.min(length, cursor + Math.max(MIN_STEP, (speed * elapsedMs) / 1000))
}

/** Extends a position to the end of its word, so words appear whole. */
export function wordEnd(text: string, position: number): number {
  const at = Math.floor(position)
  const space = text.slice(at, at + MAX_WORD_CHARS).search(/\s/)
  return space >= 0 ? at + space : at
}

const prefersReducedMotion = () =>
  typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

export function useTypewriter(text: string, enabled: boolean): { text: string; typing: boolean } {
  const [reduced] = useState(prefersReducedMotion)
  const active = enabled && !reduced
  const [cursor, setCursor] = useState(0)
  const cursorRef = useRef(0)

  useEffect(() => {
    if (!active) return
    cursorRef.current = Math.min(cursorRef.current, text.length)
    setCursor(cursorRef.current)
    if (cursorRef.current >= text.length) return

    let last = performance.now()
    let frame = requestAnimationFrame(function tick(now) {
      const next = nextReveal(text.length, cursorRef.current, now - last)
      last = now
      cursorRef.current = next
      setCursor(next)
      if (next < text.length) frame = requestAnimationFrame(tick)
    })
    return () => cancelAnimationFrame(frame)
  }, [active, text])

  if (!active) return { text, typing: false }
  return { text: text.slice(0, wordEnd(text, cursor)), typing: cursor < text.length }
}
