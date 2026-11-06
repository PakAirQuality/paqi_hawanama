"use client"

// The trajectory figure inside a chat answer: where the air arriving at a place had been (or where
// air leaving it goes), on three levels with the ensemble members of each, and the fires it passed
// near. The small figure is a preview (Mapbox when the browser can draw one and the figure is on
// screen, the SVG otherwise) that opens the expanded, interactive view when clicked; level toggles,
// a one-line caption with the member agreement, and the method behind a "How to read this map"
// disclosure.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useQuery } from '@tanstack/react-query'
import { Maximize2, X } from 'lucide-react'
import { fetchTrajectory, retryServerErrorsOnly, trajectoryQueryKey } from '@/components/fires/api'
import type { TrajectoryDoc } from '@/components/fires/api'
import { FIRE_COLOUR, LEVELS, LEVEL_KEYS, REGIONS, ensembleLine } from '@/lib/chat/trajectoryMap'
import { canRenderMap } from '@/lib/webgl'
import { TrajectoryMapGL } from './TrajectoryMapGL'
import { TrajectorySvg } from './TrajectorySvg'
import type { CopilotAction } from './types'

function hoursLine(doc: TrajectoryDoc): string {
  const res = doc.residence_hours['925'] ?? Object.values(doc.residence_hours)[0]
  if (!res) return ''
  const parts = REGIONS.filter(r => (res[r] ?? 0) > 0).map(r => `${res[r]} h ${r}`)
  return parts.length ? `At ~700 m the air spent ${parts.join(', ')}.` : ''
}

/** True while the element is on screen (always true where IntersectionObserver is missing). A callback ref, so the
 *  observer attaches whenever the figure appears, including after the loading skeleton it replaces. */
function useInView<T extends Element>(): [boolean, (el: T | null) => void] {
  const io = useRef<IntersectionObserver | null>(null)
  const [inView, setInView] = useState(() => typeof IntersectionObserver === 'undefined')
  const ref = useCallback((el: T | null) => {
    io.current?.disconnect()
    io.current = null
    if (!el || typeof IntersectionObserver === 'undefined') return
    io.current = new IntersectionObserver(([entry]) => setInView(entry.isIntersecting), { rootMargin: '160px' })
    io.current.observe(el)
  }, [])
  return [inView, ref]
}

function LevelToggles({ visible, onChange, doc }: { visible: string[]; onChange: (v: string[]) => void; doc: TrajectoryDoc }) {
  const toggle = (key: string) => {
    const next = visible.includes(key) ? visible.filter(k => k !== key) : [...visible, key]
    if (next.length) onChange(LEVEL_KEYS.filter(k => next.includes(k)))
  }
  const members = doc.ensemble?.n_members
  return (
    <>
      {LEVELS.filter(l => doc.paths[l.key]).map(l => {
        const on = visible.includes(l.key)
        return (
          <button
            key={l.key} type="button" aria-pressed={on} onClick={() => toggle(l.key)}
            title={members?.[l.key] ? `${members[l.key]} members` : undefined}
            className={`inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 transition-colors ${on ? 'border-slate-300 bg-white text-slate-700' : 'border-transparent bg-slate-100 text-slate-400 line-through'}`}
          >
            <span className="inline-block h-0.5 w-4 rounded" style={{ background: l.colour, opacity: on ? 1 : 0.4 }} />
            {l.label}
          </button>
        )
      })}
    </>
  )
}

function Legend({ doc, visible, onChange }: { doc: TrajectoryDoc; visible: string[]; onChange: (v: string[]) => void }) {
  const fireCount = doc.fires.loose?.n_fires ?? 0
  return (
    <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 px-3 pt-1.5 text-[11px] text-slate-600">
      <LevelToggles visible={visible} onChange={onChange} doc={doc} />
      <span className="inline-flex items-center gap-1">
        <span className="inline-block h-2 w-2 rounded-full" style={{ background: FIRE_COLOUR, opacity: 0.6 }} />
        fires within 25 km{fireCount ? ` (${fireCount})` : ''}
      </span>
    </div>
  )
}

/** One line under the map (the member agreement, or the sector when there is no ensemble) and the method behind a disclosure. */
function Caption({ doc, open = false }: { doc: TrajectoryDoc; open?: boolean }) {
  const sector24 = doc.sectors['24']?.modal
  const agree24 = doc.sectors['24']?.agreement
  const sectorLine = sector24 ? `At 24 h the air was to the ${sector24}${agree24 != null ? ` (${Math.round(agree24 * 3)} of 3 levels agree)` : ''}.` : ''
  const members = ensembleLine(doc)
  const hasMembers = !!doc.ensemble && Object.values(doc.ensemble.members ?? {}).some(m => m.length)
  return (
    <div className="px-3 pb-2 pt-1 text-[11px] leading-4 text-slate-500">
      <p>{members || sectorLine}</p>
      <details open={open} className="mt-0.5">
        <summary className="cursor-pointer select-none text-slate-400 hover:text-slate-600">How to read this map</summary>
        <p className="mt-1">
          {members && sectorLine ? `${sectorLine} ` : ''}{hoursLine(doc)}{' '}
          {hasMembers && <>The thin lines are the {doc.ensemble?.n_members ? Object.values(doc.ensemble.n_members).reduce((a, b) => a + b, 0) : ''} ensemble members: the start point shifted by ±{doc.ensemble?.offsets.horizontal_deg}° and ±{doc.ensemble?.offsets.vertical_hpa} hPa; their spread shows sensitivity to the winds, not a probability.{' '}</>}
          {doc.engine.startsWith('hysplit') ? 'HYSPLIT on GFS 0.25°' : 'Kinematic trajectory on ECMWF IFS 0.25° winds'}. A plausibility screen, not an attribution.
        </p>
      </details>
    </div>
  )
}

