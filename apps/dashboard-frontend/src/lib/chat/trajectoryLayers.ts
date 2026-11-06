'use client'

// The trajectory document as GeoJSON, and the hook that draws it on a Mapbox map: the ensemble
// members as thin spaghetti under the bold central path of each level, 6-hourly points with a
// hover popup, the 24/48/72 h marks, an arrowhead, the fires met along the way and the origin.
// Both the map inside the chat answer and the expanded one use it.

import { useEffect } from 'react'
import mapboxgl from 'mapbox-gl'
import type { TrajectoryDoc, TrajectoryPoint } from '@/components/fires/api'
import { ensureFlame } from '@/components/ops-pipeline/mapViz'
import { esc } from '@/lib/html'
import { FIRE_COLOUR, LEVELS, MARK_HOURS, levelOrder, levelStyle, memberPaths } from './trajectoryMap'

type Feature = GeoJSON.Feature
type FC = GeoJSON.FeatureCollection

export interface TrajectoryGeo {
  members: FC
  central: FC
  points: FC
  marks: FC
  arrows: FC
  fires: FC
  origin: FC
}

const fc = (features: Feature[]): FC => ({ type: 'FeatureCollection', features })
const line = (coords: [number, number][], properties: Record<string, unknown>): Feature => ({ type: 'Feature', geometry: { type: 'LineString', coordinates: coords }, properties })
const point = (lon: number, lat: number, properties: Record<string, unknown>): Feature => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [lon, lat] }, properties })

/** Initial bearing (degrees clockwise from north) from a to b. */
export function bearingDeg(a: { lon: number; lat: number }, b: { lon: number; lat: number }): number {
  const toRad = Math.PI / 180
  const dLon = (b.lon - a.lon) * toRad
  const y = Math.sin(dLon) * Math.cos(b.lat * toRad)
  const x = Math.cos(a.lat * toRad) * Math.sin(b.lat * toRad) - Math.sin(a.lat * toRad) * Math.cos(b.lat * toRad) * Math.cos(dLon)
  return ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360
}

const pkt = (iso: string): string => {
  const t = new Date(iso.endsWith('Z') ? iso : iso + 'Z')
  if (Number.isNaN(t.getTime())) return iso
  return t.toLocaleString('en-GB', { timeZone: 'Asia/Karachi', weekday: 'short', hour: 'numeric', minute: '2-digit', hour12: true }) + ' PKT'
}

/** How many members of this level were over each region at this hour, as one short string ("21 Pakistan Punjab, 6 Indian Punjab"). */
function membersOver(doc: TrajectoryDoc, level: string, age: number): string {
  const regions = doc.ensemble?.regions_at?.[String(age)]?.[level]
  if (!regions) return ''
  return Object.entries(regions).sort((a, b) => b[1] - a[1]).map(([r, n]) => `${n} ${r}`).join(', ')
}

export function trajectoryGeo(doc: TrajectoryDoc): TrajectoryGeo {
  const backward = doc.direction === 'backward'
  const members: Feature[] = []
  const byLevel = memberPaths(doc)
  for (const lv of levelOrder(byLevel)) {
    const { colour } = levelStyle(lv)
    for (const m of byLevel[lv]) members.push(line(m.map(p => [p.lon, p.lat]), { level: lv, colour }))
  }
  const central: Feature[] = []
  const points: Feature[] = []
  const marks: Feature[] = []
  const arrows: Feature[] = []
  for (const lv of levelOrder(doc.paths)) {
    const path = doc.paths[lv]
    if (path.length < 2) continue
    const { colour, label } = levelStyle(lv)
    central.push(line(path.map(p => [p.lon, p.lat]), { level: lv, colour }))
    for (const p of path) {
      const age = Math.abs(p.age_h)
      if (age === 0 || age % 6 !== 0) continue
      points.push(point(p.lon, p.lat, {
        level: lv, colour, age_h: age, when: pkt(p.time_utc), height: label, height_m: p.height_agl_m, speed: p.speed_ms,
        region: p.region ?? '', district: p.district ?? '', members: membersOver(doc, lv, age),
      }))
      if (MARK_HOURS.includes(age)) marks.push(point(p.lon, p.lat, { level: lv, label: `${age} h` }))
    }
    // the arrowhead: into the origin for a backward run, at the far end for a forward one
    const [a, b]: [TrajectoryPoint, TrajectoryPoint] = backward ? [path[1], path[0]] : [path[path.length - 2], path[path.length - 1]]
    arrows.push(point(b.lon, b.lat, { level: lv, bearing: bearingDeg(a, b) }))
  }
  const fires = (doc.fires.loose?.points ?? []).map(f => point(f.lon, f.lat, {
    frp: f.frp, district: f.district ?? '', country: f.country === 'PK' ? 'Pakistan' : f.country === 'IN' ? 'India' : f.country, source_class: f.source_class ?? '',
  }))
  const origin = [point(doc.origin.lon, doc.origin.lat, { label: doc.origin.label ?? '' })]
  return { members: fc(members), central: fc(central), points: fc(points), marks: fc(marks), arrows: fc(arrows), fires: fc(fires), origin: fc(origin) }
}

