"use client"

import { useRef, useState, useEffect } from 'react'
import { Loader2 } from 'lucide-react'
import mapboxgl from 'mapbox-gl'
import 'mapbox-gl/dist/mapbox-gl.css'
import { API_BASE, API_TOKEN } from './api'

mapboxgl.accessToken = '***REMOVED***'

const STYLE_URL = 'mapbox://styles/rehan0900/cmmh9p69z009m01qu0nnn3iwu'
const INITIAL_CENTER: [number, number] = [69.3459, 30.3]
const INITIAL_ZOOM = 3.5

// Urban cities for 1km downscaler overlay
const URBAN_CITIES = [
  { key: 'lahore', bounds: [74.0, 31.2, 74.6, 31.8] as [number, number, number, number] },
  { key: 'isb_rwp', bounds: [72.6, 33.3, 73.3, 33.9] as [number, number, number, number] },
  { key: 'peshawar', bounds: [71.3, 33.8, 71.9, 34.3] as [number, number, number, number] },
  { key: 'karachi', bounds: [66.7, 24.7, 67.3, 25.3] as [number, number, number, number] },
]

interface UrbanGrid {
  resolution: number
  bounds: { west: number; east: number; south: number; north: number }
  shape: [number, number]
  pm25: (number | null)[]
}

interface PredictionMapProps {
  selectedDate: string
  smoothed?: boolean
  model?: 'backbone' | 'support_aware'
}

interface SelectedDistrict {
  name: string
  pm25: number | null
}

interface HoverPM25 {
  pm25: number
  lat: number
  lon: number
  label: string
}

