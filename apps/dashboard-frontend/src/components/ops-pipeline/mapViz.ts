'use client'

/**
 * Map layers added in the redesign, one hook each. Every hook owns its sources and layers and
 * works on the map PredictionMap already created.
 *
 *  - useBasemapTuning      muted monochrome basemap, light hillshade, larger city labels
 *  - useSmokeOutlook       tomorrow's smoke outlook band per city, with the 850 hPa wind (fire report §9)
 *  - useOutlookCone        a city's upwind cone for one outlook lead
 *  - useHeatSources        persistent heat sources as a larger glowing flame, a flag for investigation (fire report §8.4)
 *  - useSmokePlumes        illustrative smoke plumes downwind of fire clusters, on the latest winds
 *  - useFireAnimation      active fires as flame icons that pop up, over a flickering glow
 *  - useEstimateSurface    the satellite PM2.5 estimate, painted from its grid in the air-quality colour map
 *  - useCitySurfaces       the 1 km city layers, same colours
 */

import { useEffect, useRef, useState } from 'react'
import mapboxgl from 'mapbox-gl'
import { MAJOR_CITIES } from '@/lib/mapviz/cities'
import { predictionRaster, renderGridImage } from '@/lib/mapviz/gridImage'
import { CITY_RANGE, SURFACE_RANGE } from '@/lib/turbo'

const API_BASE_VIZ = process.env.NEXT_PUBLIC_API_URL ?? ''
import { esc } from '@/lib/html'
import { driftPath, loadWindField, type WindField } from '@/lib/mapviz/wind'

type Map = mapboxgl.Map

// ─────────────────────────────────────────────────────────────────────────────
// Basemap: monochrome Standard theme, a light hillshade, and our own city labels
// ─────────────────────────────────────────────────────────────────────────────
export interface BasemapOptions {
  /** Mapbox Standard theme; the Tracker is monochrome (the PM2.5 surface carries the colour) */
  theme?: 'monochrome' | 'faded' | 'default'
  /** Show the basemap's own place names (towns the Tracker leaves to its own city labels) */
  placeLabels?: boolean
  /** Zoom from which our rank-2 cities are labelled */
  cityStep?: number
  /** Hillshade strength: 'strong' for a small map at low zoom, where the light default reads as blank */
  relief?: 'light' | 'strong'
}

