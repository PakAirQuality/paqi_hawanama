'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { fetchPredictionData, fetchStationDaily } from './api'
import type { ModelKey } from '@/lib/selection'

/** How many finished days the replay steps through, and how long each is shown. */
export const REPLAY_DAYS = 14
const FRAME_MS = 1100

/**
 * Replays the PM2.5 estimate day by day: the last REPLAY_DAYS finished days, each with its satellite estimate and
 * its station daily means, then back to today. Every day is fetched before the replay starts (with the same query
 * keys the page uses), so frames never wait on the network; the map crossfades from one day's estimate to the next.
 */
export function useDayPlayback(opts: { dates: string[]; model: ModelKey; onFrame: (date: string) => void; onEnd: () => void }) {
  const { dates, model } = opts
  const qc = useQueryClient()
  const [status, setStatus] = useState<'idle' | 'loading' | 'playing' | 'paused'>('idle')
  const [frames, setFrames] = useState<string[]>([])
  const [index, setIndex] = useState(0)
  const onFrame = useRef(opts.onFrame)
  const onEnd = useRef(opts.onEnd)
  onFrame.current = opts.onFrame
  onEnd.current = opts.onEnd

  const play = useCallback(async () => {
    if (status === 'paused') { setStatus('playing'); return }
    const days = dates.slice(-REPLAY_DAYS)
    if (days.length < 2) return
    setStatus('loading')
    await Promise.all(days.flatMap(d => [
      qc.prefetchQuery({ queryKey: ['ops-prediction-data', d, model], queryFn: () => fetchPredictionData(d, model) }),
      qc.prefetchQuery({ queryKey: ['ops-station-daily', d, 6], queryFn: () => fetchStationDaily(d, 'Pakistan', 6) }),
    ])).catch(() => { /* a missing day shows without its layer; the replay goes on */ })
    setFrames(days)
    setIndex(0)
    onFrame.current(days[0])
    setStatus('playing')
  }, [status, dates, model, qc])

  const pause = useCallback(() => setStatus(s => (s === 'playing' ? 'paused' : s)), [])
  const stop = useCallback(() => { setStatus('idle'); setIndex(0) }, [])

  useEffect(() => {
    if (status !== 'playing') return
    const t = setTimeout(() => {
      if (index >= frames.length - 1) { setStatus('idle'); setIndex(0); onEnd.current(); return }
      const next = index + 1
      setIndex(next)
      onFrame.current(frames[next])
    }, FRAME_MS)
    return () => clearTimeout(t)
  }, [status, index, frames])

  return { status, active: status === 'playing' || status === 'paused', index, count: frames.length, play, pause, stop }
}
