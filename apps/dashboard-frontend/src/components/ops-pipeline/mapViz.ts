'use client'

/**
 * Map layers added in the redesign, one hook each. Every hook owns its sources and layers and
 * works on the map PredictionMap already created.
 *
 *  - useBasemapTuning      muted monochrome basemap, light hillshade, larger city labels
 *  - useSmokeOutlook       tomorrow's smoke outlook band per city, with the 850 hPa wind (fire report §9)
 *  - useOutlookCone        a city's upwind cone for one outlook lead
 *  - useHeatSources        persistent heat sources as a larger glowing flame, a flag for investigation (fire report §8.4)
 *  - useSmokePlumes        illustrative smoke plumes: thin lines downwind of fire groups, on the latest winds
 *  - useFireAnimation      active fires as flame icons that pop up, over a flickering glow
 *  - useEstimateSurface    the satellite PM2.5 estimate in the air-quality colour map: smooth far out, square cells zoomed in
 *  - useCitySurfaces       the 1 km city layers, same colours
 *  - useEstimateReplay     the replay's continuous day-to-day blend of the estimate
 */

import { useEffect, useRef, useState } from 'react'
import mapboxgl from 'mapbox-gl'
import { MAJOR_CITIES } from '@/lib/mapviz/cities'
import { cachedGridImage, estimateKey, predictionRaster, renderGridImage, type GridImage } from '@/lib/mapviz/gridImage'
import { CITY_RANGE, SURFACE_RANGE } from '@/lib/turbo'

const API_BASE_VIZ = process.env.NEXT_PUBLIC_API_URL ?? ''
import { esc } from '@/lib/html'
import { bandColor, bandKey } from '@/lib/aqi'
import { driftPath, loadWindField, type WindField } from '@/lib/mapviz/wind'

type Map = mapboxgl.Map

// ─────────────────────────────────────────────────────────────────────────────
// Basemap: monochrome Standard theme, a light hillshade, and our own city labels
// ─────────────────────────────────────────────────────────────────────────────
export function useBasemapTuning(map: Map | null, loaded: boolean) {
  useEffect(() => {
    if (!map || !loaded) return
    // Mapbox Standard basemap (when the style imports it): greyscale, fewer points of interest
    try {
      const imports = (map.getStyle() as { imports?: { id: string }[] } | undefined)?.imports ?? []
      const basemap = imports.find(i => i.id === 'basemap')?.id
      if (basemap) {
        map.setConfigProperty(basemap, 'theme', 'monochrome')
        map.setConfigProperty(basemap, 'showPointOfInterestLabels', false)
      }
    } catch (err) {
      console.warn('[basemap] config not applied', err)
    }

    try {
      if (!map.getSource('hawa-dem')) {
        map.addSource('hawa-dem', { type: 'raster-dem', url: 'mapbox://mapbox.mapbox-terrain-dem-v1', tileSize: 512, maxzoom: 12 })
      }
      if (!map.getLayer('hawa-hillshade')) {
        map.addLayer({
          id: 'hawa-hillshade', type: 'hillshade', source: 'hawa-dem', slot: 'bottom',
          paint: {
            'hillshade-exaggeration': ['interpolate', ['linear'], ['zoom'], 4, 0.25, 8, 0.4, 12, 0.3],
            'hillshade-shadow-color': '#334155',
            'hillshade-highlight-color': '#ffffff',
            'hillshade-accent-color': '#475569',
          },
        } as mapboxgl.AnyLayer)
      }
    } catch (err) {
      console.warn('[basemap] hillshade not added', err)
    }

    if (!map.getSource('hawa-cities')) {
      map.addSource('hawa-cities', {
        type: 'geojson',
        data: {
          type: 'FeatureCollection',
          features: MAJOR_CITIES.map(c => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [c.lon, c.lat] }, properties: { name: c.name, rank: c.rank } })),
        },
      })
      map.addLayer({
        id: 'hawa-cities', type: 'symbol', source: 'hawa-cities', slot: 'top',
        filter: ['<=', ['get', 'rank'], ['step', ['zoom'], 1, 5.6, 2]],
        layout: {
          'text-field': ['get', 'name'],
          'text-font': ['DIN Pro Medium', 'Arial Unicode MS Regular'],
          'text-size': ['interpolate', ['linear'], ['zoom'], 4, ['match', ['get', 'rank'], 1, 12, 11], 8, ['match', ['get', 'rank'], 1, 16, 13.5]],
          'text-anchor': 'top',
          'text-offset': [0, 0.9],
          'text-letter-spacing': 0.02,
          'text-max-width': 8,
        },
        paint: {
          'text-color': '#0f172a',
          'text-halo-color': 'rgba(255,255,255,0.95)',
          'text-halo-width': 1.6,
          'text-halo-blur': 0.4,
          'text-opacity': ['interpolate', ['linear'], ['zoom'], 9.5, 1, 10.5, 0],
        },
      } as mapboxgl.AnyLayer)
    }
  }, [map, loaded])
}

// ─────────────────────────────────────────────────────────────────────────────
// Smoke outlook (fire report §9): each city coloured by tomorrow's upwind fire load band, with an
// arrow on the 850 hPa wind. Forecast wind × current fires; fires assumed to persist; not a PM2.5
// forecast. Clicking a city opens its card; its upwind cone is drawn by useOutlookCone.
// ─────────────────────────────────────────────────────────────────────────────
export const OUTLOOK_BANDS = ['low', 'elevated', 'high', 'very_high'] as const
export type OutlookBandKey = 'none' | (typeof OUTLOOK_BANDS)[number]
export const OUTLOOK_BAND_COLOR: Record<OutlookBandKey, string> = {
  none: '#cbd5e1',
  low: '#facc15',
  elevated: '#f97316',
  high: '#dc2626',
  very_high: '#7f1d1d',
}
export const OUTLOOK_BAND_LABEL: Record<OutlookBandKey, string> = {
  none: 'None', low: 'Low', elevated: 'Elevated', high: 'High', very_high: 'Very high',
}

const COMPASS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
export const compassDeg = (c: string | null | undefined): number | null => {
  const i = c ? COMPASS.indexOf(c.toUpperCase()) : -1
  return i < 0 ? null : i * 22.5
}