// ── images ───────────────────────────────────────────────────────────────────

const ARROW_PX = 24

function arrowImage(colour: string): { width: number; height: number; data: Uint8Array } {
  const c = document.createElement('canvas')
  c.width = c.height = ARROW_PX
  const ctx = c.getContext('2d')
  if (!ctx) return { width: ARROW_PX, height: ARROW_PX, data: new Uint8Array(ARROW_PX * ARROW_PX * 4) }
  ctx.beginPath()
  ctx.moveTo(12, 1); ctx.lineTo(23, 23); ctx.lineTo(12, 17); ctx.lineTo(1, 23); ctx.closePath()
  ctx.lineJoin = 'round'
  ctx.strokeStyle = '#ffffff'; ctx.lineWidth = 3; ctx.stroke()
  ctx.fillStyle = colour; ctx.fill()
  const d = ctx.getImageData(0, 0, ARROW_PX, ARROW_PX)
  return { width: ARROW_PX, height: ARROW_PX, data: new Uint8Array(d.data.buffer) }
}

function ensureImages(map: mapboxgl.Map) {
  for (const l of LEVELS) {
    const id = `traj-arrow-${l.key}`
    if (!map.hasImage(id)) map.addImage(id, arrowImage(l.colour), { pixelRatio: 2 })
  }
  try { ensureFlame(map) } catch (err) { console.warn('[trajectory] flame icon not added', err) }
}

// ── sources and layers ───────────────────────────────────────────────────────

const SRC = { members: 'traj-members', central: 'traj-central', points: 'traj-points', marks: 'traj-marks', arrows: 'traj-arrows', fires: 'traj-fires', origin: 'traj-origin' } as const
const LEVEL_LAYERS = ['traj-members-line', 'traj-central-casing', 'traj-central-line', 'traj-points', 'traj-arrows'] as const
const TEXT_FONT = ['DIN Pro Medium', 'Arial Unicode MS Regular']
const HALO = { 'text-halo-color': 'rgba(255,255,255,0.95)', 'text-halo-width': 1.6 }

function addLayers(map: mapboxgl.Map, geo: TrajectoryGeo) {
  for (const [key, id] of Object.entries(SRC) as [keyof TrajectoryGeo, string][]) {
    const src = map.getSource(id) as mapboxgl.GeoJSONSource | undefined
    if (src) src.setData(geo[key])
    else map.addSource(id, { type: 'geojson', data: geo[key] })
  }
  if (map.getLayer('traj-members-line')) return
  const add = (layer: Record<string, unknown>) => map.addLayer({ slot: 'top', ...layer } as mapboxgl.AnyLayer)
  add({ id: 'traj-members-line', type: 'line', source: SRC.members, layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: { 'line-color': ['get', 'colour'], 'line-width': 0.9, 'line-opacity': 0.32 } })
  add({ id: 'traj-fires-glow', type: 'circle', source: SRC.fires,
    paint: { 'circle-color': '#fb923c', 'circle-opacity': 0.22, 'circle-blur': 1, 'circle-radius': ['interpolate', ['linear'], ['zoom'], 4, 7, 9, 16] } })
  add({ id: 'traj-fires-icon', type: 'symbol', source: SRC.fires,
    layout: { 'icon-image': 'hawa-flame', 'icon-anchor': 'bottom', 'icon-allow-overlap': true, 'icon-ignore-placement': true,
      'icon-size': ['interpolate', ['linear'], ['zoom'], 4, ['interpolate', ['linear'], ['get', 'frp'], 0, 0.22, 50, 0.3, 200, 0.4], 9, ['interpolate', ['linear'], ['get', 'frp'], 0, 0.4, 50, 0.55, 200, 0.75]],
      'symbol-sort-key': ['*', -1, ['get', 'frp']] } })
  add({ id: 'traj-central-casing', type: 'line', source: SRC.central, layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: { 'line-color': '#ffffff', 'line-width': 5, 'line-opacity': 0.85 } })
  add({ id: 'traj-central-line', type: 'line', source: SRC.central, layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: { 'line-color': ['get', 'colour'], 'line-width': 2.6 } })
  add({ id: 'traj-points', type: 'circle', source: SRC.points,
    paint: { 'circle-color': ['get', 'colour'], 'circle-radius': ['interpolate', ['linear'], ['zoom'], 4, 2.4, 9, 4.5], 'circle-stroke-color': '#ffffff', 'circle-stroke-width': 1 } })
  add({ id: 'traj-arrows', type: 'symbol', source: SRC.arrows,
    layout: { 'icon-image': ['concat', 'traj-arrow-', ['get', 'level']], 'icon-rotate': ['get', 'bearing'], 'icon-rotation-alignment': 'map',
      'icon-size': 0.9, 'icon-allow-overlap': true, 'icon-ignore-placement': true } })
  add({ id: 'traj-marks', type: 'symbol', source: SRC.marks,
    layout: { 'text-field': ['get', 'label'], 'text-font': TEXT_FONT, 'text-size': 11, 'text-anchor': 'bottom-left', 'text-offset': [0.5, -0.4], 'text-allow-overlap': true },
    paint: { 'text-color': '#334155', ...HALO } })
  add({ id: 'traj-origin', type: 'circle', source: SRC.origin,
    paint: { 'circle-color': '#0f172a', 'circle-radius': 5, 'circle-stroke-color': '#ffffff', 'circle-stroke-width': 2 } })
  add({ id: 'traj-origin-label', type: 'symbol', source: SRC.origin,
    layout: { 'text-field': ['get', 'label'], 'text-font': TEXT_FONT, 'text-size': 12.5, 'text-anchor': 'left', 'text-offset': [0.8, 0], 'text-allow-overlap': true },
    paint: { 'text-color': '#0f172a', ...HALO } })
}