export function TrajectoryMiniMap({ action }: { action: CopilotAction }) {
  const req = useMemo(
    () => ({ lat: action.lat ?? 0, lon: action.lon ?? 0, at: action.at ?? '', direction: action.direction ?? 'backward', hours: action.hours ?? 72, label: action.label }),
    [action.lat, action.lon, action.at, action.direction, action.hours, action.label],
  )
  const traj = useQuery({ queryKey: trajectoryQueryKey(req), queryFn: () => fetchTrajectory(req), staleTime: 10 * 60 * 1000, retry: retryServerErrorsOnly })
  const doc = traj.data

  const [visible, setVisible] = useState<string[]>(LEVEL_KEYS)
  const [expanded, setExpanded] = useState(false)
  const [gl, setGl] = useState(() => typeof window !== 'undefined' && canRenderMap())
  const [inView, figureRef] = useInView<HTMLElement>()

  // the expanded view: Escape closes it, the page behind it does not scroll
  useEffect(() => {
    if (!expanded) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setExpanded(false) }
    window.addEventListener('keydown', onKey)
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { window.removeEventListener('keydown', onKey); document.body.style.overflow = prev }
  }, [expanded])

  if (traj.isError) {
    const msg = traj.error instanceof Error ? traj.error.message : 'trajectory unavailable'
    return (
      <div className="mt-2 flex items-center justify-between gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
        <span>Map unavailable: {msg}</span>
        <button type="button" onClick={() => traj.refetch()} className="rounded-md px-2 py-1 font-medium text-blue-700 hover:bg-blue-50">Retry</button>
      </div>
    )
  }
  if (!doc) {
    return <div className="skeleton mt-2 h-[260px] w-full rounded-xl" aria-busy="true" aria-label="Loading the trajectory map" />
  }
  const backward = doc.direction === 'backward'
  const label = doc.origin.label || action.label || 'here'
  const title = backward ? `Where the air reaching ${label} had been` : `Where air leaving ${label} goes`
  const subtitle = `${doc.hours} h ${backward ? 'before' : 'after'} ${doc.at_pkt}`
  const shown = visible.filter(k => doc.paths[k]).length ? visible : LEVEL_KEYS
  const members = doc.ensemble ? Object.values(doc.ensemble.n_members).reduce((a, b) => a + b, 0) : 0
  const useGl = gl && inView && !expanded

  return (
    <figure ref={figureRef} className="mt-2 rounded-xl border border-slate-200 bg-white" data-testid="trajectory-map">
      <figcaption className="flex items-start justify-between gap-2 px-3 pt-2 text-xs font-medium text-slate-700">
        <span>
          {title}
          <span className="font-normal text-slate-500"> · {subtitle}{members ? ` · ${members} members` : ''}</span>
        </span>
        <button
          type="button" onClick={() => setExpanded(true)} aria-label="Expand the map"
          className="-mr-1 -mt-0.5 shrink-0 rounded-md p-1 text-slate-500 hover:bg-slate-100 hover:text-slate-800"
        >
          <Maximize2 size={14} />
        </button>
      </figcaption>
      {/* a div with the button role: Mapbox's own attribution control is a <button>, which must not nest inside another */}
      <div
        role="button" tabIndex={0} aria-label="Open the map"
        onClick={() => setExpanded(true)}
        onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setExpanded(true) } }}
        className="group relative mt-1 block h-[260px] w-full cursor-pointer overflow-hidden rounded-lg focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
      >
        {useGl
          ? <TrajectoryMapGL doc={doc} visible={shown} title={title} preview className="h-full w-full" onUnavailable={() => setGl(false)} />
          : <TrajectorySvg doc={doc} visible={shown} label={label} title={title} className="block h-full w-full" />}
        <span className="pointer-events-none absolute right-2 top-2 inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white/90 px-2 py-0.5 text-[11px] font-medium text-slate-600 shadow-sm group-hover:bg-white group-hover:text-slate-800">
          <Maximize2 size={11} /> Tap to expand
        </span>
      </div>
      <Legend doc={doc} visible={shown} onChange={setVisible} />
      <Caption doc={doc} />

      {expanded && typeof document !== 'undefined' && createPortal(
        <div role="dialog" aria-modal="true" aria-label={title} className="fixed inset-0 z-[120] flex items-center justify-center bg-slate-900/60 p-3 md:p-6" onClick={() => setExpanded(false)}>
          <div className="flex h-full w-full max-w-6xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl" onClick={e => e.stopPropagation()}>
            <div className="flex items-start justify-between gap-3 border-b border-slate-200 px-4 py-2.5">
              <div className="text-sm font-medium text-slate-800">
                {title}
                <span className="font-normal text-slate-500"> · {subtitle}{members ? ` · ${members} members` : ''}</span>
              </div>
              <button type="button" onClick={() => setExpanded(false)} aria-label="Close" className="rounded-md p-1 text-slate-500 hover:bg-slate-100 hover:text-slate-800">
                <X size={18} />
              </button>
            </div>
            <div className="relative min-h-0 flex-1 bg-slate-50">
              {gl
                ? <TrajectoryMapGL doc={doc} visible={shown} title={title} className="h-full w-full" onUnavailable={() => setGl(false)} />
                : <TrajectorySvg doc={doc} visible={shown} label={label} title={title} className="mx-auto block h-full max-w-full" />}
            </div>
            <div className="border-t border-slate-200 pb-1">
              <Legend doc={doc} visible={shown} onChange={setVisible} />
              <Caption doc={doc} open />
            </div>
          </div>
        </div>,
        document.body,
      )}
    </figure>
  )
}

