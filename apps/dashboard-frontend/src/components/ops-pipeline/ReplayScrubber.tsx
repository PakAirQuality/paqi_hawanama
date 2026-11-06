'use client'

import { useEffect, useRef, useSyncExternalStore } from 'react'
import { Pause, Play, X } from 'lucide-react'
import { formatDateOnly } from '@/lib/time'
import type { ReplayClock, ReplayStatus } from './useDayPlayback'

/**
 * The replay's scrubber, in the manner of a phone weather app's precipitation map: play and pause, a track with a
 * tick for every day, a playhead that glides with the replay and a date bubble that follows it. Drag or tap the
 * track to scrub (the replay pauses). Only this component re-renders as the playhead moves.
 */
export function ReplayScrubber({ frames, clock, status, onPlay, onPause, onSeek, onClose }: {
  frames: string[]
  clock: ReplayClock
  status: ReplayStatus
  onPlay: () => void
  onPause: () => void
  onSeek: (t: number) => void
  onClose: () => void
}) {
  const t = useSyncExternalStore(clock.subscribe, clock.get, clock.get)
  const n = frames.length
  const pct = n > 1 ? (t / (n - 1)) * 100 : 0
  const day = frames[Math.max(0, Math.min(n - 1, Math.round(t)))]
  const trackRef = useRef<HTMLDivElement>(null)
  const dragging = useRef(false)

  const seekAt = (clientX: number) => {
    const el = trackRef.current
    if (!el || n < 2) return
    const r = el.getBoundingClientRect()
    onSeek(Math.max(0, Math.min(1, (clientX - r.left) / r.width)) * (n - 1))
  }

  // Keyboard: arrows step a day, space plays or pauses
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      e.preventDefault()
      onSeek(Math.round(t) + (e.key === 'ArrowRight' ? 1 : -1))
    } else if (e.key === ' ' || e.key === 'Enter') {
      e.preventDefault()
      if (status === 'playing') onPause(); else onPlay()
    }
  }

  useEffect(() => () => { dragging.current = false }, [])

  const short = (d: string) => formatDateOnly(d, { day: 'numeric', month: 'short' })

  return (
    <div className="flex min-w-0 flex-1 items-center gap-2">
      <button
        onClick={() => (status === 'playing' ? onPause() : onPlay())}
        aria-label={status === 'playing' ? 'Pause the replay' : 'Play the replay'}
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-slate-900 text-white transition-transform duration-150 active:scale-90"
      >
        {status === 'playing' ? <Pause className="h-4 w-4" fill="currentColor" /> : <Play className="h-4 w-4 translate-x-px" fill="currentColor" />}
      </button>

      <span className="hidden shrink-0 text-[11px] tabular-nums text-slate-500 sm:block">{n ? short(frames[0]) : ''}</span>

      {/* Track */}
      <div
        ref={trackRef}
        role="slider"
        tabIndex={0}
        aria-label="Replay position"
        aria-valuemin={0}
        aria-valuemax={n - 1}
        aria-valuenow={Math.round(t)}
        aria-valuetext={day ? formatDateOnly(day, { weekday: 'long', day: 'numeric', month: 'long' }) : ''}
        onKeyDown={onKey}
        onPointerDown={(e) => { dragging.current = true; e.currentTarget.setPointerCapture(e.pointerId); seekAt(e.clientX) }}
        onPointerMove={(e) => { if (dragging.current) seekAt(e.clientX) }}
        onPointerUp={(e) => { dragging.current = false; e.currentTarget.releasePointerCapture(e.pointerId) }}
        onPointerCancel={() => { dragging.current = false }}
        className="relative mx-1 flex h-9 min-w-0 flex-1 cursor-pointer touch-none items-center outline-none focus-visible:rounded-full focus-visible:ring-2 focus-visible:ring-slate-900/25"
      >
        <div className="pointer-events-none absolute left-0 right-0 top-1/2 h-[3px] -translate-y-1/2 rounded-full bg-slate-900/10" />
        {/* Day ticks */}
        <div className="pointer-events-none absolute inset-x-0 top-1/2 flex -translate-y-1/2 justify-between">
          {frames.map((d, i) => (
            <span key={d} className={`w-px rounded-full ${i <= t ? 'bg-slate-900/45' : 'bg-slate-900/20'}`} style={{ height: i === 0 || i === n - 1 ? 12 : 8 }} />
          ))}
        </div>
        {/* Played part */}
        <div className="pointer-events-none absolute left-0 top-1/2 h-[3px] -translate-y-1/2 rounded-full bg-slate-900/70" style={{ width: `${pct}%` }} />
        {/* Playhead with its date */}
        <div className="pointer-events-none absolute top-1/2 -translate-x-1/2 -translate-y-1/2" style={{ left: `${pct}%` }}>
          <div className="h-4 w-4 rounded-full border-2 border-white bg-slate-900 shadow-md" />
          <div className="absolute bottom-full left-1/2 mb-2.5 -translate-x-1/2 whitespace-nowrap rounded-lg bg-slate-900 px-2 py-1 text-[11px] font-semibold tabular-nums text-white shadow-lg">
            {day ? formatDateOnly(day, { weekday: 'short', day: 'numeric', month: 'short' }) : ''}
          </div>
        </div>
      </div>

      <span className="hidden shrink-0 text-[11px] tabular-nums text-slate-500 sm:block">{n ? short(frames[n - 1]) : ''}</span>

      <button
        onClick={onClose}
        aria-label="Close the replay and go back to today"
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-slate-600 transition-[background-color,color,transform] duration-150 hover:bg-slate-900/[0.06] hover:text-slate-900 active:scale-90"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  )
}