const popupStyle = 'font-family:system-ui,-apple-system,sans-serif;font-size:12px;line-height:1.45;color:#0f172a'

function pointHtml(p: Record<string, unknown>, backward: boolean): string {
  const where = [p.district, p.region].filter(Boolean).map(esc).join(', ')
  return `<div style="${popupStyle}">
    <div style="font-weight:600;color:${esc(p.colour)}">${esc(p.age_h)} h ${backward ? 'before arrival' : 'after departure'}<span style="font-weight:500;color:#64748b"> · ${esc(p.height)}</span></div>
    <div style="color:#475569">${esc(p.when)}</div>
    ${where ? `<div>Over <b>${where}</b></div>` : ''}
    ${p.speed != null && p.speed !== '' ? `<div>Wind <b>${esc(p.speed)} m/s</b></div>` : ''}
    ${p.members ? `<div style="color:#64748b;font-size:11px;margin-top:2px">Members here: ${esc(p.members)}</div>` : ''}
  </div>`
}

function fireHtml(p: Record<string, unknown>): string {
  return `<div style="${popupStyle}">
    <div style="font-weight:600;color:${FIRE_COLOUR}">Fire detection<span style="font-weight:500;color:#64748b"> · ${esc(p.country)}</span></div>
    ${p.district ? `<div>${esc(p.district)}</div>` : ''}
    <div>FRP <b>${esc(p.frp)} MW</b> <span style="color:#94a3b8">(burning intensity, not PM2.5)</span></div>
    ${p.source_class ? `<div style="color:#64748b;font-size:11px">Class: ${esc(p.source_class)}</div>` : ''}
    <div style="color:#64748b;font-size:11px;margin-top:2px">Within 25 km and 3 h of the path</div>
  </div>`
}

const hovered = new WeakSet<mapboxgl.Map>()

function addPopups(map: mapboxgl.Map, backward: boolean) {
  if (hovered.has(map)) return
  hovered.add(map)
  const popup = new mapboxgl.Popup({ closeButton: false, closeOnClick: false, maxWidth: '240px', className: 'pointer-events-none' })
  const show = (layer: string, html: (p: Record<string, unknown>) => string) => {
    map.on('mouseenter', layer, e => {
      const f = e.features?.[0]
      if (!f) return
      map.getCanvas().style.cursor = 'pointer'
      const coords = (f.geometry as GeoJSON.Point).coordinates.slice() as [number, number]
      popup.setLngLat(coords).setHTML(html((f.properties ?? {}) as Record<string, unknown>)).addTo(map)
    })
    map.on('mouseleave', layer, () => { map.getCanvas().style.cursor = ''; popup.remove() })
  }
  show('traj-points', p => pointHtml(p, backward))
  show('traj-fires-icon', fireHtml)
}

/** Draws the document on the map once it has loaded and keeps the level filter in step with `visible`. */
export function useTrajectoryLayers(map: mapboxgl.Map | null, loaded: boolean, doc: TrajectoryDoc | undefined, visible: string[]) {
  useEffect(() => {
    if (!map || !loaded || !doc) return
    try {
      ensureImages(map)
      addLayers(map, trajectoryGeo(doc))
      addPopups(map, doc.direction === 'backward')
    } catch (err) {
      console.warn('[trajectory] layers not added', err)
    }
  }, [map, loaded, doc])

  useEffect(() => {
    if (!map || !loaded || !map.getLayer('traj-members-line')) return
    const filter = ['in', ['get', 'level'], ['literal', visible]] as unknown as mapboxgl.FilterSpecification
    for (const id of LEVEL_LAYERS) map.setFilter(id, filter)
    const markLevel = visible.includes('925') ? '925' : visible[0] ?? '925'
    map.setFilter('traj-marks', ['==', ['get', 'level'], markLevel] as unknown as mapboxgl.FilterSpecification)
  }, [map, loaded, doc, visible])
}