/** The outlook's city dots appear from this zoom (about a province on screen), keeping the country view clear. */
const OUTLOOK_MIN_ZOOM = 6

export interface OutlookCityPoint { city: string; lat: number; lon: number; band: OutlookBandKey; load: number; fromCompass: string | null }

/** An arrow pointing "up", as an SDF so the map can colour it. */
function arrowImage(): { width: number; height: number; data: Uint8Array } {
  const S = 40
  const c = document.createElement('canvas')
  c.width = S; c.height = S
  const ctx = c.getContext('2d')!
  ctx.fillStyle = '#000'; ctx.strokeStyle = '#000'; ctx.lineWidth = 4; ctx.lineCap = 'round'
  ctx.beginPath(); ctx.moveTo(S / 2, S - 6); ctx.lineTo(S / 2, 13); ctx.stroke()
  ctx.beginPath(); ctx.moveTo(S / 2, 3); ctx.lineTo(S / 2 - 8, 15); ctx.lineTo(S / 2 + 8, 15); ctx.closePath(); ctx.fill()
  const d = ctx.getImageData(0, 0, S, S)
  return { width: S, height: S, data: new Uint8Array(d.data.buffer) }
}

export function useSmokeOutlook(map: Map | null, loaded: boolean, opts: { cities: OutlookCityPoint[]; enabled: boolean; selected: string | null; onSelect: (city: string) => void }) {
  const { cities, enabled, selected, onSelect } = opts
  const onSelectRef = useRef(onSelect)
  onSelectRef.current = onSelect

  useEffect(() => {
    if (!map || !loaded) return
    if (!map.getSource('hawa-outlook')) {
      if (!map.hasImage('hawa-outlook-arrow')) map.addImage('hawa-outlook-arrow', arrowImage(), { sdf: true, pixelRatio: 2 })
      map.addSource('hawa-outlook', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
      const bandColor: mapboxgl.Expression = ['match', ['get', 'band'], 'low', OUTLOOK_BAND_COLOR.low, 'elevated', OUTLOOK_BAND_COLOR.elevated, 'high', OUTLOOK_BAND_COLOR.high, 'very_high', OUTLOOK_BAND_COLOR.very_high, OUTLOOK_BAND_COLOR.none]
      const bandRank: mapboxgl.Expression = ['match', ['get', 'band'], 'low', 1, 'elevated', 2, 'high', 3, 'very_high', 4, 0]
      // The arrow sits upwind of the city and points at it: where tomorrow's smoke would come from
      map.addLayer({
        id: 'hawa-outlook-arrow', type: 'symbol', source: 'hawa-outlook', slot: 'top', minzoom: OUTLOOK_MIN_ZOOM,
        filter: ['all', ['>', bandRank, 0], ['has', 'to_deg']],
        layout: {
          'icon-image': 'hawa-outlook-arrow',
          'icon-rotate': ['get', 'to_deg'],
          'icon-rotation-alignment': 'map',
          'icon-offset': [0, 26],
          'icon-size': ['interpolate', ['linear'], ['zoom'], 4, 0.5, 8, 0.75],
          'icon-allow-overlap': true,
          'icon-ignore-placement': true,
        },
        paint: { 'icon-color': bandColor, 'icon-opacity': 0.9 },
      } as mapboxgl.AnyLayer)
      map.addLayer({
        id: 'hawa-outlook-city', type: 'circle', source: 'hawa-outlook', slot: 'top', minzoom: OUTLOOK_MIN_ZOOM,
        filter: ['>', bandRank, 0],
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 4, ['+', 3, bandRank], 8, ['+', 5, ['*', 1.6, bandRank]]],
          'circle-color': bandColor,
          'circle-stroke-color': ['case', ['boolean', ['get', 'selected'], false], '#0f172a', '#ffffff'],
          'circle-stroke-width': ['case', ['boolean', ['get', 'selected'], false], 2.5, 1.5],
          'circle-opacity': 0.95,
        },
      } as mapboxgl.AnyLayer)
      map.addLayer({
        id: 'hawa-outlook-label', type: 'symbol', source: 'hawa-outlook', slot: 'top', minzoom: OUTLOOK_MIN_ZOOM,
        filter: ['any', ['>=', bandRank, 3], ['boolean', ['get', 'selected'], false]],
        layout: {
          'text-field': ['get', 'city'],
          'text-font': ['DIN Pro Medium', 'Arial Unicode MS Regular'],
          'text-size': ['interpolate', ['linear'], ['zoom'], 4, 10.5, 8, 13],
          'text-anchor': 'left',
          'text-offset': [0.9, 0],
          'text-optional': true,
        },
        paint: { 'text-color': '#7f1d1d', 'text-halo-color': 'rgba(255,255,255,0.95)', 'text-halo-width': 1.5 },
      } as mapboxgl.AnyLayer)
      map.on('click', 'hawa-outlook-city', (e) => {
        const city = e.features?.[0]?.properties?.city
        if (city) onSelectRef.current(String(city))
      })
      map.on('mouseenter', 'hawa-outlook-city', () => { map.getCanvas().style.cursor = 'pointer' })
      map.on('mouseleave', 'hawa-outlook-city', () => { map.getCanvas().style.cursor = '' })
    }
    const vis = enabled ? 'visible' : 'none'
    for (const id of ['hawa-outlook-arrow', 'hawa-outlook-city', 'hawa-outlook-label']) map.setLayoutProperty(id, 'visibility', vis)
    ;(map.getSource('hawa-outlook') as mapboxgl.GeoJSONSource).setData({
      type: 'FeatureCollection',
      features: cities.map(c => {
        const from = compassDeg(c.fromCompass)
        return {
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [c.lon, c.lat] },
          properties: { city: c.city, band: c.band, load: c.load, selected: c.city === selected, ...(from != null ? { to_deg: (from + 180) % 360 } : {}) },
        }
      }),
    })
  }, [map, loaded, cities, enabled, selected])
}

