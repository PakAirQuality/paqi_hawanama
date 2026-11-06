"use client"

// The trajectory map drawn inside a chat answer: where the air arriving at a place had been
// (or where air leaving it goes), on three levels, with the fires it passed near. Plain SVG on an
// equirectangular projection, so it needs no map token and works on phones.

import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchTrajectory, retryServerErrorsOnly, trajectoryQueryKey } from '@/components/fires/api'
import type { TrajectoryDoc, TrajectoryPoint } from '@/components/fires/api'
import { fitProjection, outlinePath, scaleBarKm, toPath } from '@/lib/chat/trajectoryMap'
import type { GeoCollection, LonLat } from '@/lib/chat/trajectoryMap'
import type { CopilotAction } from './types'

const W = 320
const H = 230
const LEVELS: { key: string; label: string; colour: string }[] = [
  { key: '1000', label: '~100 m', colour: '#1d4ed8' },
  { key: '925', label: '~700 m', colour: '#0f766e' },
  { key: '850', label: '~1,400 m', colour: '#b45309' },
]
const FIRE = '#ea580c'
const MARKS = [24, 48, 72]
const REGIONS = ['Pakistan Punjab', 'other Pakistan', 'Indian Punjab', 'Haryana', 'elsewhere']

async function loadGeo(path: string): Promise<GeoCollection> {
  const res = await fetch(path)
  if (!res.ok) throw new Error(`${path}: ${res.status}`)
  return res.json() as Promise<GeoCollection>
}

function hoursLine(doc: TrajectoryDoc): string {
  const res = doc.residence_hours['925'] ?? Object.values(doc.residence_hours)[0]
  if (!res) return ''
  const parts = REGIONS.filter(r => (res[r] ?? 0) > 0).map(r => `${res[r]} h ${r}`)
  return parts.length ? `At ~700 m the air spent ${parts.join(', ')}.` : ''
}