export function PredictionMap({ selectedDate, smoothed = false, model = 'backbone' }: PredictionMapProps) {
  const mapContainer = useRef<HTMLDivElement>(null)
  const mapRef = useRef<mapboxgl.Map | null>(null)
  const [mapLoaded, setMapLoaded] = useState(false)
  const [hoveredDistrict, setHoveredDistrict] = useState<string | null>(null)
  const [selectedDistrict, setSelectedDistrict] = useState<SelectedDistrict | null>(null)
  const [hoverPM25, setHoverPM25] = useState<HoverPM25 | null>(null)

  // Refs for urban grid hover (same pattern as ForecastMap)
  const urbanGridsRef = useRef<Map<string, UrbanGrid>>(new Map())
  const urbanGridLoadingRef = useRef<Set<string>>(new Set())
  const selectedDateRef = useRef(selectedDate)

  useEffect(() => {
    selectedDateRef.current = selectedDate
  }, [selectedDate])

  // Initialize map once
  useEffect(() => {
    if (!mapContainer.current || mapRef.current) return

    const map = new mapboxgl.Map({
      container: mapContainer.current,
      style: STYLE_URL,
      center: INITIAL_CENTER,
      zoom: INITIAL_ZOOM,
      minZoom: 2,
      maxZoom: 15,
      attributionControl: false,
      transformRequest: (url: string) => {
        if (url.includes('/ops/pipeline/tiles/') || url.includes('/ops/downscaler/tiles/')) {
          return {
            url,
            headers: { Authorization: `Bearer ${API_TOKEN}` }
          }
        }
        return { url }
      }
    })

    mapRef.current = map

    map.on('load', async () => {
      // Load boundaries
      const districtsResponse = await fetch('/pakistan_districts.geojson')
      const districtsGeoJSON = await districtsResponse.json()
      const adm1Response = await fetch('/pakistan_adm1.geojson')
      const adm1GeoJSON = await adm1Response.json()
      const dissolvedResponse = await fetch('/pakistan_adm2_dissolved.geojson')
      const dissolvedGeoJSON = await dissolvedResponse.json()

      // Add sources
      map.addSource('pakistan-districts', { type: 'geojson', data: districtsGeoJSON, promoteId: 'shapeName' })
      map.addSource('pakistan-adm1', { type: 'geojson', data: adm1GeoJSON })
      map.addSource('pakistan-boundary', { type: 'geojson', data: dissolvedGeoJSON })

      // National COG tile source
      const params = [smoothed && 'smoothed=true', model !== 'backbone' && `model=${model}`].filter(Boolean).join('&')
      const tileUrl = `${API_BASE}/api/v1/ops/pipeline/tiles/${selectedDate}/{z}/{x}/{y}.png${params ? '?' + params : ''}`
      map.addSource('pm25-tiles', {
        type: 'raster',
        tiles: [tileUrl],
        tileSize: 256,
        bounds: [60.45, 23.25, 77.95, 37.35],
        minzoom: 0,
        maxzoom: 12,
      })

      // 1. National PM2.5 raster — fades at high zoom to let downscaler take over
      map.addLayer({
        id: 'pm25-raster',
        type: 'raster',
        source: 'pm25-tiles',
        slot: 'middle',
        paint: {
          'raster-opacity': [
            'interpolate', ['linear'], ['zoom'],
            3, 0.85,
            9, 0.3,
            12, 0.15,
          ],
          'raster-resampling': 'linear',
        },
      })

      // ── Urban 1km downscaler layers (overlay at high zoom) ──
      for (const city of URBAN_CITIES) {
        const srcId = `urban-${city.key}`
        const layerId = `urban-${city.key}-layer`
        try {
          map.addSource(srcId, {
            type: 'raster',
            tiles: [
              `${API_BASE}/api/v1/ops/downscaler/tiles/${city.key}/${selectedDate}/{z}/{x}/{y}.png?smoothed=true`,
            ],
            tileSize: 256,
            minzoom: 9,
            maxzoom: 15,
            bounds: city.bounds,
          })
          map.addLayer({
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
            slot: 'middle',
          })
        } catch (e) {
          console.warn(`[Urban] Failed to add ${layerId}:`, e)
        }
      }

      // 2. District fill layer (transparent, for interaction)
      map.addLayer({
        id: 'districts-fill', type: 'fill', source: 'pakistan-districts',
        paint: { 'fill-color': 'transparent', 'fill-opacity': 0 }
      })

      // 3. District hover highlight
      map.addLayer({
        id: 'districts-hover', type: 'fill', source: 'pakistan-districts',
        paint: {
          'fill-color': '#ffffff',
          'fill-opacity': ['case', ['boolean', ['feature-state', 'hover'], false], 0.3, 0]
        }
      })

      // 4. District selection highlight
      map.addLayer({
        id: 'districts-selected', type: 'fill', source: 'pakistan-districts',
        paint: {
          'fill-color': '#3b82f6',
          'fill-opacity': ['case', ['boolean', ['feature-state', 'selected'], false], 0.4, 0]
        }
      })

      // 5. District borders
      map.addLayer({
        id: 'districts-borders', type: 'line', source: 'pakistan-districts',
        paint: {
          'line-color': ['case',
            ['boolean', ['feature-state', 'selected'], false], '#475569',
            ['boolean', ['feature-state', 'hover'], false], '#64748b',
            '#94a3b8'],
          'line-width': ['case',
            ['boolean', ['feature-state', 'selected'], false], 1.5,
            ['boolean', ['feature-state', 'hover'], false], 1,
            0.3],
          'line-opacity': 0.5
        }
      })

      // 6. Province borders
      map.addLayer({
        id: 'province-borders', type: 'line', source: 'pakistan-adm1',
        paint: { 'line-color': '#94a3b8', 'line-width': 1, 'line-opacity': 0.7 }
      })

      // 7. Country outline
      map.addLayer({
        id: 'country-outline', type: 'line', source: 'pakistan-boundary',
        paint: { 'line-color': '#64748b', 'line-width': 1.5, 'line-opacity': 0.9 }
      })

      // ── Hover: district + urban grid readout ──
      let hoveredId: string | null = null

      // Fetch urban grid JSON once per city (cached)
      const ensureUrbanGrid = (cityKey: string) => {
        if (urbanGridsRef.current.has(cityKey) || urbanGridLoadingRef.current.has(cityKey)) return
        urbanGridLoadingRef.current.add(cityKey)
        fetch(`${API_BASE}/api/v1/ops/downscaler/grid/${cityKey}/${selectedDateRef.current}`, {
          headers: { Authorization: `Bearer ${API_TOKEN}` },
        })
          .then(r => r.ok ? r.json() : null)
          .then(data => {
            if (!data) return
            urbanGridsRef.current.set(cityKey, {
              resolution: data.grid?.resolution || 0.01,
              bounds: data.grid?.bounds || {},
              shape: data.grid?.shape || [0, 0],
              pm25: data.pm25 || [],
            })
          })
          .catch(() => {})
          .finally(() => urbanGridLoadingRef.current.delete(cityKey))
      }

      // O(1) grid lookup
      const lookupUrbanPM25 = (cityKey: string, lat: number, lng: number): number | null => {
        const grid = urbanGridsRef.current.get(cityKey)
        if (!grid || !grid.pm25.length) return null
        const { bounds, shape, resolution } = grid
        const row = Math.floor((lat - bounds.south) / resolution)
        const col = Math.floor((lng - bounds.west) / resolution)
        if (row < 0 || row >= shape[0] || col < 0 || col >= shape[1]) return null
        const idx = row * shape[1] + col
        return grid.pm25[idx]
      }

      // Combined mousemove: district hover + urban grid readout
      map.on('mousemove', (e) => {
        const zoom = map.getZoom()
        const { lng, lat } = e.lngLat

        // Urban grid hover at high zoom
        if (zoom >= 8) {
          const city = URBAN_CITIES.find(c =>
            lng >= c.bounds[0] && lng <= c.bounds[2] &&
            lat >= c.bounds[1] && lat <= c.bounds[3]
          )
          if (city) {
            ensureUrbanGrid(city.key)
            const val = lookupUrbanPM25(city.key, lat, lng)
            if (val != null) {
              setHoverPM25({ pm25: val, lat, lon: lng, label: '1km Downscaler' })
            } else {
              setHoverPM25(null)
            }
          } else {
            setHoverPM25(null)
          }
        } else {
          setHoverPM25(null)
        }
      })

      // District hover
      map.on('mousemove', 'districts-fill', (e) => {
        if (e.features && e.features.length > 0) {
          const feature = e.features[0]
          const newId = feature.properties?.shapeName
          if (hoveredId !== newId) {
            if (hoveredId) map.setFeatureState({ source: 'pakistan-districts', id: hoveredId }, { hover: false })
            hoveredId = newId
            map.setFeatureState({ source: 'pakistan-districts', id: newId }, { hover: true })
            setHoveredDistrict(newId)
          }
          map.getCanvas().style.cursor = 'pointer'
        }
      })

      map.on('mouseleave', 'districts-fill', () => {
        if (hoveredId) {
          map.setFeatureState({ source: 'pakistan-districts', id: hoveredId }, { hover: false })
          hoveredId = null
        }
        setHoveredDistrict(null)
        setHoverPM25(null)
        map.getCanvas().style.cursor = ''
      })

      // Click handler - select district and fetch PM2.5
      let selectedId: string | null = null

      map.on('click', 'districts-fill', async (e) => {
        if (!e.features || e.features.length === 0) return
        const feature = e.features[0]
        const districtName = feature.properties?.shapeName
        const newId = districtName

        if (selectedId) map.setFeatureState({ source: 'pakistan-districts', id: selectedId }, { selected: false })
        selectedId = newId
        map.setFeatureState({ source: 'pakistan-districts', id: newId }, { selected: true })

        let centroid: [number, number]
        if (feature.geometry.type === 'Polygon') {
          centroid = getCentroid((feature.geometry as any).coordinates[0])
        } else if (feature.geometry.type === 'MultiPolygon') {
          const largest = (feature.geometry as any).coordinates.reduce((a: any, b: any) =>
            a[0].length > b[0].length ? a : b
          )
          centroid = getCentroid(largest[0])
        } else {
          centroid = [e.lngLat.lng, e.lngLat.lat]
        }

        try {
          const extraParams = [smoothed && 'smoothed=true', model !== 'backbone' && `model=${model}`].filter(Boolean).map(p => '&' + p).join('')
          const res = await fetch(
            `${API_BASE}/api/v1/ops/pipeline/tiles/${selectedDate}/point?lat=${centroid[1]}&lon=${centroid[0]}${extraParams}`,
            { headers: { Authorization: `Bearer ${API_TOKEN}` } }
          )
          if (res.ok) {
            const data = await res.json()
            setSelectedDistrict({ name: districtName, pm25: data.pm25 })
          } else {
            setSelectedDistrict({ name: districtName, pm25: null })
          }
        } catch {
          setSelectedDistrict({ name: districtName, pm25: null })
        }
      })

      map.on('click', (e) => {
        const features = map.queryRenderedFeatures(e.point, { layers: ['districts-fill'] })
        if (features.length === 0 && selectedId) {
          map.setFeatureState({ source: 'pakistan-districts', id: selectedId }, { selected: false })
          selectedId = null
          setSelectedDistrict(null)
        }
      })

      setMapLoaded(true)
    })

    return () => {
      if (mapRef.current) {
        mapRef.current.remove()
        mapRef.current = null
      }
    }
  }, [])

  // Update tile sources when date/smoothed/model changes
  useEffect(() => {
    if (!mapRef.current || !mapLoaded) return
    const map = mapRef.current

    // ── Update national tiles ──
    const params = [smoothed && 'smoothed=true', model !== 'backbone' && `model=${model}`].filter(Boolean).join('&')
    const tileUrl = `${API_BASE}/api/v1/ops/pipeline/tiles/${selectedDate}/{z}/{x}/{y}.png${params ? '?' + params : ''}`

    if (map.getLayer('pm25-raster')) map.removeLayer('pm25-raster')
    if (map.getSource('pm25-tiles')) map.removeSource('pm25-tiles')

    map.addSource('pm25-tiles', {
      type: 'raster',
      tiles: [tileUrl],
      tileSize: 256,
      bounds: [60.45, 23.25, 77.95, 37.35],
      minzoom: 0,
      maxzoom: 12,
    })
    map.addLayer({
      id: 'pm25-raster',
      type: 'raster',
      source: 'pm25-tiles',
      slot: 'middle',
      paint: {
        'raster-opacity': [
          'interpolate', ['linear'], ['zoom'],
          3, 0.85,
          9, 0.3,
          12, 0.15,
        ],
        'raster-resampling': 'linear',
      },
    })

    // ── Update urban tiles ──
    for (const city of URBAN_CITIES) {
      const srcId = `urban-${city.key}`
      const layerId = `urban-${city.key}-layer`
      try {
        if (map.getLayer(layerId)) map.removeLayer(layerId)
        if (map.getSource(srcId)) map.removeSource(srcId)

        map.addSource(srcId, {
          type: 'raster',
          tiles: [`${API_BASE}/api/v1/ops/downscaler/tiles/${city.key}/${selectedDate}/{z}/{x}/{y}.png?smoothed=true`],
          tileSize: 256,
          minzoom: 9,
          maxzoom: 15,
          bounds: city.bounds,
        })
        map.addLayer({
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
          slot: 'middle',
        })
      } catch (e) {
        console.warn(`[Urban] Failed to update ${layerId}:`, e)
      }
    }

    // Clear cached grids (date changed, grids are stale)
    urbanGridsRef.current.clear()
    urbanGridLoadingRef.current.clear()

    setSelectedDistrict(null)
    setHoverPM25(null)
  }, [selectedDate, smoothed, model, mapLoaded])

  return (
    <div className="relative w-full h-full">
      <div ref={mapContainer} className="w-full h-full" />

      {/* Urban grid hover readout */}
      {hoverPM25 && !selectedDistrict && (
        <div className="absolute bottom-16 left-4 z-20 bg-white/95 backdrop-blur-sm rounded-lg shadow-lg border border-slate-200/60 px-3 py-2">
          <div className="text-[10px] text-emerald-600 font-semibold uppercase tracking-wide">{hoverPM25.label}</div>
          <div className="flex items-baseline gap-1 mt-0.5">
            <span className="text-xl font-bold text-slate-900">{hoverPM25.pm25.toFixed(1)}</span>
            <span className="text-xs text-slate-500">µg/m³</span>
          </div>
        </div>
      )}

      {/* Selected district info panel */}
      {selectedDistrict && (
        <div className="absolute top-6 left-6 bg-white/95 backdrop-blur-sm rounded-xl shadow-2xl border border-slate-200/60 overflow-hidden min-w-[200px]">
          <div className="px-4 py-3 bg-slate-50 border-b border-slate-200">
            <h3 className="text-lg font-bold text-slate-800">{selectedDistrict.name}</h3>
          </div>
          <div className="px-4 py-4">
            <div className="text-xs text-slate-500 uppercase tracking-wide font-medium">PM₂.₅ Concentration</div>
            <div className="flex items-baseline gap-1.5 mt-1">
              <span className="text-3xl font-bold text-slate-900">
                {selectedDistrict.pm25 !== null ? selectedDistrict.pm25.toFixed(1) : '—'}
              </span>
              <span className="text-sm text-slate-500">μg/m³</span>
            </div>
          </div>
        </div>
      )}

      {/* Hover tooltip (district level, low zoom) */}
      {hoveredDistrict && !selectedDistrict && !hoverPM25 && (
        <div className="absolute top-6 left-6 bg-white/95 backdrop-blur-sm rounded-xl shadow-2xl border border-slate-200/60 overflow-hidden px-4 py-3">
          <h3 className="text-lg font-bold text-slate-800">{hoveredDistrict}</h3>
          <p className="text-sm text-slate-500 mt-1">Click for details</p>
        </div>
      )}

      {!mapLoaded && (
        <div className="absolute inset-0 flex items-center justify-center bg-slate-100">
          <Loader2 className="w-8 h-8 animate-spin text-blue-500" />
        </div>
      )}
    </div>
  )
}

function getCentroid(ring: number[][]): [number, number] {
  let x = 0, y = 0
  for (const coord of ring) {
    x += coord[0]
    y += coord[1]
  }
  return [x / ring.length, y / ring.length]
}