/** A city's upwind cone for one outlook lead: ±60° around the 850 hPa wind-from direction, out to the reach, with its strongest fires. */
export function useOutlookCone(map: Map | null, loaded: boolean, cone: { lon: number; lat: number; fromDeg: number; radiusKm: number; color: string; fires: { lon: number; lat: number }[] } | null) {
  useEffect(() => {
    if (!map || !loaded) return
    if (!map.getSource('hawa-cone')) {
      map.addSource('hawa-cone', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
      map.addSource('hawa-cone-fires', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
      map.addLayer({ id: 'hawa-cone-fill', type: 'fill', source: 'hawa-cone', slot: 'top', paint: { 'fill-color': ['get', 'color'], 'fill-opacity': 0.12 } } as mapboxgl.AnyLayer)
      map.addLayer({ id: 'hawa-cone-line', type: 'line', source: 'hawa-cone', slot: 'top', paint: { 'line-color': ['get', 'color'], 'line-width': 1.5, 'line-dasharray': [2, 1.5], 'line-opacity': 0.8 } } as mapboxgl.AnyLayer)
      map.addLayer({
        id: 'hawa-cone-fires', type: 'circle', source: 'hawa-cone-fires', slot: 'top',
        paint: { 'circle-radius': 7, 'circle-color': 'transparent', 'circle-stroke-color': '#0f172a', 'circle-stroke-width': 1.8 },
      } as mapboxgl.AnyLayer)
    }
    const empty: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] }
    if (!cone) {
      ;(map.getSource('hawa-cone') as mapboxgl.GeoJSONSource).setData(empty)
      ;(map.getSource('hawa-cone-fires') as mapboxgl.GeoJSONSource).setData(empty)
      return
    }
    const ring: number[][] = [[cone.lon, cone.lat]]
    const kmLat = 110.57, kmLon = 111.32 * Math.cos((cone.lat * Math.PI) / 180)
    for (let a = -60; a <= 60; a += 4) {
      const b = ((cone.fromDeg + a) * Math.PI) / 180 // compass bearing from the city toward the wind's source
      ring.push([cone.lon + (Math.sin(b) * cone.radiusKm) / kmLon, cone.lat + (Math.cos(b) * cone.radiusKm) / kmLat])
    }
    ring.push([cone.lon, cone.lat])
    ;(map.getSource('hawa-cone') as mapboxgl.GeoJSONSource).setData({
      type: 'FeatureCollection',
      features: [{ type: 'Feature', geometry: { type: 'Polygon', coordinates: [ring] }, properties: { color: cone.color } }],
    })
    ;(map.getSource('hawa-cone-fires') as mapboxgl.GeoJSONSource).setData({
      type: 'FeatureCollection',
      features: cone.fires.map(f => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [f.lon, f.lat] }, properties: {} })),
    })
  }, [map, loaded, cone])
}

// ─────────────────────────────────────────────────────────────────────────────
// Persistent heat sources (fire report §8.4, §7): cells burning on 10 or more of the last 30 days.
// Kilns, flares, landfills and industry rather than field burns: a flag for investigation only;
// they stay in every count.
// ─────────────────────────────────────────────────────────────────────────────
export interface HeatSource { lat: number; lon: number; days_active: number; night_share: number | null; district: string | null; country: string | null; frp_mean_mw: number | null }

export function useHeatSources(map: Map | null, loaded: boolean, opts: { rows: HeatSource[]; enabled: boolean; windowDays: number }) {
  const { rows, enabled, windowDays } = opts
  useEffect(() => {
    if (!map || !loaded) return
    if (!map.getSource('hawa-heat')) {
      map.addSource('hawa-heat', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
      // A soft glow, then a flame a little bigger than an active fire's
      map.addLayer({
        id: 'hawa-heat-glow', type: 'circle', source: 'hawa-heat', slot: 'top',
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 4, 9, 9, 20],
          'circle-color': '#fb923c',
          'circle-opacity': 0.38,
          'circle-blur': 1,
        },
      } as mapboxgl.AnyLayer)
      ensureFlame(map)
      map.addLayer({
        id: 'hawa-heat', type: 'symbol', source: 'hawa-heat', slot: 'top',
        layout: {
          'icon-image': 'hawa-flame',
          'icon-size': ['interpolate', ['linear'], ['zoom'], 4, 0.36, 8, 0.6, 12, 1],
          'icon-anchor': 'bottom',
          'icon-offset': [0, 2],
          'icon-allow-overlap': true,
          'icon-ignore-placement': true,
        },
      } as mapboxgl.AnyLayer)
      const popup = new mapboxgl.Popup({ closeButton: false, closeOnClick: false, maxWidth: '240px', className: 'pointer-events-none' })
      map.on('mouseenter', 'hawa-heat', (e) => {
        const f = e.features?.[0]
        if (!f) return
        const p = f.properties as Record<string, unknown>
        const night = p.night_share != null && p.night_share !== 'null' ? `, ${Math.round(Number(p.night_share) * 100)}% at night` : ''
        const where = [p.district, p.country].filter(v => v && v !== 'null').join(', ')
        popup.setLngLat((f.geometry as GeoJSON.Point).coordinates as [number, number]).setHTML(`
          <div style="font-family:system-ui,-apple-system,sans-serif;font-size:12px;line-height:1.5">
            <div style="font-weight:600;color:#c2410c;margin-bottom:2px">Persistent heat source</div>
            <div>Burning on <b>${esc(p.days_active)}</b> of the last ${esc(p.window_days)} days${night}</div>
            ${where ? `<div style="color:#475569">${esc(where)}</div>` : ''}
            <div style="color:#64748b;font-size:11px;margin-top:2px">Likely a kiln, flare, landfill or industry rather than a field burn. A flag for investigation; it stays in every count.</div>
          </div>`).addTo(map)
      })
      map.on('mouseleave', 'hawa-heat', () => popup.remove())
    }
    for (const id of ['hawa-heat-glow', 'hawa-heat']) map.setLayoutProperty(id, 'visibility', enabled ? 'visible' : 'none')
    ;(map.getSource('hawa-heat') as mapboxgl.GeoJSONSource).setData({
      type: 'FeatureCollection',
      features: rows.map(r => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [r.lon, r.lat] }, properties: { ...r, window_days: windowDays } })),
    })
  }, [map, loaded, rows, enabled, windowDays])
}