export function TrajectoryMiniMap({ action }: { action: CopilotAction }) {
  const req = useMemo(
    () => ({ lat: action.lat ?? 0, lon: action.lon ?? 0, at: action.at ?? '', direction: action.direction ?? 'backward', hours: action.hours ?? 72, label: action.label }),
    [action.lat, action.lon, action.at, action.direction, action.hours, action.label],
  )
  const traj = useQuery({ queryKey: trajectoryQueryKey(req), queryFn: () => fetchTrajectory(req), staleTime: 10 * 60 * 1000, retry: retryServerErrorsOnly })
  const pk = useQuery({ queryKey: ['geo', 'pakistan-adm1'], queryFn: () => loadGeo('/pakistan_adm1.geojson'), staleTime: Infinity, retry: 1 })
  const india = useQuery({ queryKey: ['geo', 'india-pb-hr'], queryFn: () => loadGeo('/india_pb_hr.geojson'), staleTime: Infinity, retry: 1 })

  const doc = traj.data
  const scene = useMemo(() => {
    if (!doc) return null
    const all: LonLat[] = [{ lon: doc.origin.lon, lat: doc.origin.lat }]
    for (const path of Object.values(doc.paths)) for (const p of path) all.push({ lon: p.lon, lat: p.lat })
    const proj = fitProjection(all, W, H, 22)
    const lines = LEVELS.filter(l => doc.paths[l.key]?.length > 1).map(l => ({
      ...l,
      d: toPath(doc.paths[l.key].map(p => ({ lon: p.lon, lat: p.lat })), proj),
      sixHourly: doc.paths[l.key].filter(p => Math.abs(p.age_h) % 6 === 0 && p.age_h !== 0).map(p => proj.project(p)),
    }))
    const markPath: TrajectoryPoint[] = doc.paths['925'] ?? Object.values(doc.paths)[0] ?? []
    const marks = MARKS.map(h => markPath.find(p => Math.abs(p.age_h) === h)).filter((p): p is TrajectoryPoint => !!p)
      .map(p => ({ h: Math.abs(p.age_h), ...proj.project(p) }))
    const fires = (doc.fires.loose?.points ?? []).map(f => ({ ...proj.project(f), r: Math.min(5, 1.5 + Math.sqrt(Math.max(f.frp, 1)) / 4), frp: f.frp, district: f.district }))
    const origin = proj.project(doc.origin)
    const km = scaleBarKm(proj)
    return { proj, lines, marks, fires, origin, km, barUnits: proj.kmToUnits(km), pk: outlinePath(pk.data, proj), india: outlinePath(india.data, proj) }
  }, [doc, pk.data, india.data])

  if (traj.isError) {
    const msg = traj.error instanceof Error ? traj.error.message : 'trajectory unavailable'
    return (
      <div className="mt-2 flex items-center justify-between gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
        <span>Map unavailable: {msg}</span>
        <button type="button" onClick={() => traj.refetch()} className="rounded-md px-2 py-1 font-medium text-blue-700 hover:bg-blue-50">Retry</button>
      </div>
    )
  }
  if (!doc || !scene) {
    return <div className="skeleton mt-2 h-[230px] w-full rounded-xl" aria-busy="true" aria-label="Loading the trajectory map" />
  }
  const backward = doc.direction === 'backward'
  const label = doc.origin.label || action.label || 'here'
  const title = backward ? `Where the air reaching ${label} had been` : `Where air leaving ${label} goes`
  const sector24 = doc.sectors['24']?.modal
  const agree24 = doc.sectors['24']?.agreement
  const fireCount = doc.fires.loose?.n_fires ?? 0

  return (
    <figure className="mt-2 rounded-xl border border-slate-200 bg-white" data-testid="trajectory-map">
      <figcaption className="px-3 pt-2 text-xs font-medium text-slate-700">
        {title}
        <span className="font-normal text-slate-500"> · {doc.hours} h {backward ? 'before' : 'after'} {doc.at_pkt}</span>
      </figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={title} className="block w-full" style={{ aspectRatio: `${W} / ${H}` }}>
        <defs>
          {LEVELS.map(l => (
            <marker key={l.key} id={`traj-arrow-${l.key}`} viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient={backward ? 'auto-start-reverse' : 'auto'}>
              <path d="M0 0 L8 4 L0 8 Z" fill={l.colour} />
            </marker>
          ))}
        </defs>
        <rect x={0} y={0} width={W} height={H} fill="#f8fafc" />
        {scene.india && <path d={scene.india} fill="#eef2f7" stroke="#cbd5e1" strokeWidth={0.8} strokeLinejoin="round" />}
        {scene.pk && <path d={scene.pk} fill="#f1f5f9" stroke="#94a3b8" strokeWidth={0.8} strokeLinejoin="round" />}
        {scene.fires.map((f, i) => (
          <circle key={`f${i}`} cx={f.x} cy={f.y} r={f.r} fill={FIRE} fillOpacity={0.45} stroke={FIRE} strokeWidth={0.4}>
            <title>{`${f.district ?? 'fire'} · ${f.frp} MW`}</title>
          </circle>
        ))}
        {scene.lines.map(l => (
          <g key={l.key}>
            <path d={l.d} fill="none" stroke="#ffffff" strokeWidth={4} strokeLinejoin="round" strokeLinecap="round" opacity={0.8} />
            <path
              d={l.d} fill="none" stroke={l.colour} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round"
              {...(backward ? { markerStart: `url(#traj-arrow-${l.key})` } : { markerEnd: `url(#traj-arrow-${l.key})` })}
            />
            {l.sixHourly.map((p, i) => <circle key={i} cx={p.x} cy={p.y} r={1.6} fill={l.colour} />)}
          </g>
        ))}
        {scene.marks.map(m => (
          <text key={m.h} x={m.x + 4} y={m.y - 4} fontSize={9} fill="#334155" stroke="#ffffff" strokeWidth={3} paintOrder="stroke" fontWeight={600}>
            {m.h} h
          </text>
        ))}
        <circle cx={scene.origin.x} cy={scene.origin.y} r={4} fill="#0f172a" stroke="#ffffff" strokeWidth={1.5} />
        <text x={scene.origin.x + 7} y={scene.origin.y + 4} fontSize={10} fontWeight={700} fill="#0f172a" stroke="#ffffff" strokeWidth={3} paintOrder="stroke">
          {label}
        </text>
        <g transform={`translate(${W - 12 - scene.barUnits} ${H - 12})`}>
          <line x1={0} y1={0} x2={scene.barUnits} y2={0} stroke="#334155" strokeWidth={1.5} />
          <line x1={0} y1={-3} x2={0} y2={3} stroke="#334155" strokeWidth={1.5} />
          <line x1={scene.barUnits} y1={-3} x2={scene.barUnits} y2={3} stroke="#334155" strokeWidth={1.5} />
          <text x={scene.barUnits / 2} y={-5} fontSize={8} textAnchor="middle" fill="#334155">{scene.km} km</text>
        </g>
      </svg>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 pt-1 text-[11px] text-slate-600">
        {LEVELS.map(l => (
          <span key={l.key} className="inline-flex items-center gap-1">
            <span className="inline-block h-0.5 w-4 rounded" style={{ background: l.colour }} />
            {l.label}
          </span>
        ))}
        <span className="inline-flex items-center gap-1">
          <span className="inline-block h-2 w-2 rounded-full" style={{ background: FIRE, opacity: 0.6 }} />
          fires within 25 km of the path{fireCount ? ` (${fireCount})` : ''}
        </span>
      </div>
      <p className="px-3 pb-2 pt-1 text-[11px] leading-4 text-slate-500">
        {sector24 ? `At 24 h the air was to the ${sector24}${agree24 != null ? ` (${Math.round(agree24 * 3)} of 3 levels agree)` : ''}. ` : ''}
        {hoursLine(doc)}{' '}
        {doc.engine.startsWith('hysplit') ? 'HYSPLIT on GFS 0.25°' : 'Kinematic trajectory on ECMWF IFS 0.25° winds'}; position error roughly 10–20 % of the distance travelled. A plausibility screen, not an attribution.
      </p>
    </figure>
  )
}
