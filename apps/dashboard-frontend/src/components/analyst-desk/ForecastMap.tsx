"use client"

import { useEffect, useRef, useState, useCallback } from 'react'
import mapboxgl from 'mapbox-gl'
import 'mapbox-gl/dist/mapbox-gl.css'
import type { ForecastEntry, CurrentStation, CopilotAction, StationMention } from './types'
import { WindParticleRenderer, type WindMetadata } from './WindParticleLayer'
import type { FiresGeoJSON } from './api'
import { BAND_COLORS, BAND_LABELS, formatPM25 } from './utils'

mapboxgl.accessToken = process.env.NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN || ''

const API_BASE = 'https://hawanama-152782825429.asia-south1.run.app'
const MARKER_MIN_ZOOM = 4

import { loadPakBoundary, isInsidePakistan } from './pakistan'

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
  container.style.cssText = 'width:28px;display:flex;flex-direction:column;align-items:center;'

  const marker = document.createElement('div')
  marker.className = `aqi-marker ${colorClass}`
  marker.textContent = value != null ? `${Math.round(value)}` : '-'

  // Vertical stem (visible at closer zoom via CSS)
  const stem = document.createElement('div')
  stem.className = 'aqi-stem'
  stem.style.cssText = 'width:1.5px;height:0px;background:rgba(0,0,0,0.25);transition:height 0.3s;'

  // Ground dot
  const dot = document.createElement('div')
  dot.className = 'aqi-ground-dot'
  dot.style.cssText = 'width:4px;height:2px;border-radius:50%;background:rgba(0,0,0,0.15);transition:opacity 0.3s;opacity:0;'

  container.appendChild(marker)
  container.appendChild(stem)
  container.appendChild(dot)
  return container
}

// ── Component ──

interface ProviderMap {
  by_sensor_id: Record<string, string>
  by_station_id: Record<string, string>
  by_name: Record<string, string>
}

interface ForecastMapProps {
  forecasts: ForecastEntry[]
  currentStations: CurrentStation[]
  selectedHorizon: number  // 0 = Now, 1/2/3 = D+1/D+2/D+3
  onHorizonChange: (h: number) => void
  onStationClick: (mention: StationMention) => void
  onDistrictClick?: (cityName: string) => void
  pendingAction?: CopilotAction | null
  onActionProcessed?: () => void
  networkFilter?: string | null
  onClearNetworkFilter?: () => void
  firesGeoJSON?: FiresGeoJSON | null
  // Layer toggles (lifted to parent for icon rail control)
  showStations?: boolean
  showSatellite?: boolean
  showFires?: boolean
  showWind?: boolean
  showPopulation?: boolean
  onToggleStations?: () => void
  onToggleSatellite?: () => void
  onToggleFires?: () => void
  onToggleWind?: () => void
  showPopulation?: boolean
  onTogglePopulation?: () => void
  mapRef?: React.MutableRefObject<{ resize: () => void } | null>
}

