"use client"

import { useEffect, useRef } from 'react'
import mapboxgl from 'mapbox-gl'
import 'mapbox-gl/dist/mapbox-gl.css'
import type { ForecastEntry, CurrentStation, CopilotAction } from './types'
import { BAND_COLORS, BAND_LABELS, formatPM25 } from './utils'

mapboxgl.accessToken = '***REMOVED***'

const API_BASE = 'https://hawanama-152782825429.asia-south1.run.app'
const MARKER_MIN_ZOOM = 4

// ── Pakistan boundary (point-in-polygon) ──

type Ring = [number, number][]
let pakMultiPoly: Ring[][][] | null = null

async function loadPakBoundary(): Promise<void> {
  if (pakMultiPoly) return
  try {
    const res = await fetch('/pakistan_country.geojson')
    const data = await res.json()
    const geom = data.features[0].geometry
    pakMultiPoly = geom.type === 'MultiPolygon'
      ? geom.coordinates
      : [geom.coordinates]
  } catch {
    pakMultiPoly = []
  }
}

function pointInRing(lng: number, lat: number, ring: Ring): boolean {
  let inside = false
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i]
    const [xj, yj] = ring[j]
    if ((yi > lat) !== (yj > lat) && lng < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) {
      inside = !inside
    }
  }
  return inside
}

function isInsidePakistan(lng: number, lat: number): boolean {
  if (!pakMultiPoly) return false
  for (const polygon of pakMultiPoly) {
    if (pointInRing(lng, lat, polygon[0])) {
      let inHole = false
      for (let h = 1; h < polygon.length; h++) {
        if (pointInRing(lng, lat, polygon[h])) { inHole = true; break }
      }
      if (!inHole) return true
    }
  }
  return false
}

// ── AQI color class (same as dashboard InteractivePakistanMap) ──

function getAQIColorClass(aqi: number | null | undefined): string {
  if (aqi == null || aqi <= 0) return 'bg-no-reading'
  if (aqi <= 50) return 'bg-good'
  if (aqi <= 100) return 'bg-moderate'
  if (aqi <= 150) return 'bg-unhealthy-sensitive'
  if (aqi <= 200) return 'bg-unhealthy'
  if (aqi <= 300) return 'bg-very-unhealthy'
  return 'bg-hazardous'
}

// Forecast risk_band → AQI marker class
function bandToMarkerClass(band: string): string {
  switch (band) {
    case 'good': return 'bg-good'
    case 'moderate': return 'bg-moderate'
    case 'unhealthy': return 'bg-unhealthy'
    case 'very_unhealthy': return 'bg-very-unhealthy'
    case 'severe': return 'bg-hazardous'
    default: return 'bg-moderate'
  }
}

// PM2.5 → band fallback
function pm25ToBand(pm25: number | null | undefined): string {
  if (pm25 == null) return 'moderate'
  if (pm25 <= 35) return 'good'
  if (pm25 <= 75) return 'moderate'
  if (pm25 <= 150) return 'unhealthy'
  if (pm25 <= 250) return 'very_unhealthy'
  return 'severe'
}

// AQI category → forecast band
const AQI_CATEGORY_MAP: Record<string, string> = {
  good: 'good',
  moderate: 'moderate',
  unhealthy_sensitive: 'unhealthy',
  unhealthy: 'unhealthy',
  very_unhealthy: 'very_unhealthy',
  hazardous: 'severe',
}

const AQI_CATEGORY_LABELS: Record<string, string> = {
  good: 'Good',
  moderate: 'Moderate',
  unhealthy_sensitive: 'Unhealthy (Sensitive)',
  unhealthy: 'Unhealthy',
  very_unhealthy: 'Very Unhealthy',
  hazardous: 'Hazardous',
}

// ── Marker element factory (CSS classes, no inline transforms) ──

function createMarkerEl(value: number | null | undefined, colorClass: string): HTMLDivElement {
  const container = document.createElement('div')
  container.className = 'aqi-marker-container point'
  container.style.width = '28px'
  container.style.height = '28px'

  const marker = document.createElement('div')
  marker.className = `aqi-marker ${colorClass}`
  marker.textContent = value != null ? `${Math.round(value)}` : '-'

  container.appendChild(marker)
  return container
}

