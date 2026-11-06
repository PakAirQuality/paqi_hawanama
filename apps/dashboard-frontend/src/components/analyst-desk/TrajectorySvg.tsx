"use client"

// The token-free trajectory drawing: plain SVG on an equirectangular projection. It stands in for
// the Mapbox map when WebGL is unavailable, while the figure is off screen, and in tests. It draws
// the same things: member spaghetti under the bold central paths, 6-hourly dots, hour marks, the
// fires along the way and the origin, with the Pakistan and Indian Punjab–Haryana outlines behind.

import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { TrajectoryDoc, TrajectoryPoint } from '@/components/fires/api'
import { FIRE_COLOUR, LEVELS, MARK_HOURS, allPoints, fitProjection, memberPaths, outlinePath, scaleBarKm, toPath } from '@/lib/chat/trajectoryMap'
import type { GeoCollection } from '@/lib/chat/trajectoryMap'

const W = 320
const H = 230

async function loadGeo(path: string): Promise<GeoCollection> {
  const res = await fetch(path)
  if (!res.ok) throw new Error(`${path}: ${res.status}`)
  return res.json() as Promise<GeoCollection>
}

interface Props {
  doc: TrajectoryDoc
  visible: string[]
  label: string
  title: string
  className?: string
}

export function TrajectorySvg({ doc, visible, label, title, className }: Props) {
  const pk = useQuery({ queryKey: ['geo', 'pakistan-adm1'], queryFn: () => loadGeo('/pakistan_adm1.geojson'), staleTime: Infinity, retry: 1 })
  const india = useQuery({ queryKey: ['geo', 'india-pb-hr'], queryFn: () => loadGeo('/india_pb_hr.geojson'), staleTime: Infinity, retry: 1 })
  const backward = doc.direction === 'backward'

  const scene = useMemo(() => {
    const proj = fitProjection(allPoints(doc), W, H, 22)
    const members = memberPaths(doc)
    const lines = LEVELS.filter(l => doc.paths[l.key]?.length > 1).map(l => ({
      ...l,
      d: toPath(doc.paths[l.key].map(p => ({ lon: p.lon, lat: p.lat })), proj),
      members: (members[l.key] ?? []).map(m => toPath(m, proj)),
      sixHourly: doc.paths[l.key].filter(p => Math.abs(p.age_h) % 6 === 0 && p.age_h !== 0).map(p => proj.project(p)),
    }))
    const markKey = visible.includes('925') && doc.paths['925'] ? '925' : visible.find(k => doc.paths[k]) ?? Object.keys(doc.paths)[0]
    const markPath: TrajectoryPoint[] = doc.paths[markKey] ?? []
    const marks = MARK_HOURS.map(h => markPath.find(p => Math.abs(p.age_h) === h)).filter((p): p is TrajectoryPoint => !!p)
      .map(p => ({ h: Math.abs(p.age_h), ...proj.project(p) }))
    const fires = (doc.fires.loose?.points ?? []).map(f => ({ ...proj.project(f), r: Math.min(5, 1.5 + Math.sqrt(Math.max(f.frp, 1)) / 4), frp: f.frp, district: f.district }))
    const origin = proj.project(doc.origin)
    const km = scaleBarKm(proj)
    return { lines, marks, fires, origin, km, barUnits: proj.kmToUnits(km), pk: outlinePath(pk.data, proj), india: outlinePath(india.data, proj) }
  }, [doc, visible, pk.data, india.data])

  const shown = scene.lines.filter(l => visible.includes(l.key))

  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={title} className={className ?? 'block w-full'} style={{ aspectRatio: `${W} / ${H}` }} data-testid="trajectory-map-svg">
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
        <circle key={`f${i}`} cx={f.x} cy={f.y} r={f.r} fill={FIRE_COLOUR} fillOpacity={0.45} stroke={FIRE_COLOUR} strokeWidth={0.4}>
          <title>{`${f.district ?? 'fire'} · ${f.frp} MW`}</title>
        </circle>
      ))}
      {shown.map(l => (
        <g key={`m${l.key}`} className="traj-members">
          {l.members.map((d, i) => <path key={i} d={d} fill="none" stroke={l.colour} strokeWidth={0.7} strokeOpacity={0.3} strokeLinejoin="round" className="traj-member" />)}
        </g>
      ))}
      {shown.map(l => (
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
  )
}