// ─────────────────────────────────────────────────────────────────────────────
// Smoke plumes: from each group of fires, a thin smooth line downwind over about 18 hours of travel on the
// latest surface winds, deep orange at the fire fading to pale yellow, with a small dot where it starts.
// Drawn like trajectory bundles. Illustrative only: where smoke may drift, not a dispersion model (the fire
// report has no plume model in its operational path).
// ─────────────────────────────────────────────────────────────────────────────
const PLUME_HOURS = 18
const PLUME_CELL_DEG = 0.1
const PLUME_MAX_LINES = 220

/** Fires grouped on a PLUME_CELL_DEG grid; groups of at least `min` become plume sources, strongest first. */
function fireClusters(fires: { geometry: { coordinates: number[] }; properties?: { frp?: number | string | null } | null }[], min = 2) {
  const cells = new Map<string, { x: number; y: number; n: number }>()
  for (const f of fires) {
    const [lon, lat] = f.geometry.coordinates
    if (!Number.isFinite(lon) || !Number.isFinite(lat)) continue
    const key = `${Math.floor(lon / PLUME_CELL_DEG)},${Math.floor(lat / PLUME_CELL_DEG)}`
    const c = cells.get(key) ?? { x: 0, y: 0, n: 0 }
    c.x += lon; c.y += lat; c.n += 1
    cells.set(key, c)
  }
  return [...cells.values()].filter(c => c.n >= min).sort((a, b) => b.n - a.n).slice(0, PLUME_MAX_LINES)
    .map(c => ({ lon: c.x / c.n, lat: c.y / c.n, count: c.n }))
}

/** Chaikin corner cutting: turns the hourly drift points into a smooth curve. */
function smoothPath(pts: [number, number][], rounds = 3): [number, number][] {
  let p = pts
  for (let r = 0; r < rounds && p.length > 2; r++) {
    const out: [number, number][] = [p[0]]
    for (let i = 0; i < p.length - 1; i++) {
      const [x0, y0] = p[i], [x1, y1] = p[i + 1]
      out.push([0.75 * x0 + 0.25 * x1, 0.75 * y0 + 0.25 * y1], [0.25 * x0 + 0.75 * x1, 0.25 * y0 + 0.75 * y1])
    }
    out.push(p[p.length - 1])
    p = out
  }
  return p
}

// Plumes fade out between these zooms: they read at country and province scale, not over a city
const PLUME_FADE_ZOOM: [number, number] = [7, 8]
// Marching dashes (Mapbox's line-dash animation): each step moves the dashes a little further along the line
const DASH_STEPS: number[][] = [
  [0, 4, 3], [0.5, 4, 2.5], [1, 4, 2], [1.5, 4, 1.5], [2, 4, 1], [2.5, 4, 0.5], [3, 4, 0],
  [0, 0.5, 3, 3.5], [0, 1, 3, 3], [0, 1.5, 3, 2.5], [0, 2, 3, 2], [0, 2.5, 3, 1.5], [0, 3, 3, 1], [0, 3.5, 3, 0.5],
]

/**
 * `pm25At` gives the PM2.5 at a point (the satellite estimate, else the nearest station); each plume is coloured
 * by the AQI band of the PM2.5 along its path: the air the smoke is moving into, not a measure of what the fires
 * themselves add (fire power is never a PM2.5 contribution).
 */
export function useSmokePlumes(map: Map | null, loaded: boolean, opts: { fires: { geometry: { coordinates: number[] }; properties?: { frp?: number | string | null } | null }[]; enabled: boolean; pm25At?: (lon: number, lat: number) => number | null }) {
  const { fires, enabled, pm25At } = opts
  const [field, setField] = useState<WindField | null>(null)
  const grown = useRef(false)
  useEffect(() => {
    if (!enabled || field) return
    let alive = true
    loadWindField().then(f => { if (alive) setField(f) })
    return () => { alive = false }
  }, [enabled, field])

  useEffect(() => {
    if (!map || !loaded) return
    if (!map.getSource('hawa-plume-lines')) {
      map.addSource('hawa-plume-lines', { type: 'geojson', data: { type: 'FeatureCollection', features: [] }, lineMetrics: true })
      map.addSource('hawa-plume-src', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
      const [z0, z1] = PLUME_FADE_ZOOM
      const width = (k: number): mapboxgl.Expression => ['interpolate', ['linear'], ['zoom'],
        4, ['interpolate', ['linear'], ['get', 'count'], 2, 0.7 * k, 20, 1.1 * k, 60, 1.5 * k],
        z1, ['interpolate', ['linear'], ['get', 'count'], 2, 1 * k, 20, 1.6 * k, 60, 2.2 * k]]
      // A faint full-length line, then flowing dashes in the same colour on top
      map.addLayer({
        id: 'hawa-plume-lines', type: 'line', source: 'hawa-plume-lines', slot: 'top', maxzoom: z1 + 0.01,
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: {
          'line-color': ['get', 'color'],
          'line-width': width(1),
          'line-opacity': ['interpolate', ['linear'], ['zoom'], 4, 0.32, z0, 0.3, z1, 0],
          'line-trim-offset': [0, 0],
        },
      } as mapboxgl.AnyLayer)
      map.addLayer({
        id: 'hawa-plume-flow', type: 'line', source: 'hawa-plume-lines', slot: 'top', maxzoom: z1 + 0.01,
        layout: { 'line-cap': 'butt', 'line-join': 'round' },
        paint: {
          'line-color': ['get', 'color'],
          'line-width': width(1.15),
          'line-opacity': ['interpolate', ['linear'], ['zoom'], 4, 0.95, z0, 0.9, z1, 0],
          'line-dasharray': DASH_STEPS[0],
        },
      } as mapboxgl.AnyLayer)
      map.addLayer({
        id: 'hawa-plume-src', type: 'circle', source: 'hawa-plume-src', slot: 'top', maxzoom: z1 + 0.01,
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 4, 2, z1, 3.5],
          'circle-color': '#f4a28c',
          'circle-opacity': ['interpolate', ['linear'], ['zoom'], 4, 0.75, z0, 0.7, z1, 0],
        },
      } as mapboxgl.AnyLayer)
    }
    const ids = ['hawa-plume-lines', 'hawa-plume-flow', 'hawa-plume-src']
    for (const id of ids) map.setLayoutProperty(id, 'visibility', enabled ? 'visible' : 'none')
    if (!enabled) return
    const lines: GeoJSON.Feature[] = []
    const sources: GeoJSON.Feature[] = []
    if (field) {
      for (const c of fireClusters(fires)) {
        const path = driftPath(field, c.lon, c.lat, PLUME_HOURS)
        if (path.length < 4) continue
        // The PM2.5 along the path (skipping the source itself), for the line's AQI colour
        const vals = path.slice(1).map(([x, y]) => pm25At?.(x, y) ?? null).filter((v): v is number => v != null)
        const pm = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null
        lines.push({ type: 'Feature', geometry: { type: 'LineString', coordinates: smoothPath(path) }, properties: { count: c.count, color: pm != null ? bandColor(bandKey(pm)) : '#94a3b8' } })
        sources.push({ type: 'Feature', geometry: { type: 'Point', coordinates: [c.lon, c.lat] }, properties: {} })
      }
    }
    ;(map.getSource('hawa-plume-lines') as mapboxgl.GeoJSONSource).setData({ type: 'FeatureCollection', features: lines })
    ;(map.getSource('hawa-plume-src') as mapboxgl.GeoJSONSource).setData({ type: 'FeatureCollection', features: sources })

    // The lines draw outward from their fires the first time they appear; later updates swap in place
    if (!lines.length || grown.current || prefersReducedMotion()) return
    grown.current = true
    let raf = 0
    const t0 = performance.now()
    const grow = (now: number) => {
      // The first frame's timestamp can fall just before t0, so the progress is kept at or above 0
      const t = Math.max(0, Math.min(1, (now - t0) / 1600))
      const shown = 1 - Math.pow(1 - t, 3)
      if (map.getLayer('hawa-plume-lines')) map.setPaintProperty('hawa-plume-lines', 'line-trim-offset', shown >= 1 ? [0, 0] : [shown, 1])
      if (t < 1) raf = requestAnimationFrame(grow)
    }
    raf = requestAnimationFrame(grow)
    return () => cancelAnimationFrame(raf)
  }, [map, loaded, fires, field, enabled, pm25At])

  // The dashes flow downwind, about 20 steps a second, while the plumes are on and the tab is visible
  useEffect(() => {
    if (!map || !loaded || !enabled || prefersReducedMotion()) return
    let step = 0
    const timer = setInterval(() => {
      if (document.visibilityState === 'hidden' || !map.getLayer('hawa-plume-flow')) return
      if (map.getZoom() > PLUME_FADE_ZOOM[1]) return // nothing to animate once the lines are gone
      step = (step + 1) % DASH_STEPS.length
      map.setPaintProperty('hawa-plume-flow', 'line-dasharray', DASH_STEPS[step])
    }, 55)
    return () => clearInterval(timer)
  }, [map, loaded, enabled])
}