export function ForecastMap({
  forecasts,
  currentStations,
  selectedHorizon,
  onHorizonChange,
  onStationClick,
  onDistrictClick,
  pendingAction,
  onActionProcessed,
  networkFilter,
  onClearNetworkFilter,
  firesGeoJSON,
  showStations: showStationsProp,
  showSatellite: showSatelliteProp,
  showFires: showFiresProp,
  showWind: showWindProp,
  onToggleStations,
  onToggleSatellite,
  onToggleFires,
  onToggleWind,
  showPopulation: showPopulationProp,
  onTogglePopulation,
  mapRef: externalMapRef,
}: ForecastMapProps) {
  const mapContainer = useRef<HTMLDivElement>(null)
  const map = useRef<mapboxgl.Map | null>(null)
  const markersRef = useRef<mapboxgl.Marker[]>([])
  const mapLoaded = useRef(false)
  const [zoomLevel, setZoomLevel] = useState(4.2)
  const providerMapRef = useRef<ProviderMap | null>(null)
  const fireSourceAdded = useRef(false)

  const [showFiresLocal, setShowFiresLocal] = useState(true)
  const [showStationsLocal, setShowStationsLocal] = useState(true)
  const [showSatelliteLocal, setShowSatelliteLocal] = useState(true)
  const [showWindLocal, setShowWindLocal] = useState(true)

  // Use prop if provided, else fall back to local state
  const showFires = showFiresProp ?? showFiresLocal
  const showStations = showStationsProp ?? showStationsLocal
  const showSatellite = showSatelliteProp ?? showSatelliteLocal
  const showWind = showWindProp ?? showWindLocal
  const [showPopulationLocal, setShowPopulationLocal] = useState(false)
  const showPopulation = showPopulationProp ?? showPopulationLocal
  const [windImage, setWindImage] = useState<HTMLImageElement | null>(null)
  const [windMetadata, setWindMetadata] = useState<WindMetadata | null>(null)
  const windRendererRef = useRef<WindParticleRenderer | null>(null)

  // Hover readout — local grid lookup (no network on mousemove)
  const [hoverPM25, setHoverPM25] = useState<{
    pm25: number; lat: number; lon: number; label: string;
    population?: number; popWeightedPM25?: number
  } | null>(null)
  const predDateRef = useRef<string>('')

  // Urban grid cache: city_key → { grid, lookup function }
  type UrbanGrid = {
    resolution: number
    bounds: { west: number; east: number; south: number; north: number }
    shape: [number, number]  // [rows, cols]
    pm25: (number | null)[]
    population: number[]
    stats: { pop_weighted_pm25?: number; population_total?: number }
  }
  const urbanGridsRef = useRef<Map<string, UrbanGrid>>(new Map())
  const urbanGridLoadingRef = useRef<Set<string>>(new Set())

  // Ref to latest fire data for use in map load callback
  const firesRef = useRef(firesGeoJSON)
  firesRef.current = firesGeoJSON

  // Keep refs to latest data to avoid stale closures in map callbacks
  const dataRef = useRef({ forecasts, currentStations, selectedHorizon, onStationClick, onDistrictClick })
  dataRef.current = { forecasts, currentStations, selectedHorizon, onStationClick, onDistrictClick }

  // Load provider map for network filtering
  useEffect(() => {
    fetch('/station-providers.json')
      .then(r => r.json())
      .then((d: ProviderMap) => { providerMapRef.current = d })
      .catch(() => {})
  }, [])

  // Initialize map
  useEffect(() => {
    if (!mapContainer.current || map.current) return

    map.current = new mapboxgl.Map({
      container: mapContainer.current,
      style: 'mapbox://styles/rehan0900/cmmh9p69z009m01qu0nnn3iwu',
      center: [69.3459, 30.3],
      zoom: 4.2,
      projection: 'globe',
      maxZoom: 18,
      minZoom: 2,
      pitch: 30,
      bearing: -10,
      maxPitch: 85,
      antialias: true,
    })

    map.current.on('load', async () => {
      if (!map.current) return
      await loadPakBoundary()

      // ── 3D Terrain ──
      map.current.addSource('mapbox-dem', {
        type: 'raster-dem',
        url: 'mapbox://mapbox.mapbox-terrain-dem-v1',
        tileSize: 512,
        maxzoom: 14,
      })
      map.current.setTerrain({
        source: 'mapbox-dem',
        exaggeration: ['interpolate', ['linear'], ['zoom'], 0, 1.5, 15, 1.0],
      })

      // ── Atmosphere ──
      map.current.setFog({
        range: [0.5, 10],
        color: '#ffffff',
        'high-color': '#b8d4e8',
        'space-color': '#d8f2ff',
        'horizon-blend': 0.08,
        'star-intensity': 0.0,
      })

      // ── 3D Buildings (city-level detail) ──
      const layers = map.current.getStyle().layers || []
      const labelLayerId = layers.find(
        (layer: any) => layer.type === 'symbol' && layer.layout?.['text-field']
      )?.id

      map.current.addLayer({
        id: '3d-buildings',
        source: 'composite',
        'source-layer': 'building',
        filter: ['==', 'extrude', 'true'],
        type: 'fill-extrusion',
        minzoom: 14,
        paint: {
          'fill-extrusion-color': [
            'interpolate', ['linear'], ['get', 'height'],
            0, '#cbd5e1',
            30, '#94a3b8',
            80, '#64748b',
          ],
          'fill-extrusion-height': [
            'interpolate', ['linear'], ['zoom'],
            14, 0,
            14.5, ['get', 'height'],
          ],
          'fill-extrusion-base': [
            'interpolate', ['linear'], ['zoom'],
            14, 0,
            14.5, ['get', 'min_height'],
          ],
          'fill-extrusion-opacity': 0.7,
        },
      }, labelLayerId)

      // Camera starts at 30° pitch. User controls pitch freely via
      // right-click drag or two-finger tilt. No auto-pitch on zoom —
      // it fights the user's scroll gesture and feels janky.

      // ── PM2.5 estimation raster (daily NRT/Final predictions) ──
      // Fetch the latest available prediction date from the pipeline
      let predDate: string
      try {
        const datesRes = await fetch(`${API_BASE}/api/v1/ops/pipeline/tiles/dates`)
        const datesData = await datesRes.json()
        const d = datesData.dates ?? []
        predDate = d[d.length - 1] || new Date().toISOString().slice(0, 10)
      } catch {
        predDate = new Date().toISOString().slice(0, 10)
      }
      predDateRef.current = predDate

      map.current.addSource('satpm25', {
        type: 'raster',
        tiles: [`${API_BASE}/api/v1/ops/pipeline/tiles/${predDate}/{z}/{x}/{y}.png?smoothed=true`],
        tileSize: 256,
        minzoom: 3,
        maxzoom: 10,
        bounds: [60.5, 23.3, 77.9, 37.3],
        attribution: `PAQi PM2.5 Estimation (${predDate})`,
      })
      map.current.addLayer({
        id: 'satpm25-layer',
        type: 'raster',
        source: 'satpm25',
        paint: {
          'raster-opacity': [
            'interpolate', ['linear'], ['zoom'],
            3, 0.8,
            7, 0.65,
            9, 0.3,
            12, 0.15,
          ],
        },
        slot: 'middle',
      })

      // ── Urban 1 km city layers (overlay at higher zoom) ──
      const cities = [
        { key: 'lahore', bounds: [74.0, 31.2, 74.6, 31.8] as [number, number, number, number] },
        { key: 'isb_rwp', bounds: [72.6, 33.3, 73.3, 33.9] as [number, number, number, number] },
        { key: 'peshawar', bounds: [71.3, 33.8, 71.9, 34.3] as [number, number, number, number] },
        { key: 'karachi', bounds: [66.7, 24.7, 67.3, 25.3] as [number, number, number, number] },
      ]

      for (const city of cities) {
        const srcId = `urban-${city.key}`
        const layerId = `urban-${city.key}-layer`
        try {
          map.current!.addSource(srcId, {
            type: 'raster',
            tiles: [
              `${API_BASE}/api/v1/ops/pipeline/tiles/${predDate}/{z}/{x}/{y}.png?smoothed=true&model=urban/${city.key}`,
            ],
            tileSize: 256,
            minzoom: 9,
            maxzoom: 15,
            bounds: city.bounds,
          })
          map.current!.addLayer({
            id: layerId,
            type: 'raster',
            source: srcId,
            minzoom: 9,
            paint: {
              'raster-opacity': [
                'interpolate', ['linear'], ['zoom'],
                9, 0,
                10, 0.45,
                12, 0.5,
                15, 0.4,
              ],
            },
          })
          console.log(`[Urban] Added ${layerId} for date=${predDate}`)
        } catch (e) {
          console.warn(`[Urban] Failed to add ${layerId}:`, e)
        }
      }

      // ── Population density layer ──
      map.current.addSource('population', {
        type: 'raster',
        tiles: [
          `${API_BASE}/api/v1/ops/pipeline/tiles/${predDate}/{z}/{x}/{y}.png?model=population`,
        ],
        tileSize: 256,
        minzoom: 4,
        maxzoom: 14,
        bounds: [60.8, 23.6, 77.9, 37.1],
      })
      map.current.addLayer({
        id: 'population-layer',
        type: 'raster',
        source: 'population',
        layout: { visibility: 'none' },
        paint: {
          'raster-opacity': [
            'interpolate', ['linear'], ['zoom'],
            4, 0.5,
            10, 0.6,
            14, 0.5,
          ],
        },
      })

      // ── PM2.5 click-to-query (interactive raster) ──
      const pm25Popup = new mapboxgl.Popup({ closeButton: true, closeOnClick: true, maxWidth: '200px' })
      map.current.on('click', async (e) => {
        if (!map.current) return
        const z = map.current.getZoom()
        if (z < 5) return  // too zoomed out
        // Skip if clicked on a station marker or district
        const features = map.current.queryRenderedFeatures(e.point, { layers: ['districts-fill'] })
        if (features.length > 0) return

        const { lng, lat } = e.lngLat
        if (!isInsidePakistan(lng, lat)) return

        try {
          const res = await fetch(
            `${API_BASE}/api/v1/ops/pipeline/tiles/${predDate}/point?lat=${lat.toFixed(4)}&lon=${lng.toFixed(4)}&smoothed=true`,
            { headers: { Authorization: `Bearer ${process.env.NEXT_PUBLIC_TASKS_API_SECRET || ''}` } }
          )
          if (!res.ok) return
          const data = await res.json()
          const pm25 = data.pm25
          if (pm25 == null) return

          const band = pm25 <= 35 ? 'Good' : pm25 <= 75 ? 'Moderate' : pm25 <= 150 ? 'Unhealthy' : pm25 <= 250 ? 'Very Unhealthy' : 'Severe'
          const color = pm25 <= 35 ? '#6ecc39' : pm25 <= 75 ? '#f0c20c' : pm25 <= 150 ? '#f18017' : pm25 <= 250 ? '#a070b5' : '#991b1b'
          const textColor = pm25 <= 75 ? '#333' : '#fff'

          pm25Popup.setLngLat(e.lngLat).setHTML(`
            <div style="font-family:system-ui,-apple-system,sans-serif;font-size:12px;line-height:1.5;text-align:center">
              <div style="font-size:10px;color:#94a3b8;margin-bottom:4px">${lat.toFixed(3)}°N, ${lng.toFixed(3)}°E</div>
              <div style="background:${color};color:${textColor};border-radius:8px;padding:8px 14px">
                <div style="font-size:20px;font-weight:700">${Math.round(pm25)}</div>
                <div style="font-size:10px;opacity:0.85">µg/m³ PM2.5</div>
              </div>
              <div style="font-size:10px;color:#64748b;margin-top:4px">${band}</div>
            </div>
          `).addTo(map.current)
        } catch { /* ignore query errors */ }
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

      // ── Active fires (FIRMS VIIRS) ──
      map.current.addSource('fires', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      })

      map.current.addLayer({
        id: 'fires-glow',
        type: 'circle',
        source: 'fires',
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['get', 'frp'], 0, 12, 50, 24, 200, 40],
          'circle-color': '#ff8c00',
          'circle-opacity': 0.15,
          'circle-blur': 1,
        },
      })

      map.current.addLayer({
        id: 'fires-layer',
        type: 'circle',
        source: 'fires',
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['get', 'frp'], 0, 3, 50, 6, 200, 10],
          'circle-color': [
            'match', ['get', 'confidence'],
            'h', '#ff2200',
            'high', '#ff2200',
            '#ff8c00',
          ],
          'circle-opacity': 0.85,
          'circle-stroke-width': 1,
          'circle-stroke-color': 'rgba(0,0,0,0.3)',
        },
      })

      // Fire hover popup
      const firePopup = new mapboxgl.Popup({ closeButton: false, closeOnClick: false, maxWidth: '200px' })

      map.current.on('mouseenter', 'fires-layer', (e) => {
        if (!map.current || !e.features?.[0]) return
        map.current.getCanvas().style.cursor = 'pointer'
        const props = e.features[0].properties!
        const coords = (e.features[0].geometry as GeoJSON.Point).coordinates.slice() as [number, number]
        firePopup.setLngLat(coords).setHTML(`
          <div style="font-family:system-ui,-apple-system,sans-serif;font-size:12px;line-height:1.5">
            <div style="font-weight:600;color:#ea580c;margin-bottom:4px">Fire Detection</div>
            <div>FRP: <b>${props.frp} MW</b></div>
            <div>Confidence: <b style="text-transform:capitalize">${props.confidence}</b></div>
            <div>Satellite: <b>${props.satellite}</b></div>
            <div style="color:#64748b;font-size:11px;margin-top:2px">${props.acq_date}</div>
          </div>
        `).addTo(map.current)
      })

      map.current.on('mouseleave', 'fires-layer', () => {
        if (!map.current) return
        map.current.getCanvas().style.cursor = ''
        firePopup.remove()
      })

      fireSourceAdded.current = true

      // Sync fire data if it arrived before map loaded (Pakistan only)
      if (firesRef.current) {
        const src = map.current.getSource('fires') as mapboxgl.GeoJSONSource | undefined
        if (src) {
          const filtered = {
            ...firesRef.current,
            features: firesRef.current.features.filter((f: any) => {
              const [lng, lat] = (f.geometry as GeoJSON.Point).coordinates
              return isInsidePakistan(lng, lat)
            }),
          }
          src.setData(filtered as GeoJSON.FeatureCollection)
        }
      }

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

      // ── District click → zoom to bounds + mention in chat ──
      map.current.on('click', 'districts-fill', (e) => {
        if (!map.current || !e.features?.[0]) return
        // Don't zoom out when already zoomed into a city
        if (map.current.getZoom() >= 9) return
        const districtName = (e.features[0].properties?.shapeName || e.features[0].id || '') as string
        if (districtName) {
          dataRef.current.onDistrictClick?.(districtName)
        }
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
      map.current.on('zoom', () => {
        updateMarkerVisibility()
        if (map.current) setZoomLevel(map.current.getZoom())
      })

      mapLoaded.current = true
      renderMarkers()

      // ── Hover readout: local grid lookup (zero network latency) ──
      const urbanCities = [
        { key: 'lahore', w: 74.0, s: 31.2, e: 74.6, n: 31.8 },
        { key: 'isb_rwp', w: 72.6, s: 33.3, e: 73.3, n: 33.9 },
        { key: 'peshawar', w: 71.3, s: 33.8, e: 71.9, n: 34.3 },
        { key: 'karachi', w: 66.7, s: 24.7, e: 67.3, n: 25.3 },
      ]

      // Fetch urban grid data for a city (once, then cached in ref)
      const ensureUrbanGrid = (cityKey: string) => {
        if (urbanGridsRef.current.has(cityKey) || urbanGridLoadingRef.current.has(cityKey)) return
        urbanGridLoadingRef.current.add(cityKey)
        fetch(`${API_BASE}/api/v1/ops/pipeline/tiles/${predDateRef.current}/urban/${cityKey}.json`)
          .then(r => r.ok ? r.json() : null)
          .then(data => {
            if (!data) return
            urbanGridsRef.current.set(cityKey, {
              resolution: data.grid?.resolution || 0.01,
              bounds: data.grid?.bounds || {},
              shape: data.grid?.shape || [0, 0],
              pm25: data.pm25 || [],
              population: data.population || [],
              stats: data.stats || {},
            })
          })
          .catch(() => {})
          .finally(() => urbanGridLoadingRef.current.delete(cityKey))
      }

      // Local grid lookup: O(1) from preloaded data
      const lookupUrbanCell = (cityKey: string, lat: number, lng: number): {
        pm25: number | null; population: number; popWeightedPM25: number
      } | null => {
        const grid = urbanGridsRef.current.get(cityKey)
        if (!grid || !grid.pm25.length) return null
        const { bounds, shape, resolution } = grid
        const row = Math.floor((lat - bounds.south) / resolution)
        const col = Math.floor((lng - bounds.west) / resolution)
        if (row < 0 || row >= shape[0] || col < 0 || col >= shape[1]) return null
        const idx = row * shape[1] + col
        return {
          pm25: grid.pm25[idx],
          population: grid.population[idx] || 0,
          popWeightedPM25: grid.stats?.pop_weighted_pm25 || 0,
        }
      }

      map.current.on('mousemove', (e) => {
        if (!map.current || map.current.getZoom() < 8) {
          setHoverPM25(null)
          return
        }
        const { lng, lat } = e.lngLat
        if (!isInsidePakistan(lng, lat)) { setHoverPM25(null); return }

        // Check if cursor is inside a city with urban coverage
        const city = urbanCities.find(c => lng >= c.w && lng <= c.e && lat >= c.s && lat <= c.n)

        if (city) {
          // Ensure grid is loaded (fires once per city)
          ensureUrbanGrid(city.key)

          // Instant local lookup
          const cell = lookupUrbanCell(city.key, lat, lng)
          if (cell?.pm25 != null) {
            setHoverPM25({
              pm25: cell.pm25, lat, lon: lng, label: '1km Downscaler',
              population: cell.population, popWeightedPM25: cell.popWeightedPM25,
            })
          } else {
            setHoverPM25(null)
          }
        } else {
          // Outside urban coverage — clear (national layer visible anyway)
          setHoverPM25(null)
        }
      })

      map.current.on('mouseout', () => setHoverPM25(null))

      // Expose resize to parent for panel animation
      if (externalMapRef) {
        externalMapRef.current = { resize: () => map.current?.resize() }
      }
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
    const close = zoom >= 10  // stems appear at city zoom
    for (const marker of markersRef.current) {
      if (visible) {
        marker.addTo(map.current!)
        // Animate stems at close zoom
        const el = marker.getElement()
        const stem = el.querySelector('.aqi-stem') as HTMLElement
        const dot = el.querySelector('.aqi-ground-dot') as HTMLElement
        if (stem) stem.style.height = close ? '18px' : '0px'
        if (dot) dot.style.opacity = close ? '1' : '0'
      } else {
        marker.remove()
      }
    }
  }

  // Render markers for current or forecast data (always reads from dataRef)
  const renderMarkers = () => {
    if (!map.current || !mapLoaded.current) return

    markersRef.current.forEach(m => m.remove())
    markersRef.current = []

    if (!showStations) return

    const { forecasts: fc, currentStations: cs, selectedHorizon: sh, onStationClick: osc } = dataRef.current

    const nf = networkFilter ?? null
    const pm = providerMapRef.current

    if (sh === 0) {
      // Current/live station markers — Pakistan only
      cs.filter(s =>
        s.latitude != null && s.longitude != null &&
        isInsidePakistan(s.longitude, s.latitude) &&
        (!nf || !pm || (pm.by_station_id[s.id] || pm.by_name[s.name] || '').toLowerCase().includes(nf.toLowerCase()))
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
        el.addEventListener('click', () => osc({
          sensorId: 0,
          stationName: station.name || 'Station',
          cityName: station.city || '',
        }))

        markersRef.current.push(marker)
      })
    } else {
      // Forecast markers (D+1/D+2/D+3)
      fc.filter(f =>
        f.lead_days === sh &&
        (!nf || !pm || (pm.by_sensor_id[String(f.sensor_id)] || pm.by_name[f.station_name] || '').toLowerCase().includes(nf.toLowerCase()))
      ).forEach((entry) => {
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
        el.addEventListener('click', () => osc({
          sensorId: entry.sensor_id,
          stationName: entry.station_name || `Station ${entry.sensor_id}`,
          cityName: entry.city_name || '',
        }))

        markersRef.current.push(marker)
      })
    }

    updateMarkerVisibility()
  }

  // Update markers when data changes
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    renderMarkers()
  }, [forecasts, currentStations, selectedHorizon, onStationClick, networkFilter, showStations])

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

  // Sync fire data to map source
  useEffect(() => {
    if (!map.current || !fireSourceAdded.current) return
    const src = map.current.getSource('fires') as mapboxgl.GeoJSONSource | undefined
    if (!src) return
    if (firesGeoJSON) {
      // Filter to Pakistan only
      const filtered = {
        ...firesGeoJSON,
        features: firesGeoJSON.features.filter((f: any) => {
          const [lng, lat] = (f.geometry as GeoJSON.Point).coordinates
          return isInsidePakistan(lng, lat)
        }),
      }
      src.setData(filtered as GeoJSON.FeatureCollection)
    } else {
      src.setData({ type: 'FeatureCollection', features: [] })
    }
  }, [firesGeoJSON])

  // Toggle fire layer visibility
  useEffect(() => {
    if (!map.current || !fireSourceAdded.current) return
    const vis = showFires ? 'visible' : 'none'
    for (const id of ['fires-glow', 'fires-layer']) {
      if (map.current.getLayer(id)) {
        map.current.setLayoutProperty(id, 'visibility', vis)
      }
    }
  }, [showFires])

  // Toggle satellite layer visibility
  useEffect(() => {
    if (!map.current) return
    const vis = showSatellite ? 'visible' : 'none'
    if (map.current.getLayer('satpm25-layer')) {
      map.current.setLayoutProperty('satpm25-layer', 'visibility', vis)
    }
    for (const c of ['lahore', 'isb_rwp', 'peshawar', 'karachi']) {
      const id = `urban-${c}-layer`
      if (map.current.getLayer(id)) {
        map.current.setLayoutProperty(id, 'visibility', vis)
      }
    }
  }, [showSatellite])

  // Toggle population layer visibility
  useEffect(() => {
    if (!map.current) return
    if (map.current.getLayer('population-layer')) {
      map.current.setLayoutProperty('population-layer', 'visibility', showPopulation ? 'visible' : 'none')
    }
  }, [showPopulation])

  // Fetch wind texture + metadata when wind is enabled (lazy)
  useEffect(() => {
    if (!showWind) return
    if (windImage && windMetadata) return // already cached

    let mounted = true
    const fetchWind = async () => {
      try {
        const [texResp, metaResp] = await Promise.all([
          fetch(`${API_BASE}/api/v1/data-sources/wind/texture`),
          fetch(`${API_BASE}/api/v1/data-sources/wind/metadata`),
        ])
        if (!texResp.ok || !metaResp.ok) return

        const [blob, meta] = await Promise.all([texResp.blob(), metaResp.json()])

        const img = new Image()
        img.crossOrigin = 'anonymous'
        await new Promise<void>((resolve, reject) => {
          img.onload = () => resolve()
          img.onerror = () => reject(new Error('Failed to decode wind texture'))
          img.src = URL.createObjectURL(blob)
        })

        if (mounted) {
          setWindImage(img)
          setWindMetadata(meta)
        }
      } catch (err) {
        console.warn('Wind data fetch failed:', err)
      }
    }

    fetchWind()
    return () => { mounted = false }
  }, [showWind, windImage, windMetadata])

  // Create/destroy wind particle renderer
  useEffect(() => {
    if (windRendererRef.current) {
      windRendererRef.current.destroy()
      windRendererRef.current = null
    }

    if (!map.current || !mapLoaded.current || !windImage || !windMetadata || !showWind) return

    try {
      const renderer = new WindParticleRenderer(map.current, windImage, windMetadata)
      renderer.start()
      windRendererRef.current = renderer
    } catch (err) {
      console.warn('Wind renderer failed:', err)
    }

    return () => {
      if (windRendererRef.current) {
        windRendererRef.current.destroy()
        windRendererRef.current = null
      }
    }
  }, [windImage, windMetadata, showWind])

  // Timeline steps — date-formatted labels
  const formatHorizonDate = (daysAhead: number) => {
    const d = new Date()
    d.setDate(d.getDate() + daysAhead)
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  }
  const steps = [
    { value: 0, label: `Today \u2014 ${formatHorizonDate(0)}` },
    { value: 1, label: formatHorizonDate(1) },
    { value: 2, label: formatHorizonDate(2) },
    { value: 3, label: formatHorizonDate(3) },
  ]

  return (
    <div className="relative w-full h-full">
      {/* ── Unified top bar: network filter + timeline + analytics toggle ── */}
      <div className="absolute top-3 right-3 z-10 flex items-center gap-2">
        {/* Network filter badge (conditional) */}
        {networkFilter && (
          <div className="flex items-center gap-1.5 bg-slate-800/85 backdrop-blur-sm rounded-lg px-3 py-1.5 shadow-lg ring-1 ring-white/10 text-[11px] font-medium text-slate-200">
            <span>{networkFilter}</span>
            <button
              onClick={onClearNetworkFilter}
              className="ml-1 w-4 h-4 flex items-center justify-center rounded-full bg-white/15 hover:bg-white/25 text-white/70 text-xs leading-none"
            >
              &times;
            </button>
          </div>
        )}

        {/* Timeline pill */}
        <div className="flex items-center gap-1.5 bg-slate-800/85 backdrop-blur-sm rounded-lg px-2 py-1.5 shadow-lg ring-1 ring-white/10">
          <button
            onClick={() => { if (selectedHorizon > 0) onHorizonChange(selectedHorizon - 1) }}
            disabled={selectedHorizon <= 0}
            className="p-1 rounded-md hover:bg-white/10 disabled:opacity-30 transition-colors shrink-0"
          >
            <svg className="w-3.5 h-3.5 text-white/70" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" /></svg>
          </button>

          <div className="text-center min-w-[110px] text-[12px] font-semibold text-white shrink-0">
            {steps[selectedHorizon].label}
          </div>

          <button
            onClick={() => { if (selectedHorizon < 3) onHorizonChange(selectedHorizon + 1) }}
            disabled={selectedHorizon >= 3}
            className="p-1 rounded-md hover:bg-white/10 disabled:opacity-30 transition-colors shrink-0"
          >
            <svg className="w-3.5 h-3.5 text-white/70" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" /></svg>
          </button>

          {/* Dot indicators instead of slider */}
          <div className="flex items-center gap-1 ml-1">
            {steps.map((s, i) => (
              <button
                key={i}
                onClick={() => onHorizonChange(i)}
                className={`w-1.5 h-1.5 rounded-full transition-colors ${
                  i === selectedHorizon ? 'bg-amber-400' : 'bg-white/25 hover:bg-white/40'
                }`}
              />
            ))}
          </div>
        </div>

        {/* Zoom level indicator */}
        <div className="px-2 py-1.5 rounded-lg bg-slate-800/85 backdrop-blur-sm shadow-lg ring-1 ring-white/10 text-[11px] font-mono text-white/70 tabular-nums">
          z{zoomLevel.toFixed(1)}
        </div>

      </div>

      {/* Map container */}
      <div ref={mapContainer} className="w-full h-full" />

      {/* PM2.5 hover readout — upper left, always visible at city zoom */}
      {zoomLevel >= 8 && (
        <div className="absolute top-3 left-3 z-10 pointer-events-none">
          <div className="flex items-center gap-3 px-3.5 py-2.5 rounded-xl bg-slate-800/90 backdrop-blur-sm shadow-lg ring-1 ring-white/10 min-w-[180px]">
            {hoverPM25 ? (
              <>
                <div className="text-center min-w-[44px]">
                  <div className={`text-2xl font-bold tabular-nums leading-none ${
                    hoverPM25.pm25 <= 15 ? 'text-emerald-300' :
                    hoverPM25.pm25 <= 35 ? 'text-emerald-400' :
                    hoverPM25.pm25 <= 55 ? 'text-amber-400' :
                    hoverPM25.pm25 <= 75 ? 'text-orange-400' :
                    hoverPM25.pm25 <= 150 ? 'text-orange-500' :
                    'text-red-400'
                  }`}>
                    {Math.round(hoverPM25.pm25)}
                  </div>
                  <div className="text-[9px] text-slate-400 font-medium mt-0.5">µg/m³</div>
                </div>
                <div className="text-[10px] leading-tight border-l border-white/10 pl-3">
                  <div className="font-semibold text-white">{hoverPM25.label || 'PM2.5'}</div>
                  <div className="text-slate-500">{
                    hoverPM25.pm25 <= 35 ? 'Good' :
                    hoverPM25.pm25 <= 75 ? 'Moderate' :
                    hoverPM25.pm25 <= 150 ? 'Unhealthy' :
                    hoverPM25.pm25 <= 250 ? 'Very Unhealthy' : 'Severe'
                  }</div>
                </div>
                {hoverPM25.population != null && hoverPM25.population > 0 && (
                  <div className="text-center border-l border-white/10 pl-3 min-w-[40px]">
                    <div className="text-lg font-bold tabular-nums leading-none text-purple-300">
                      {hoverPM25.population >= 1000 ? `${(hoverPM25.population / 1000).toFixed(1)}k` : Math.round(hoverPM25.population)}
                    </div>
                    <div className="text-[8px] text-slate-500 font-medium mt-0.5">pop/km²</div>
                  </div>
                )}
                {hoverPM25.popWeightedPM25 != null && hoverPM25.popWeightedPM25 > 0 && (
                  <div className="text-center border-l border-white/10 pl-3 min-w-[36px]">
                    <div className="text-sm font-bold tabular-nums leading-none text-purple-400/70">
                      {Math.round(hoverPM25.popWeightedPM25)}
                    </div>
                    <div className="text-[7px] text-slate-500 font-medium mt-0.5">city avg</div>
                  </div>
                )}
              </>
            ) : (
              <div className="text-[11px] text-slate-400">
                Hover over map to see PM2.5
              </div>
            )}
          </div>
        </div>
      )}

      {/* Layer indicators + fire badge — bottom right */}
      <div className="absolute right-3 bottom-8 z-10 flex flex-col items-end gap-1.5">
        {/* Layer toggle buttons */}
        <div className="flex items-center gap-1">
          <button
            onPointerDown={(e) => { e.stopPropagation(); onToggleStations?.(); if (!onToggleStations) setShowStationsLocal(v => !v) }}
            className={`w-7 h-7 rounded-lg backdrop-blur-sm ring-1 flex items-center justify-center transition-all cursor-pointer pointer-events-auto ${
              showStations ? 'bg-slate-800/85 ring-white/10' : 'bg-slate-800/50 ring-white/5 opacity-60'
            }`}
            title={showStations ? 'Hide stations' : 'Show stations'}
          >
            <svg className={`w-3.5 h-3.5 ${showStations ? 'text-amber-400' : 'text-white/25'}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 10.5a3 3 0 11-6 0 3 3 0 016 0z" />
              <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 10.5c0 7.142-7.5 11.25-7.5 11.25S4.5 17.642 4.5 10.5a7.5 7.5 0 1115 0z" />
            </svg>
          </button>
          <button
            onPointerDown={(e) => { e.stopPropagation(); onToggleSatellite?.(); if (!onToggleSatellite) setShowSatelliteLocal(v => !v) }}
            className={`w-7 h-7 rounded-lg backdrop-blur-sm ring-1 flex items-center justify-center transition-all cursor-pointer pointer-events-auto ${
              showSatellite ? 'bg-slate-800/85 ring-white/10' : 'bg-slate-800/50 ring-white/5 opacity-60'
            }`}
            title={showSatellite ? 'Hide PM2.5' : 'Show PM2.5'}
          >
            <svg className={`w-3.5 h-3.5 ${showSatellite ? 'text-indigo-400' : 'text-white/25'}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 3.75H6A2.25 2.25 0 003.75 6v1.5M16.5 3.75H18A2.25 2.25 0 0120.25 6v1.5m0 9V18A2.25 2.25 0 0118 20.25h-1.5m-9 0H6A2.25 2.25 0 013.75 18v-1.5" />
              <circle cx="12" cy="12" r="3" />
            </svg>
          </button>
          <button
            onPointerDown={(e) => { e.stopPropagation(); onToggleWind?.(); if (!onToggleWind) setShowWindLocal(v => !v) }}
            className={`w-7 h-7 rounded-lg backdrop-blur-sm ring-1 flex items-center justify-center transition-all cursor-pointer pointer-events-auto ${
              showWind ? 'bg-slate-800/85 ring-white/10' : 'bg-slate-800/50 ring-white/5 opacity-60'
            }`}
            title={showWind ? 'Hide wind' : 'Show wind'}
          >
            <svg className={`w-3.5 h-3.5 ${showWind ? 'text-sky-400' : 'text-white/25'}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9.59 4.59A2 2 0 1111 8H2m10.59 11.41A2 2 0 1014 16H2m15.73-8.27A2.5 2.5 0 1119.5 12H2" />
            </svg>
          </button>
          <button
            onPointerDown={(e) => { e.stopPropagation(); onToggleFires?.(); if (!onToggleFires) setShowFiresLocal(v => !v) }}
            className={`w-7 h-7 rounded-lg backdrop-blur-sm ring-1 flex items-center justify-center transition-all cursor-pointer pointer-events-auto ${
              showFires ? 'bg-slate-800/85 ring-white/10' : 'bg-slate-800/50 ring-white/5 opacity-60'
            }`}
            title={showFires ? 'Hide fires' : 'Show fires'}
          >
            <svg className={`w-3.5 h-3.5 ${showFires ? 'text-orange-400' : 'text-white/25'}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15.362 5.214A8.252 8.252 0 0112 21 8.25 8.25 0 016.038 7.048 8.287 8.287 0 009 9.6a8.983 8.983 0 013.361-6.867 8.21 8.21 0 003 2.48z" />
            </svg>
          </button>
          <button
            onPointerDown={(e) => { e.stopPropagation(); onTogglePopulation?.(); if (!onTogglePopulation) setShowPopulationLocal(v => !v) }}
            className={`w-7 h-7 rounded-lg backdrop-blur-sm ring-1 flex items-center justify-center transition-all cursor-pointer pointer-events-auto ${
              showPopulation ? 'bg-slate-800/85 ring-white/10' : 'bg-slate-800/50 ring-white/5 opacity-60'
            }`}
            title={showPopulation ? 'Hide population' : 'Show population'}
          >
            <svg className={`w-3.5 h-3.5 ${showPopulation ? 'text-purple-400' : 'text-white/25'}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z" />
            </svg>
          </button>
        </div>

        {/* Fire count */}
        {showFires && firesGeoJSON && firesGeoJSON.features.length > 0 && (
          <div className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-slate-800/85 backdrop-blur-sm shadow-lg text-[11px] font-medium text-amber-400 ring-1 ring-white/10">
            <svg className="w-3.5 h-3.5 text-orange-400" fill="currentColor" viewBox="0 0 24 24">
              <path d="M12 23c-3.6 0-8-3.2-8-9.1C4 7.4 11.3 1.3 11.6 1.1a.7.7 0 01.9 0c.2.2 7.5 6.3 7.5 12.8 0 5.9-4.4 9.1-8 9.1zm0-19.6C10 5.5 6 10.2 6 13.9 6 18.5 9.3 21 12 21s6-2.5 6-7.1c0-3.7-4-8.4-6-10.5z"/>
              <path d="M12 21c-2 0-4-1.6-4-4.6 0-2.4 3.3-5.5 3.5-5.6a.7.7 0 01.9 0c.2.1 3.6 3.2 3.6 5.6 0 3-2 4.6-4 4.6zm0-8c-1.2 1.3-2 3-2 3.4 0 2 1.2 3 2 3s2-1 2-3c0-.5-.8-2.1-2-3.4z"/>
            </svg>
            <span>{firesGeoJSON.features.length} active</span>
          </div>
        )}
      </div>

      {/* Popup styling */}
      <style jsx global>{`
        .horizon-slider::-webkit-slider-thumb {
          -webkit-appearance: none;
          appearance: none;
          width: 20px;
          height: 20px;
          border-radius: 50%;
          background: #34d399;
          box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1), 0 2px 4px -2px rgba(0,0,0,0.1);
          cursor: grab;
          border: 2px solid white;
        }
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
        /* 3D marker floating effect */
        .aqi-marker-container {
          filter: drop-shadow(0 3px 4px rgba(0,0,0,0.2));
          transition: filter 0.3s;
        }
        .aqi-marker-container:hover {
          filter: drop-shadow(0 6px 8px rgba(0,0,0,0.3));
          transform: translateY(-2px);
        }
        .aqi-marker-container:hover .aqi-stem {
          height: 22px !important;
        }
      `}</style>
    </div>
  )
}