// ── Component ──

interface ForecastMapProps {
  forecasts: ForecastEntry[]
  currentStations: CurrentStation[]
  selectedHorizon: number  // 0 = Now, 1/2/3 = D+1/D+2/D+3
  onHorizonChange: (h: number) => void
  onStationClick: (sensorId: number) => void
  pendingAction?: CopilotAction | null
  onActionProcessed?: () => void
}

export function ForecastMap({
  forecasts,
  currentStations,
  selectedHorizon,
  onHorizonChange,
  onStationClick,
  pendingAction,
  onActionProcessed,
}: ForecastMapProps) {
  const mapContainer = useRef<HTMLDivElement>(null)
  const map = useRef<mapboxgl.Map | null>(null)
  const markersRef = useRef<mapboxgl.Marker[]>([])
  const mapLoaded = useRef(false)

  // Keep refs to latest data to avoid stale closures in map callbacks
  const dataRef = useRef({ forecasts, currentStations, selectedHorizon, onStationClick })
  dataRef.current = { forecasts, currentStations, selectedHorizon, onStationClick }

  // Initialize map
  useEffect(() => {
    if (!mapContainer.current || map.current) return

    map.current = new mapboxgl.Map({
      container: mapContainer.current,
      style: 'mapbox://styles/rehan0900/cmmh9p69z009m01qu0nnn3iwu',
      center: [69.3459, 30.3],
      zoom: 4.2,
      projection: 'globe',
      maxZoom: 14,
      minZoom: 2,
    })

    map.current.addControl(new mapboxgl.NavigationControl({ showCompass: false }), 'top-right')

    map.current.on('load', async () => {
      if (!map.current) return
      await loadPakBoundary()

      // ── Satellite PM2.5 raster ──
      map.current.addSource('satpm25', {
        type: 'raster',
        tiles: [`${API_BASE}/api/v1/data-sources/satpm25/{z}/{x}/{y}.png`],
        tileSize: 256,
        minzoom: 3,
        maxzoom: 10,
        bounds: [60.5, 23.5, 77.5, 37.5],
        attribution: 'Typical PM2.5 (2022 satellite baseline)',
      })
      map.current.addLayer({
        id: 'satpm25-layer',
        type: 'raster',
        source: 'satpm25',
        paint: { 'raster-opacity': 0.75 },
        slot: 'middle',
      })

      // ── District boundaries (ADM2) — clickable ──
      map.current.addSource('pakistan-districts', {
        type: 'geojson',
        data: '/pakistan_districts.geojson',
        promoteId: 'shapeName',
      })

      map.current.addLayer({
        id: 'districts-fill',
        type: 'fill',
        source: 'pakistan-districts',
        paint: { 'fill-color': 'transparent', 'fill-opacity': 0 },
      })

      map.current.addLayer({
        id: 'districts-hover',
        type: 'fill',
        source: 'pakistan-districts',
        paint: {
          'fill-color': '#ffffff',
          'fill-opacity': [
            'case',
            ['boolean', ['feature-state', 'hover'], false],
            0.25,
            0,
          ],
        },
      })

      map.current.addLayer({
        id: 'districts-borders',
        type: 'line',
        source: 'pakistan-districts',
        paint: {
          'line-color': [
            'case',
            ['boolean', ['feature-state', 'hover'], false],
            '#64748b',
            '#94a3b8',
          ],
          'line-width': [
            'case',
            ['boolean', ['feature-state', 'hover'], false],
            1,
            0.3,
          ],
          'line-opacity': 0.5,
        },
      })

      // ── Province boundaries (ADM1) ──
      map.current.addSource('pakistan-provinces', {
        type: 'geojson',
        data: '/pakistan_adm1.geojson',
      })
      map.current.addLayer({
        id: 'provinces-line',
        type: 'line',
        source: 'pakistan-provinces',
        paint: { 'line-color': '#94a3b8', 'line-width': 1, 'line-opacity': 0.7 },
      })

      // ── Country outline ──
      map.current.addSource('pakistan-boundary', {
        type: 'geojson',
        data: '/pakistan_country.geojson',
      })
      map.current.addLayer({
        id: 'country-outline',
        type: 'line',
        source: 'pakistan-boundary',
        paint: { 'line-color': '#64748b', 'line-width': 1.5, 'line-opacity': 0.9 },
      })

      // ── District hover tracking ──
      let hoveredId: string | null = null

      map.current.on('mousemove', 'districts-fill', (e) => {
        if (!map.current || !e.features?.[0]) return
        map.current.getCanvas().style.cursor = 'pointer'
        const id = e.features[0].id as string
        if (hoveredId && hoveredId !== id) {
          map.current.setFeatureState({ source: 'pakistan-districts', id: hoveredId }, { hover: false })
        }
        hoveredId = id
        map.current.setFeatureState({ source: 'pakistan-districts', id }, { hover: true })
      })

      map.current.on('mouseleave', 'districts-fill', () => {
        if (!map.current) return
        map.current.getCanvas().style.cursor = ''
        if (hoveredId) {
          map.current.setFeatureState({ source: 'pakistan-districts', id: hoveredId }, { hover: false })
          hoveredId = null
        }
      })

      // ── District click → zoom to bounds ──
      map.current.on('click', 'districts-fill', (e) => {
        if (!map.current || !e.features?.[0]) return
        const geom = e.features[0].geometry as GeoJSON.Polygon | GeoJSON.MultiPolygon
        const coords: [number, number][] = []
        if (geom.type === 'Polygon') {
          geom.coordinates[0].forEach(c => coords.push(c as [number, number]))
        } else {
          geom.coordinates.forEach(poly => poly[0].forEach(c => coords.push(c as [number, number])))
        }
        const bounds = coords.reduce(
          (b, [lng, lat]) => [Math.min(b[0], lng), Math.min(b[1], lat), Math.max(b[2], lng), Math.max(b[3], lat)],
          [Infinity, Infinity, -Infinity, -Infinity]
        )
        map.current.fitBounds([[bounds[0], bounds[1]], [bounds[2], bounds[3]]], {
          padding: 100, maxZoom: 7.5, duration: 600,
        })
      })

      // ── Zoom-based marker visibility ──
      map.current.on('zoom', updateMarkerVisibility)

      mapLoaded.current = true
      renderMarkers()
    })

    return () => {
      mapLoaded.current = false
      markersRef.current.forEach(m => m.remove())
      markersRef.current = []
      map.current?.remove()
      map.current = null
    }
  }, [])

  const updateMarkerVisibility = () => {
    if (!map.current) return
    const zoom = map.current.getZoom()
    const visible = zoom >= MARKER_MIN_ZOOM
    for (const marker of markersRef.current) {
      if (visible) {
        marker.addTo(map.current!)
      } else {
        marker.remove()
      }
    }
  }

  // Render markers for current or forecast data (always reads from dataRef)
  const renderMarkers = () => {
    if (!map.current || !mapLoaded.current) return
    const { forecasts: fc, currentStations: cs, selectedHorizon: sh, onStationClick: osc } = dataRef.current

    markersRef.current.forEach(m => m.remove())
    markersRef.current = []

    if (sh === 0) {
      // Current/live station markers — Pakistan only
      cs.filter(s =>
        s.latitude != null && s.longitude != null &&
        isInsidePakistan(s.longitude, s.latitude)
      ).forEach((station) => {
        if (station.pm25 == null && station.aqi_raw == null) return

        const colorClass = getAQIColorClass(station.aqi_raw)
        const aqiCat = station.aqi_category || 'moderate'
        const band = AQI_CATEGORY_MAP[aqiCat] || 'moderate'
        const color = BAND_COLORS[band] || '#9ca3af'
        const textColor = band === 'moderate' ? '#333' : '#fff'

        const el = createMarkerEl(station.pm25, colorClass)

        const marker = new mapboxgl.Marker({ element: el, anchor: 'center' })
          .setLngLat([station.longitude, station.latitude])
          .setPopup(
            new mapboxgl.Popup({ offset: 16, closeButton: false, maxWidth: '240px' })
              .setHTML(`
                <div style="font-family:system-ui,-apple-system,sans-serif;font-size:13px;line-height:1.5">
                  <div style="font-weight:600;font-size:14px;margin-bottom:2px">${station.name || 'Station'}</div>
                  <div style="color:#64748b;font-size:12px;margin-bottom:8px">${station.city || ''}</div>
                  <div style="background:${color};color:${textColor};border-radius:8px;padding:8px 10px;margin-bottom:8px">
                    <div style="display:flex;justify-content:space-between;align-items:baseline">
                      <span style="font-size:22px;font-weight:700">${station.pm25 != null ? Math.round(station.pm25) : '—'}</span>
                      <span style="font-size:11px;opacity:0.85">µg/m³</span>
                    </div>
                    <div style="font-size:11px;opacity:0.9;margin-top:2px">${AQI_CATEGORY_LABELS[aqiCat] || aqiCat}</div>
                  </div>
                  ${station.aqi_raw != null ? `<div style="font-size:11px;color:#475569">AQI: <b>${Math.round(station.aqi_raw)}</b></div>` : ''}
                </div>
              `)
          )

        el.addEventListener('mouseenter', () => marker.togglePopup())
        el.addEventListener('mouseleave', () => marker.togglePopup())

        markersRef.current.push(marker)
      })
    } else {
      // Forecast markers (D+1/D+2/D+3)
      fc.filter(f => f.lead_days === sh).forEach((entry) => {
        if (entry.latitude == null || entry.longitude == null) return

        const rawBand = entry.risk_band
        const band = (rawBand && rawBand !== 'unknown') ? rawBand : pm25ToBand(entry.pm25_forecast)
        const colorClass = bandToMarkerClass(band)
        const color = BAND_COLORS[band] || '#9ca3af'
        const textColor = band === 'moderate' ? '#333' : '#fff'

        const el = createMarkerEl(entry.pm25_forecast, colorClass)

        if (entry.ramp_detected) {
          const inner = el.querySelector('.aqi-marker') as HTMLElement
          if (inner) {
            inner.style.boxShadow = `
              0 0 0 4px ${BAND_COLORS[band] || '#9ca3af'}60,
              0 0 16px ${BAND_COLORS[band] || '#9ca3af'}80,
              0 2px 4px rgba(0, 0, 0, 0.3)
            `
          }
        }

        if (entry.confidence === 'low') {
          const inner = el.querySelector('.aqi-marker') as HTMLElement
          if (inner) {
            inner.style.outline = '2px dashed rgba(0,0,0,0.3)'
            inner.style.outlineOffset = '3px'
          }
        }

        const marker = new mapboxgl.Marker({ element: el, anchor: 'center' })
          .setLngLat([entry.longitude, entry.latitude])
          .setPopup(
            new mapboxgl.Popup({ offset: 16, closeButton: false, maxWidth: '240px' })
              .setHTML(`
                <div style="font-family:system-ui,-apple-system,sans-serif;font-size:13px;line-height:1.5">
                  <div style="font-weight:600;font-size:14px;margin-bottom:2px">${entry.station_name || `Station ${entry.sensor_id}`}</div>
                  <div style="color:#64748b;font-size:12px;margin-bottom:8px">${entry.city_name || ''}</div>
                  <div style="background:${color};color:${textColor};border-radius:8px;padding:8px 10px;margin-bottom:8px">
                    <div style="display:flex;justify-content:space-between;align-items:baseline">
                      <span style="font-size:22px;font-weight:700">${formatPM25(entry.pm25_forecast)}</span>
                      <span style="font-size:11px;opacity:0.85">µg/m³</span>
                    </div>
                    <div style="font-size:11px;opacity:0.9;margin-top:2px">${BAND_LABELS[band] || band}</div>
                  </div>
                  <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;font-size:11px;color:#475569">
                    <div>Q75: <b>${formatPM25(entry.pm25_q75)}</b></div>
                    <div>Q90: <b>${formatPM25(entry.pm25_q90)}</b></div>
                    <div>Priority: <b style="text-transform:capitalize">${entry.priority || '—'}</b></div>
                    <div>Conf: <b style="text-transform:capitalize">${entry.confidence || '—'}</b></div>
                  </div>
                  ${entry.ramp_detected ? '<div style="color:#d97706;font-weight:600;margin-top:6px;font-size:12px">&#9889; Ramp Detected</div>' : ''}
                </div>
              `)
          )

        el.addEventListener('mouseenter', () => marker.togglePopup())
        el.addEventListener('mouseleave', () => marker.togglePopup())
        el.addEventListener('click', () => osc(entry.sensor_id))

        markersRef.current.push(marker)
      })
    }

    updateMarkerVisibility()
  }

  // Update markers when data changes
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    renderMarkers()
  }, [forecasts, currentStations, selectedHorizon, onStationClick])

  // Handle copilot map actions
  useEffect(() => {
    if (!pendingAction || !map.current || !mapLoaded.current) return

    if (pendingAction.type === 'zoom_to_city' && pendingAction.city) {
      // Find all stations in this city to compute bounds
      const cityLower = pendingAction.city.toLowerCase()
      const cityStations = forecasts.filter(
        f => (f.city_name || '').toLowerCase() === cityLower &&
          f.latitude != null && f.longitude != null
      )
      if (cityStations.length > 0) {
        const lngs = cityStations.map(s => s.longitude!)
        const lats = cityStations.map(s => s.latitude!)
        const bounds: [[number, number], [number, number]] = [
          [Math.min(...lngs) - 0.05, Math.min(...lats) - 0.05],
          [Math.max(...lngs) + 0.05, Math.max(...lats) + 0.05],
        ]
        map.current.fitBounds(bounds, { padding: 80, maxZoom: 10, duration: 800 })
      }
    } else if (pendingAction.type === 'zoom_to_station' && pendingAction.lat && pendingAction.lng) {
      map.current.flyTo({
        center: [pendingAction.lng, pendingAction.lat],
        zoom: 11,
        duration: 800,
      })
    }

    onActionProcessed?.()
  }, [pendingAction, forecasts, onActionProcessed])

  // Timeline steps
  const steps = [
    { value: 0, label: 'Now', sub: 'Live' },
    { value: 1, label: 'Tomorrow', sub: 'D+1' },
    { value: 2, label: 'Day After', sub: 'D+2' },
    { value: 3, label: '3-Day Outlook', sub: 'D+3' },
  ]

  return (
    <div className="relative w-full h-full">
      {/* ── Timeline toggle — top center ── */}
      <div className="absolute top-4 left-1/2 -translate-x-1/2 z-10">
        <div className="flex items-center bg-white/95 backdrop-blur-sm rounded-full shadow-lg border border-slate-200/60 p-1">
          {steps.map((step) => {
            const isActive = selectedHorizon === step.value
            return (
              <button
                key={step.value}
                onClick={() => onHorizonChange(step.value)}
                className={`relative flex flex-col items-center px-5 py-1.5 rounded-full transition-all duration-200 ${
                  isActive
                    ? 'bg-slate-800 text-white shadow-md'
                    : 'text-slate-500 hover:text-slate-800 hover:bg-slate-100'
                }`}
              >
                <span className={`text-xs font-semibold leading-tight ${isActive ? 'text-white' : ''}`}>
                  {step.label}
                </span>
                <span className={`text-[9px] leading-tight ${isActive ? 'text-slate-300' : 'text-slate-400'}`}>
                  {step.sub}
                </span>
              </button>
            )
          })}
        </div>
      </div>

      {/* Map container */}
      <div ref={mapContainer} className="w-full h-full" />

      {/* Popup styling */}
      <style jsx global>{`
        .mapboxgl-popup-content {
          border-radius: 12px !important;
          padding: 12px 14px !important;
          box-shadow: 0 10px 25px rgba(0,0,0,0.15), 0 4px 10px rgba(0,0,0,0.08) !important;
          border: 1px solid rgba(0,0,0,0.06) !important;
        }
        .mapboxgl-popup-tip {
          border-top-color: white !important;
        }
        .mapboxgl-ctrl-attrib {
          display: none !important;
        }
      `}</style>
    </div>
  )
}