// ─────────────────────────────────────────────────────────────────────────────
// Active fires: flame icons that pop up, over a glow that flickers on its own rhythm
// ─────────────────────────────────────────────────────────────────────────────
const prefersReducedMotion = () =>
  typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

const GLOW_RADIUS: [number, number][] = [[0, 7], [50, 14], [200, 24]]
const byFrp = (stops: [number, number][], k: number): mapboxgl.Expression =>
  ['interpolate', ['linear'], ['to-number', ['get', 'frp'], 0], ...stops.flatMap(([f, r]) => [f, r * k])]

/**
 * The flame icon, drawn on a canvas: a round body with a tall tongue leaning right and a small
 * tongue each side, shaded yellow at the tip through orange to red at the base. Drawn in a
 * 100-unit box and scaled to the 64 px image; a soft shadow lifts it off the map.
 */
const FLAME_START: [number, number] = [50, 100]
const FLAME_SEGS: [number, number, number, number, number, number][] = [
  [32, 100, 18, 87, 18, 71], // bottom-left of the body
  [18, 63, 21, 57, 26, 52], // up to the left tongue's tip
  [28, 58, 32, 63, 38, 65], // into the left notch
  [36, 52, 37, 39, 42, 29], // main tongue, left edge
  [46, 21, 51, 15, 57, 10], // to the main tip
  [56, 24, 59, 40, 65, 54], // main tongue, right edge down to the right notch
  [68, 48, 71, 43, 76, 39], // up to the right tongue's tip
  [82, 47, 82, 58, 82, 71], // right tongue's outer edge into the body
  [82, 87, 68, 100, 50, 100], // bottom-right of the body
]

function flameImage(): { width: number; height: number; data: Uint8Array } {
  const S = 64
  const c = document.createElement('canvas')
  c.width = S; c.height = S
  const ctx = c.getContext('2d')!
  // 100-unit box -> 64 px, with a little room for the shadow
  const k = 0.6, ox = 2, oy = 0
  const X = (x: number) => ox + x * k, Y = (y: number) => oy + y * k
  ctx.beginPath()
  ctx.moveTo(X(FLAME_START[0]), Y(FLAME_START[1]))
  for (const [x1, y1, x2, y2, x, y] of FLAME_SEGS) ctx.bezierCurveTo(X(x1), Y(y1), X(x2), Y(y2), X(x), Y(y))
  ctx.closePath()
  const fill = ctx.createLinearGradient(0, Y(10), 0, Y(100))
  fill.addColorStop(0, '#fcc934')
  fill.addColorStop(0.5, '#f7862a')
  fill.addColorStop(1, '#ec2f25')
  ctx.shadowColor = 'rgba(15,23,42,0.35)'; ctx.shadowBlur = 3; ctx.shadowOffsetY = 1
  ctx.fillStyle = fill
  ctx.fill()
  const d = ctx.getImageData(0, 0, S, S)
  return { width: S, height: S, data: new Uint8Array(d.data.buffer) }
}

/** Adds the flame image once per map. */
export function ensureFlame(map: Map) {
  if (!map.hasImage('hawa-flame')) map.addImage('hawa-flame', flameImage(), { pixelRatio: 2 })
}

// Flame size by zoom and radiative power, scaled by k (the pop-in)
const flameSize = (k: number): mapboxgl.Expression => ['interpolate', ['linear'], ['zoom'],
  4, byFrp([[0, 0.18], [50, 0.24], [200, 0.32]], k),
  8, byFrp([[0, 0.3], [50, 0.4], [200, 0.55]], k),
  12, byFrp([[0, 0.5], [50, 0.65], [200, 0.85]], k),
]