export function useBasemapTuning(map: Map | null, loaded: boolean, opts: BasemapOptions = {}) {
  const { theme = 'monochrome', placeLabels, cityStep = 5.6, relief = 'light' } = opts
  useEffect(() => {
    if (!map || !loaded) return
    // Mapbox Standard basemap (when the style imports it): greyscale, fewer points of interest
    try {
      const imports = (map.getStyle() as { imports?: { id: string }[] } | undefined)?.imports ?? []
      const basemap = imports.find(i => i.id === 'basemap')?.id
      if (basemap) {
        map.setConfigProperty(basemap, 'theme', theme)
        map.setConfigProperty(basemap, 'showPointOfInterestLabels', false)
        if (placeLabels != null) {
          map.setConfigProperty(basemap, 'showPlaceLabels', placeLabels)
          map.setConfigProperty(basemap, 'showRoadLabels', false)
          map.setConfigProperty(basemap, 'showTransitLabels', false)
        }
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
            'hillshade-exaggeration': relief === 'strong'
              ? ['interpolate', ['linear'], ['zoom'], 4, 0.6, 8, 0.5, 12, 0.35]
              : ['interpolate', ['linear'], ['zoom'], 4, 0.25, 8, 0.4, 12, 0.3],
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
        filter: ['<=', ['get', 'rank'], ['step', ['zoom'], 1, cityStep, 2]],
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
  }, [map, loaded, theme, placeLabels, cityStep, relief])
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
// Smoke plumes: from each cluster of fires, a soft plume that widens, greys and fades downwind over about
// 18 hours of travel on the latest surface winds. Illustrative only: where smoke may drift, not a dispersion
// model (the fire report has no plume model in its operational path).
// ─────────────────────────────────────────────────────────────────────────────
const PLUME_HOURS = 18
const PLUME_STEP_KM = 3

/** Fires grouped on a 0.25° grid; groups of at least `min` become plume sources. */
function fireClusters(fires: { geometry: { coordinates: number[] }; properties?: { frp?: number | string | null } | null }[], min = 2) {
  const cells = new Map<string, { x: number; y: number; n: number }>()
  for (const f of fires) {
    const [lon, lat] = f.geometry.coordinates
    if (!Number.isFinite(lon) || !Number.isFinite(lat)) continue
    const key = `${Math.floor(lon / 0.25)},${Math.floor(lat / 0.25)}`
    const c = cells.get(key) ?? { x: 0, y: 0, n: 0 }
    c.x += lon; c.y += lat; c.n += 1
    cells.set(key, c)
  }
  return [...cells.values()].filter(c => c.n >= min).map(c => ({ lon: c.x / c.n, lat: c.y / c.n, count: c.n }))
}

export function useSmokePlumes(map: Map | null, loaded: boolean, opts: { fires: { geometry: { coordinates: number[] }; properties?: { frp?: number | string | null } | null }[]; enabled: boolean }) {
  const { fires, enabled } = opts
  const [field, setField] = useState<WindField | null>(null)
  useEffect(() => {
    if (!enabled || field) return
    let alive = true
    loadWindField().then(f => { if (alive) setField(f) })
    return () => { alive = false }
  }, [enabled, field])

  useEffect(() => {
    if (!map || !loaded) return
    if (!map.getSource('hawa-plumes')) {
      map.addSource('hawa-plumes', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
      // Circle radius in km on the ground: pixels per km double with each zoom level (about 30°N)
      const kmToPx = 512 / (40075 * 0.87)
      map.addLayer({
        id: 'hawa-plumes', type: 'circle', source: 'hawa-plumes', slot: 'top',
        paint: {
          'circle-radius': ['interpolate', ['exponential', 2], ['zoom'], 0, ['*', ['get', 'rkm'], kmToPx], 16, ['*', ['get', 'rkm'], kmToPx * 65536]],
          'circle-color': ['interpolate', ['linear'], ['get', 'p'], 0, '#c2410c', 0.15, '#57534e', 0.6, '#44403c', 1, '#78716c'],
          'circle-opacity': ['get', 'o'],
          'circle-blur': 1,
          'circle-pitch-alignment': 'map',
        },
      } as mapboxgl.AnyLayer)
    }
    map.setLayoutProperty('hawa-plumes', 'visibility', enabled ? 'visible' : 'none')
    if (!enabled) return
    const feats: GeoJSON.Feature[] = []
    if (field) {
      for (const c of fireClusters(fires)) {
        const path = driftPath(field, c.lon, c.lat, PLUME_HOURS)
        if (path.length < 3) continue
        // Walk the path in even steps; the plume widens and fades with distance
        const seg: number[] = [0]
        const km = (a: number[], b: number[]) => Math.hypot((b[0] - a[0]) * 111.32 * Math.cos((a[1] * Math.PI) / 180), (b[1] - a[1]) * 110.57)
        for (let i = 1; i < path.length; i++) seg.push(seg[i - 1] + km(path[i - 1], path[i]))
        const total = seg[seg.length - 1]
        if (total < PLUME_STEP_KM * 2) continue
        const strength = Math.min(1, c.count / 30)
        let i = 1
        for (let d = 0; d <= total; d += PLUME_STEP_KM) {
          while (i < seg.length - 1 && seg[i] < d) i++
          const t = Math.max(0, Math.min(1, (d - seg[i - 1]) / (seg[i] - seg[i - 1] || 1)))
          const lon = path[i - 1][0] + (path[i][0] - path[i - 1][0]) * t
          const lat = path[i - 1][1] + (path[i][1] - path[i - 1][1]) * t
          const p = d / total
          feats.push({
            type: 'Feature',
            geometry: { type: 'Point', coordinates: [lon, lat] },
            properties: {
              p,
              rkm: (3 + 22 * p) * (0.75 + 0.25 * strength),
              o: 0.6 * (0.6 + 0.4 * strength) * Math.pow(1 - p, 0.9) * Math.min(1, 0.5 + p * 8),
            },
          })
        }
      }
    }
    ;(map.getSource('hawa-plumes') as mapboxgl.GeoJSONSource).setData({ type: 'FeatureCollection', features: feats })
  }, [map, loaded, fires, field, enabled])
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

    if (prefersReducedMotion()) { map.setLayoutProperty('fires-icon', 'icon-size', flameSize(1)); return }

    let raf = 0
    let last = 0
    let popping = true
    const t0 = performance.now()
    const tick = (now: number) => {
      raf = requestAnimationFrame(tick)
      if (!map.getLayer('fires-icon') || document.visibilityState === 'hidden') return
      const el = (now - t0) / 1000
      // Flames pop up with a little overshoot over the first 0.6 s (sizes are set only during the pop)
      if (popping) {
        const t = Math.min(1, el / 0.6)
        const k = t >= 1 ? 1 : 1 + 2.2 * Math.pow(t - 1, 3) + 1.2 * Math.pow(t - 1, 2)
        map.setLayoutProperty('fires-icon', 'icon-size', flameSize(Math.max(0.01, k)))
        for (const id of glows) map.setPaintProperty(id, 'circle-radius', byFrp(GLOW_RADIUS, Math.max(0, k)))
        if (t >= 1) popping = false
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

/**
 * The national estimate: two image layers in turn, so a new day fades in over the old one.
 * `grid` is the prediction endpoint's response for the day and model in view.
 */
export function useEstimateSurface(map: Map | null, loaded: boolean, opts: { grid: Parameters<typeof predictionRaster>[0]; visible: boolean }) {
  const { grid, visible } = opts
  const shown = useRef<0 | 1 | null>(null)
  const raf = useRef(0)
  // Each layer's current strength (0 to 1), so a new day blends from where the last fade had reached
  const level = useRef<[number, number]>([0, 0])
  const visibleRef = useRef(visible)
  visibleRef.current = visible

  useEffect(() => {
    if (!map || !loaded) return
    const raster = predictionRaster(grid)
    if (!raster) return
    let cancelled = false
    loadCountryPolygons().then(clip => {
      if (cancelled) return
      const image = renderGridImage(raster, SURFACE_RANGE, { scale: 5, clip })
      if (!image || cancelled) return
      // The fainter of the two layers takes the new day, so nothing on screen jumps
      const next: 0 | 1 = level.current[0] <= level.current[1] ? 0 : 1
      const other: 0 | 1 = next === 0 ? 1 : 0
      const id = `hawa-estimate-${next}`
      const src = map.getSource(id) as mapboxgl.ImageSource | undefined
      if (src) src.updateImage(image)
      else {
        map.addSource(id, { type: 'image', ...image })
        map.addLayer({
          id, type: 'raster', source: id, slot: 'middle',
          layout: { visibility: 'none' },
          paint: { 'raster-opacity': scaledOpacity(NATIONAL_OPACITY, 0), 'raster-resampling': 'linear', 'raster-fade-duration': 0 },
        } as mapboxgl.AnyLayer)
      }
      shown.current = next
      map.setLayoutProperty(id, 'visibility', visibleRef.current ? 'visible' : 'none')
      // Crossfade over 800 ms, eased at both ends: the new day in, the other layer out, each from its current strength
      cancelAnimationFrame(raf.current)
      const t0 = performance.now()
      const otherId = `hawa-estimate-${other}`
      const fromNext = level.current[next], fromOther = level.current[other]
      const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2)
      const step = (now: number) => {
        const t = Math.min(1, (now - t0) / 800)
        const k = ease(t)
        level.current[next] = fromNext + (1 - fromNext) * k
        level.current[other] = fromOther * (1 - k)
        if (map.getLayer(id)) map.setPaintProperty(id, 'raster-opacity', scaledOpacity(NATIONAL_OPACITY, level.current[next]))
        if (map.getLayer(otherId)) map.setPaintProperty(otherId, 'raster-opacity', scaledOpacity(NATIONAL_OPACITY, level.current[other]))
        if (t < 1) raf.current = requestAnimationFrame(step)
        else if (map.getLayer(otherId)) map.setLayoutProperty(otherId, 'visibility', 'none')
      }
      raf.current = requestAnimationFrame(step)
    })
    return () => { cancelled = true }
  }, [map, loaded, grid])

  useEffect(() => {
    if (!map || !loaded || shown.current === null) return
    const id = `hawa-estimate-${shown.current}`
    if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', visible ? 'visible' : 'none')
  }, [map, loaded, visible, grid])

  useEffect(() => () => cancelAnimationFrame(raf.current), [])
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
    // A new date: hide the old city layers until their new grids arrive
    for (const c of cities) if (map.getLayer(`hawa-city-${c.key}`)) map.setLayoutProperty(`hawa-city-${c.key}`, 'visibility', 'none')
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
