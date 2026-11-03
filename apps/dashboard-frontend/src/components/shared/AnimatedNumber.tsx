'use client'

import { useEffect, useRef } from 'react'
import { animate, useReducedMotion } from 'motion/react'

/** Counts from the previous value to the new one. Shows the value instantly on first render and for reduced motion. */
export function AnimatedNumber({ value, className }: { value: number; className?: string }) {
  const ref = useRef<HTMLSpanElement>(null)
  const prev = useRef(value)
  const reduce = useReducedMotion()

  useEffect(() => {
    const el = ref.current
    if (!el) return
    if (reduce || prev.current === value) {
      el.textContent = String(value)
      prev.current = value
      return
    }
    const controls = animate(prev.current, value, {
      duration: 0.4,
      ease: [0.2, 0.8, 0.2, 1],
      onUpdate: v => { el.textContent = String(Math.round(v)) },
    })
    prev.current = value
    return () => controls.stop()
  }, [value, reduce])

  return <span ref={ref} className={className}>{value}</span>
}