export function useFireAnimation(map: Map | null, loaded: boolean, opts: { enabled: boolean; data: unknown }) {
  const { enabled, data } = opts
  useEffect(() => {
    if (!map || !loaded || !enabled || !map.getLayer('fires-layer') || !map.getLayer('fires-glow')) return
    const layers = () => map.getStyle()?.layers ?? []
    const after = (id: string) => { const l = layers(); return l[l.findIndex(x => x.id === id) + 1]?.id }

    // Three glow groups, each on its own flicker phase, so neighbouring fires do not move together.
    // Only a single opacity number changes per frame (a cheap uniform update, not a per-feature one).
    const bucket: mapboxgl.Expression = ['%', ['floor', ['*', ['to-number', ['get', 'frp'], 0], 10]], 3]
    map.setFilter('fires-glow', ['==', bucket, 0])
    for (const k of [1, 2]) {
      const id = `fires-glow-${k}`
      if (!map.getLayer(id)) {
        map.addLayer({
          id, type: 'circle', source: 'fires', filter: ['==', bucket, k],
          paint: { 'circle-radius': byFrp(GLOW_RADIUS, 1), 'circle-color': '#fb923c', 'circle-opacity': 0.18, 'circle-blur': 1 },
        } as mapboxgl.AnyLayer, 'fires-glow')
      }
      map.setLayoutProperty(id, 'visibility', 'visible')
    }
    map.setPaintProperty('fires-glow', 'circle-color', '#fb923c')

    // The old dot stays as an invisible hover target (the fire hover card listens on it)
    map.setPaintProperty('fires-layer', 'circle-opacity', 0)
    map.setPaintProperty('fires-layer', 'circle-stroke-width', 0)
    map.setPaintProperty('fires-layer', 'circle-radius', byFrp([[0, 6], [50, 9], [200, 13]], 1))

    // The flame icon, directly above the hover target (station markers still draw over it)
    ensureFlame(map)
    if (!map.getLayer('fires-icon')) {
      map.addLayer({
        id: 'fires-icon', type: 'symbol', source: 'fires',
        layout: {
          'icon-image': 'hawa-flame',
          'icon-size': flameSize(1),
          'icon-anchor': 'bottom',
          'icon-offset': [0, 2],
          'icon-allow-overlap': true,
          'icon-ignore-placement': true,
          // Stronger fires draw on top
          'symbol-sort-key': ['to-number', ['get', 'frp'], 0],
        },
        paint: { 'icon-opacity': 1 },
      } as mapboxgl.AnyLayer, after('fires-layer'))
    }
    map.setLayoutProperty('fires-icon', 'visibility', 'visible')
    const glows = ['fires-glow', 'fires-glow-1', 'fires-glow-2']

    // Sizes are data-driven, so they are set once (changing them every frame reloads the fire data);
    // the flames fade in with a single constant opacity instead
    map.setLayoutProperty('fires-icon', 'icon-size', flameSize(1))
    for (const id of glows) map.setPaintProperty(id, 'circle-radius', byFrp(GLOW_RADIUS, 1))
    if (prefersReducedMotion()) { map.setPaintProperty('fires-icon', 'icon-opacity', 1); return }

    map.setPaintProperty('fires-icon', 'icon-opacity', 0)
    let raf = 0
    let last = 0
    let fading = true
    const t0 = performance.now()
    const tick = (now: number) => {
      raf = requestAnimationFrame(tick)
      if (!map.getLayer('fires-icon') || document.visibilityState === 'hidden') return
      const el = Math.max(0, now - t0) / 1000
      if (fading) {
        const t = Math.min(1, el / 0.45)
        map.setPaintProperty('fires-icon', 'icon-opacity', 1 - Math.pow(1 - t, 2))
        if (t >= 1) fading = false
      }
      // Glow flicker at about 12 updates a second
      if (now - last < 80) return
      last = now
      glows.forEach((id, k) => {
        const a = Math.sin(el * 5.2 + k * 2.1) * 0.6 + Math.sin(el * 8.7 + k * 1.3) * 0.4
        map.setPaintProperty(id, 'circle-opacity', 0.17 + 0.08 * a)
      })
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [map, loaded, enabled, data])

  useEffect(() => {
    if (!map || !loaded) return
    for (const id of ['fires-icon', 'fires-glow-1', 'fires-glow-2']) {
      if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', enabled ? 'visible' : 'none')
    }
  }, [map, loaded, enabled])
}

// ─────────────────────────────────────────────────────────────────────────────
// PM2.5 estimate surface, painted in the browser from the model grid (air-quality colour map)
// ─────────────────────────────────────────────────────────────────────────────
type OpacityStops = [number, number][]
const scaledOpacity = (stops: OpacityStops, k: number): mapboxgl.Expression =>
  ['interpolate', ['linear'], ['zoom'], ...stops.flatMap(([z, o]) => [z, o * k])]

export const NATIONAL_OPACITY: OpacityStops = [[3, 0.72], [7, 0.66], [9, 0.42], [12, 0.22]]
const CITY_OPACITY: OpacityStops = [[9, 0], [10, 0.35], [11, 0.55], [13, 0.65], [15, 0.5]]

let countryPolys: Promise<number[][][][]> | null = null
export function loadCountryPolygons(): Promise<number[][][][]> {
  countryPolys ??= fetch('/PAK_adm0.json').then(r => r.json()).then(d => {
    const g = d.features[0].geometry
    return g.type === 'MultiPolygon' ? g.coordinates : [g.coordinates]
  }).catch(() => [])
  return countryPolys
}

/** Calls `done` once an image source has finished loading its picture (or after a safety timeout). */
function whenSourceLoaded(map: Map, id: string, done: () => void): () => void {
  let finished = false
  const finish = () => { if (finished) return; finished = true; map.off('sourcedata', onData); clearTimeout(timer); done() }
  const onData = (e: { sourceId?: string }) => { if (e.sourceId === id && map.isSourceLoaded(id)) finish() }
  map.on('sourcedata', onData)
  const timer = setTimeout(finish, 1500)
  return () => { finished = true; map.off('sourcedata', onData); clearTimeout(timer) }
}

/** Opacity by zoom with every stop's value worked out from the base opacity. */
const opacityStops = (k: (o: number) => number): mapboxgl.Expression =>
  ['interpolate', ['linear'], ['zoom'], ...NATIONAL_OPACITY.flatMap(([z, o]) => [z, Math.max(0, Math.min(1, k(o)))])]

/**
 * The national estimate: two image layers in turn, so a new day fades in over the old one. Each day's picture is
 * painted once (cached by date and model). A fade starts only after the new picture has loaded. While the replay
 * plays this layer rests; when it resumes, the picture loads hidden and appears at full strength in one step
 * (the replay shows the same day until then), and `onResumed` tells the map it can hide the replay.
 */
export function useEstimateSurface(map: Map | null, loaded: boolean, opts: { grid: Parameters<typeof predictionRaster>[0]; visible: boolean; suspended?: boolean; onResumed?: () => void; cells?: boolean }) {
  const { grid, visible, suspended = false, cells = false } = opts
  const shown = useRef<0 | 1 | null>(null)
  const raf = useRef(0)
  const visibleRef = useRef(visible)
  visibleRef.current = visible
  const onResumed = useRef(opts.onResumed)
  onResumed.current = opts.onResumed
  // Each layer's current strength (0 to 1), so a new day blends from where the last fade had reached
  const level = useRef<[number, number]>([0, 0])
  const wasSuspended = useRef(false)

  useEffect(() => {
    if (!map || !loaded) return
    const ids = ['hawa-estimate-0', 'hawa-estimate-1'] as const
    const setLevel = (k: 0 | 1, v: number) => { level.current[k] = v; if (map.getLayer(ids[k])) map.setPaintProperty(ids[k], 'raster-opacity', scaledOpacity(NATIONAL_OPACITY, v)) }
    // While the replay plays, its own layers show the estimate; this one rests
    if (suspended) {
      wasSuspended.current = true
      cancelAnimationFrame(raf.current)
      for (const id of ids) if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', 'none')
      level.current = [0, 0]
      return
    }
    const raster = predictionRaster(grid)
    // No estimate for this day (the request failed or the day has none): fade out rather than keep the last day
    if (!raster) {
      if (grid === null && shown.current !== null) {
        cancelAnimationFrame(raf.current)
        const from: [number, number] = [level.current[0], level.current[1]]
        const t0 = performance.now()
        const step = (now: number) => {
          const t = Math.max(0, Math.min(1, (now - t0) / 400))
          setLevel(0, from[0] * (1 - t)); setLevel(1, from[1] * (1 - t))
          if (t < 1) raf.current = requestAnimationFrame(step)
        }
        raf.current = requestAnimationFrame(step)
      }
      return
    }
    let cancelled = false
    let stopWaiting: (() => void) | null = null
    loadCountryPolygons().then(clip => {
      if (cancelled) return
      // Smooth (blended between cells) at country zoom; square cells, the grid's real ~10 km resolution, zoomed in
      const key = estimateKey(grid as { date?: string; model?: string } | null)
      const image = cachedGridImage(key && (cells ? `${key}:cells` : key), () => renderGridImage(raster, SURFACE_RANGE, { scale: 5, clip, nearest: cells }))
      if (!image || cancelled) return
      // The fainter of the two layers takes the new day, so nothing on screen jumps
      const next: 0 | 1 = level.current[0] <= level.current[1] ? 0 : 1
      const other: 0 | 1 = next === 0 ? 1 : 0
      const id = ids[next], otherId = ids[other]
      const src = map.getSource(id) as mapboxgl.ImageSource | undefined
      if (src) src.updateImage(image)
      else {
        map.addSource(id, { type: 'image', ...image })
        map.addLayer({
          id, type: 'raster', source: id, slot: 'middle',
          layout: { visibility: 'none' },
          paint: { 'raster-opacity': 0, 'raster-resampling': 'linear', 'raster-fade-duration': 0 },
        } as mapboxgl.AnyLayer)
      }
      shown.current = next
      // Square cells keep crisp edges however far you zoom; the smooth picture is smoothed further by the GPU
      map.setPaintProperty(id, 'raster-resampling', cells ? 'nearest' : 'linear')
      const resuming = wasSuspended.current
      wasSuspended.current = false
      setLevel(next, 0)
      map.setLayoutProperty(id, 'visibility', visibleRef.current ? 'visible' : 'none')
      stopWaiting = whenSourceLoaded(map, id, () => {
        if (cancelled) return
        cancelAnimationFrame(raf.current)
        if (resuming) {
          // Back from the replay: the same day appears at full strength at once, and the replay can go
          setLevel(next, 1); setLevel(other, 0)
          if (map.getLayer(otherId)) map.setLayoutProperty(otherId, 'visibility', 'none')
          onResumed.current?.()
          return
        }
        // Crossfade over 800 ms, eased at both ends: the new day in, the other layer out, each from its current strength
        const t0 = performance.now()
        const fromNext = level.current[next], fromOther = level.current[other]
        const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2)
        const step = (now: number) => {
          const t = Math.max(0, Math.min(1, (now - t0) / 800))
          const k = ease(t)
          setLevel(next, fromNext + (1 - fromNext) * k)
          setLevel(other, fromOther * (1 - k))
          if (t < 1) raf.current = requestAnimationFrame(step)
          else if (map.getLayer(otherId)) map.setLayoutProperty(otherId, 'visibility', 'none')
        }
        raf.current = requestAnimationFrame(step)
      })
    })
    return () => { cancelled = true; stopWaiting?.() }
  }, [map, loaded, grid, suspended, cells])

  useEffect(() => {
    if (!map || !loaded || shown.current === null || suspended) return
    const id = `hawa-estimate-${shown.current}`
    if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', visible ? 'visible' : 'none')
  }, [map, loaded, visible, grid, suspended])

  useEffect(() => () => cancelAnimationFrame(raf.current), [])
}

/**
 * The replay's estimate: day i and day i+1 blended in proportion to the playhead (t = i + f), at constant total
 * strength. Day i+1 sits on top at opacity alpha*f and day i beneath at alpha*(1-f)/(1-alpha*f), so the two add up
 * to exactly alpha*(1-f) of day i and alpha*f of day i+1 with no dip or flash part-way. Each day always goes on
 * layer (day % 2), so a layer only takes a new picture when it is fully transparent.
 *
 * `onReady` fires once the first two days' pictures have loaded (the map keeps the normal estimate up until then,
 * so the replay never starts on a blank map). When the replay ends its layers stay as they are until `release`,
 * which the map sets once the normal estimate is back on screen, so the hand-back is seamless.
 */
export function useEstimateReplay(map: Map | null, loaded: boolean, opts: { images: GridImage[] | null; clock: { get(): number; subscribe(fn: () => void): () => void } | null; visible: boolean; release: boolean; onReady?: () => void }) {
  const { images, clock, visible, release } = opts
  const assigned = useRef<[number, number]>([-1, -1])
  const top = useRef<0 | 1 | null>(null)
  const onReady = useRef(opts.onReady)
  onReady.current = opts.onReady

  useEffect(() => {
    if (!map || !loaded) return
    const ids = ['hawa-replay-0', 'hawa-replay-1'] as const
    const hide = () => {
      for (const id of ids) if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', 'none')
      assigned.current = [-1, -1]
      top.current = null
    }
    if (!visible) { hide(); return }
    if (!images?.length || !clock) {
      // Ended: keep the last day on screen until the normal estimate has taken over
      if (release) hide()
      return
    }

    const src = (k: number) => map.getSource(ids[k]) as mapboxgl.ImageSource
    for (const [k, id] of ids.entries()) {
      const first = images[Math.min(k, images.length - 1)]
      if (!map.getSource(id)) {
        map.addSource(id, { type: 'image', ...first })
        map.addLayer({
          id, type: 'raster', source: id, slot: 'middle',
          paint: { 'raster-opacity': 0, 'raster-resampling': 'linear', 'raster-fade-duration': 0 },
        } as mapboxgl.AnyLayer)
      } else {
        map.setPaintProperty(id, 'raster-opacity', 0)
        src(k).updateImage(first)
      }
      map.setLayoutProperty(id, 'visibility', 'visible')
      assigned.current[k] = Math.min(k, images.length - 1)
    }
    top.current = null

    const apply = () => {
      const n = images.length
      const t = Math.max(0, Math.min(n - 1, clock.get()))
      const i = Math.min(n - 1, Math.floor(t))
      const f = i >= n - 1 ? 0 : t - i
      const lo = (i % 2) as 0 | 1, hi = (1 - lo) as 0 | 1
      if (assigned.current[lo] !== i) { src(lo).updateImage(images[i]); assigned.current[lo] = i }
      if (i + 1 < n && assigned.current[hi] !== i + 1) { src(hi).updateImage(images[i + 1]); assigned.current[hi] = i + 1 }
      // Day i+1 goes on top of day i
      if (top.current !== hi) { map.moveLayer(ids[lo], ids[hi]); top.current = hi }
      map.setPaintProperty(ids[lo], 'raster-opacity', opacityStops(o => (o * (1 - f)) / (1 - o * f)))
      map.setPaintProperty(ids[hi], 'raster-opacity', opacityStops(o => o * f))
    }

    // Start blending only once both first pictures are in
    let unsub: (() => void) | null = null
    let pending = 2
    const ready = () => {
      if (--pending > 0) return
      apply()
      onReady.current?.()
      unsub = clock.subscribe(apply)
    }
    const stops = ids.map(id => whenSourceLoaded(map, id, ready))
    return () => { stops.forEach(s => s()); unsub?.() }
  }, [map, loaded, images, clock, visible, release])
}

/** The 1 km city layers (zoom 9 and in), painted with the same colours over their own range. */
export function useCitySurfaces(map: Map | null, loaded: boolean, opts: { cities: { key: string; bounds: [number, number, number, number] }[]; date: string; visible: boolean }) {
  const { cities, date, visible } = opts
  const visibleRef = useRef(visible)
  visibleRef.current = visible

  useEffect(() => {
    if (!map || !loaded) return
    const requested = new Set<string>()
    let cancelled = false
    const load = () => {
      if (map.getZoom() < 8.4) return
      const b = map.getBounds()
      if (!b) return
      for (const c of cities) {
        const [w, s, e, n] = c.bounds
        if (requested.has(c.key) || e < b.getWest() || w > b.getEast() || n < b.getSouth() || s > b.getNorth()) continue
        requested.add(c.key)
        fetch(`${API_BASE_VIZ}/api/v1/ops/downscaler/grid/${c.key}/${date}`)
          .then(r => (r.ok ? r.json() : null))
          .then(d => {
            if (cancelled || !d?.pm25?.length || !d.grid?.shape || !d.grid?.bounds) return
            const [rows, cols] = d.grid.shape
            const bb = d.grid.bounds
            const image = renderGridImage({ values: d.pm25, rows, cols, west: bb.west, south: bb.south, east: bb.east, north: bb.north, points: false }, CITY_RANGE, { scale: 6, maxWidth: 900 })
            if (!image) return
            const id = `hawa-city-${c.key}`
            const src = map.getSource(id) as mapboxgl.ImageSource | undefined
            if (src) src.updateImage(image)
            else {
              map.addSource(id, { type: 'image', ...image })
              map.addLayer({
                id, type: 'raster', source: id, slot: 'middle', minzoom: 9,
                paint: { 'raster-opacity': scaledOpacity(CITY_OPACITY, 1), 'raster-resampling': 'linear', 'raster-fade-duration': 0 },
              } as mapboxgl.AnyLayer)
            }
            map.setLayoutProperty(id, 'visibility', visibleRef.current ? 'visible' : 'none')
          })
          .catch(() => {})
      }
    }
    // A new date: each city layer keeps its picture until the new grid arrives and replaces it in place
    load()
    map.on('moveend', load)
    return () => { cancelled = true; map.off('moveend', load) }
  }, [map, loaded, cities, date])

  useEffect(() => {
    if (!map || !loaded) return
    for (const c of cities) {
      const id = `hawa-city-${c.key}`
      if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', visible ? 'visible' : 'none')
    }
  }, [map, loaded, cities, visible])
}
