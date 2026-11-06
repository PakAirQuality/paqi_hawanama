'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { fetchPredictionData } from './api'
import type { ModelKey } from '@/lib/selection'
import type { PredictionData } from './types'
import { cachedGridImage, estimateKey, predictionRaster, renderGridImage, type GridImage } from '@/lib/mapviz/gridImage'
import { SURFACE_RANGE } from '@/lib/turbo'
import { loadCountryPolygons } from './mapViz'

/** How many finished days the replay covers, and how long the playhead takes to cross one day. */
export const REPLAY_DAYS = 14
const MS_PER_DAY = 900
/** After the last day, how long the replay holds before handing back to today. */
const END_HOLD_MS = 700

/**
 * The replay's playhead, as a number of days from the first frame (0 to frames − 1, fractional while moving).
 * It changes every animation frame, so it lives outside React state: the map blend and the scrubber subscribe
 * to it directly, and the rest of the page only hears about whole-day changes.
 */
export interface ReplayClock {
  get(): number
  set(t: number): void
  subscribe(fn: () => void): () => void
}

function createClock(): ReplayClock {
  let t = 0
  const listeners = new Set<() => void>()
  return {
    get: () => t,
    set: (v) => { t = v; listeners.forEach(f => f()) },
    subscribe: (fn) => { listeners.add(fn); return () => { listeners.delete(fn) } },
  }
}

export type ReplayStatus = 'idle' | 'loading' | 'playing' | 'paused' | 'ending'

/**
 * Replays the PM2.5 estimate over the last REPLAY_DAYS finished days, like the precipitation map of a phone
 * weather app: the playhead moves continuously and the map blends from one day into the next in proportion,
 * with a scrubber to pause and drag. Every day's data is fetched and every day's image painted before it starts,
 * so nothing waits on the network or the painter while it plays. Only the estimate animates (no station readings):
 * onFrame reports the nearest whole day (for the map key's date), and onEnd fires when it finishes.
 */
export function useDayPlayback(opts: { dates: string[]; model: ModelKey; onFrame: (date: string) => void; onEnd: () => void }) {
  const { dates, model } = opts
  const qc = useQueryClient()
  const clock = useMemo(() => createClock(), [])
  const [status, setStatus] = useState<ReplayStatus>('idle')
  const [frames, setFrames] = useState<string[]>([])
  const [images, setImages] = useState<GridImage[] | null>(null)
  const onFrame = useRef(opts.onFrame)
  const onEnd = useRef(opts.onEnd)
  onFrame.current = opts.onFrame
  onEnd.current = opts.onEnd
  const lastDay = useRef(-1)
  const prepared = useRef<{ key: string; frames: string[]; images: GridImage[] } | null>(null)
  // Bumped by stop(): a replay still preparing when it changes does not start
  const run = useRef(0)

  /** Tell the page when the nearest whole day changes. */
  const announce = useCallback((t: number, list: string[]) => {
    const d = Math.round(t)
    if (d !== lastDay.current && list[d]) { lastDay.current = d; onFrame.current(list[d]) }
  }, [])

  const prepare = useCallback(async (days: string[]) => {
    const key = `${model}:${days.join(',')}`
    if (prepared.current?.key === key) return prepared.current
    // Only the estimate grids: the replay shows no station readings
    await Promise.all(days.map(d =>
      qc.prefetchQuery({ queryKey: ['ops-prediction-data', d, model], queryFn: () => fetchPredictionData(d, model) }),
    ))
    const clip = await loadCountryPolygons()
    const kept: string[] = []
    const imgs: GridImage[] = []
    for (const d of days) {
      const raster = predictionRaster(qc.getQueryData<PredictionData>(['ops-prediction-data', d, model]))
      const data = qc.getQueryData<PredictionData>(['ops-prediction-data', d, model])
      const image = raster ? cachedGridImage(estimateKey(data as { date?: string; model?: string } | undefined) ?? `${d}:${model}`, () => renderGridImage(raster, SURFACE_RANGE, { scale: 5, clip })) : null
      if (image) { kept.push(d); imgs.push(image) }
      await new Promise(r => setTimeout(r, 0)) // let the page breathe between days
    }
    prepared.current = { key, frames: kept, images: imgs }
    return prepared.current
  }, [qc, model])

  const play = useCallback(async () => {
    if (status === 'paused') {
      // Pressing play at the end starts again
      if (clock.get() >= frames.length - 1) { clock.set(0); announce(0, frames) }
      setStatus('playing')
      return
    }
    if (status !== 'idle') return
    const days = dates.slice(-REPLAY_DAYS)
    if (days.length < 2) return
    setStatus('loading')
    const id = ++run.current
    try {
      const p = await prepare(days)
      if (id !== run.current) return // cancelled while preparing
      if (p.frames.length < 2) { setStatus('idle'); return }
      setFrames(p.frames)
      setImages(p.images)
      lastDay.current = -1
      clock.set(0)
      announce(0, p.frames)
      setStatus('playing')
    } catch {
      if (id === run.current) setStatus('idle')
    }
  }, [status, dates, prepare, clock, frames, announce])

  const pause = useCallback(() => setStatus(s => (s === 'playing' ? 'paused' : s)), [])

  const stop = useCallback(() => {
    run.current++
    setStatus('idle')
    setImages(null)
    lastDay.current = -1
  }, [])

  /** Move the playhead (dragging the scrubber); pauses the replay. */
  const seek = useCallback((t: number) => {
    const v = Math.max(0, Math.min(frames.length - 1, t))
    clock.set(v)
    announce(v, frames)
    setStatus(s => (s === 'playing' || s === 'ending' ? 'paused' : s))
  }, [clock, frames, announce])

  // The playhead moves on animation frames while playing
  useEffect(() => {
    if (status !== 'playing') return
    let raf = 0
    let last = performance.now()
    const tick = (now: number) => {
      const dt = Math.min(64, now - last) // a hidden tab does not leap ahead
      last = now
      const end = frames.length - 1
      const t = Math.min(end, clock.get() + dt / MS_PER_DAY)
      clock.set(t)
      announce(t, frames)
      if (t >= end) { setStatus('ending'); return }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [status, frames, clock, announce])

  // Hold the last day for a moment, then hand back to today
  useEffect(() => {
    if (status !== 'ending') return
    const t = setTimeout(() => { setStatus('idle'); setImages(null); lastDay.current = -1; onEnd.current() }, END_HOLD_MS)
    return () => clearTimeout(t)
  }, [status])

  const active = status === 'playing' || status === 'paused' || status === 'ending'
  return { status, active, frames, images: active ? images : null, clock, play, pause, stop, seek }
}
