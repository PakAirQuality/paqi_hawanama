"use client"

import { useRef, useState, useEffect } from 'react'
import { Loader2, X } from 'lucide-react'
import mapboxgl from 'mapbox-gl'
import 'mapbox-gl/dist/mapbox-gl.css'
import { API_BASE, API_TOKEN } from './api'

mapboxgl.accessToken = process.env.NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN || ''

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

interface StationReading {
  name: string
  city: string
  pm25: number
  lat: number
  lon: number
  latitude?: number
  longitude?: number
  valid_hours?: number | null
  complete?: boolean
}

interface PredictionMapProps {
  selectedDate: string
  smoothed?: boolean
  model?: 'backbone' | 'support_aware'
  showKilns?: boolean
  showIndustry?: boolean
  onMapReady?: (flyTo: (lng: number, lat: number, zoom?: number) => void) => void
}

interface SelectedDistrict {
  name: string
  pm25: number | null
  stations: StationReading[]
}

interface HoverPM25 {
  pm25: number
  lat: number
  lon: number
  label: string
}

// AQI band classification + marker factory (same as analyst desk ForecastMap)
function pm25ToBand(pm25: number): string {
  if (pm25 <= 35) return 'good'
  if (pm25 <= 75) return 'moderate'
  if (pm25 <= 150) return 'unhealthy'
  if (pm25 <= 250) return 'very_unhealthy'
  return 'severe'
}

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

const BAND_COLORS: Record<string, string> = {
  good: '#6ecc39',
  moderate: '#f0c20c',
  unhealthy: '#ef7855',
  very_unhealthy: '#a070b5',
  severe: '#991b1b',
}

function createMarkerEl(value: number | null | undefined, colorClass: string): HTMLDivElement {
  const container = document.createElement('div')
  container.className = 'aqi-marker-container point'
  container.style.cssText = 'width:28px;display:flex;flex-direction:column;align-items:center;'

  const marker = document.createElement('div')
  marker.className = `aqi-marker ${colorClass}`
  marker.textContent = value != null ? `${Math.round(value)}` : '-'

  const stem = document.createElement('div')
  stem.className = 'aqi-stem'
  stem.style.cssText = 'width:1.5px;height:0px;background:rgba(0,0,0,0.25);transition:height 0.3s;'

  const dot = document.createElement('div')
  dot.className = 'aqi-ground-dot'
  dot.style.cssText = 'width:4px;height:2px;border-radius:50%;background:rgba(0,0,0,0.15);transition:opacity 0.3s;opacity:0;'

  container.appendChild(marker)
  container.appendChild(stem)
  container.appendChild(dot)
  return container
}

export function PredictionMap({ selectedDate, smoothed = false, model = 'backbone', showKilns = true, showIndustry = false, onMapReady }: PredictionMapProps) {
  const mapContainer = useRef<HTMLDivElement>(null)
  const mapRef = useRef<mapboxgl.Map | null>(null)
  const [mapLoaded, setMapLoaded] = useState(false)
  const [hoveredDistrict, setHoveredDistrict] = useState<string | null>(null)
  const [selectedDistrict, setSelectedDistrict] = useState<SelectedDistrict | null>(null)
  const [hoverPM25, setHoverPM25] = useState<HoverPM25 | null>(null)

  // Station markers
  const markersRef = useRef<mapboxgl.Marker[]>([])
  const [stations, setStations] = useState<StationReading[]>([])
  const stationsRef = useRef<StationReading[]>([])
  const [hoveredStation, setHoveredStation] = useState<StationReading | null>(null)

  // Refs for urban grid hover (same pattern as ForecastMap)
  const urbanGridsRef = useRef<Map<string, UrbanGrid>>(new Map())
  const urbanGridLoadingRef = useRef<Set<string>>(new Set())
  const selectedDateRef = useRef(selectedDate)

  useEffect(() => {
    selectedDateRef.current = selectedDate
  }, [selectedDate])

  // Fetch QA-filtered station daily means for the selected date (same labels as model training)
  useEffect(() => {
    const fetchStations = async () => {
      try {
        const res = await fetch(
          `${API_BASE}/api/v1/ops/pipeline/stations/daily/${selectedDate}?min_hours=6&country=Pakistan`,
          { headers: { Authorization: `Bearer ${API_TOKEN}` } }
        )
        if (res.ok) {
          const data = await res.json()
          const s = data?.stations ?? []
          setStations(s)
          stationsRef.current = s
        } else {
          setStations([])
          stationsRef.current = []
        }
      } catch {
        setStations([])
        stationsRef.current = []
      }
    }
    fetchStations()
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

    // Expose flyTo callback to parent
    onMapReady?.((lng: number, lat: number, zoom?: number) => {
      map.flyTo({ center: [lng, lat], zoom: zoom ?? 12, duration: 1200 })
    })

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

      // 1. National PM2.5 raster — the hero layer
      //    Far: strong presence. Close: yields to downscaler + contextual layers.
      map.addLayer({
        id: 'pm25-raster',
        type: 'raster',
        source: 'pm25-tiles',
        slot: 'middle',
        paint: {
          'raster-opacity': [
            'interpolate', ['linear'], ['zoom'],
            3, 0.7,
            7, 0.65,
            9, 0.4,
            12, 0.2,
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
                10, 0.35,
                11, 0.55,
                13, 0.65,
                15, 0.5,
              ],
            },
            slot: 'middle',
          })
        } catch (e) {
          console.warn(`[Urban] Failed to add ${layerId}:`, e)
        }
      }

      // ── Brick kilns — secondary explanatory layer, reveals on zoom ──
      //    z<8.5: hidden. z8.5-10: subtle amber dots. z10+: chimney icons. z12+: hover popups.
      try {
        const kilnsRes = await fetch('/brick_kilns.geojson')
        const kilnsGeoJSON = await kilnsRes.json()
        map.addSource('brick-kilns', { type: 'geojson', data: kilnsGeoJSON })

        // Generate chimney icon (SVG → canvas → map image)
        const chimneyImg = await new Promise<HTMLImageElement>((resolve) => {
          const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="28" viewBox="0 0 24 28">
            <!-- Chimney stack -->
            <rect x="8" y="6" width="8" height="16" rx="1" fill="#b45309" stroke="#92400e" stroke-width="0.8"/>
            <!-- Chimney top rim -->
            <rect x="6.5" y="4" width="11" height="3" rx="1" fill="#d97706" stroke="#92400e" stroke-width="0.6"/>
            <!-- Base/foundation -->
            <rect x="5" y="22" width="14" height="4" rx="1" fill="#78716c" stroke="#57534e" stroke-width="0.6"/>
            <!-- Smoke puffs -->
            <circle cx="12" cy="2.5" r="2" fill="#d97706" opacity="0.5"/>
            <circle cx="15" cy="1.5" r="1.5" fill="#d97706" opacity="0.35"/>
            <circle cx="9.5" cy="1" r="1.2" fill="#d97706" opacity="0.25"/>
          </svg>`
          const img = new Image()
          img.onload = () => resolve(img)
          img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg)
        })
        if (!map.hasImage('kiln-chimney')) {
          map.addImage('kiln-chimney', chimneyImg, { sdf: false })
        }

        // Soft glow halo — ambient presence at medium zoom
        map.addLayer({
          id: 'brick-kilns-glow', type: 'circle', source: 'brick-kilns',
          minzoom: 8.5,
          paint: {
            'circle-radius': ['interpolate', ['linear'], ['zoom'], 8.5, 3, 10, 6, 12, 10, 14, 14],
            'circle-color': '#d97706',
            'circle-opacity': ['interpolate', ['linear'], ['zoom'],
              8.5, 0,
              9.5, 0.04,
              10.5, 0.08,
              12, 0.1,
            ],
            'circle-blur': 1,
          },
        })

        // Small amber dots — the earliest hint (z8.5-10)
        map.addLayer({
          id: 'brick-kilns-dots', type: 'circle', source: 'brick-kilns',
          minzoom: 8.5,
          maxzoom: 11,
          paint: {
            'circle-radius': ['interpolate', ['linear'], ['zoom'], 8.5, 1, 10, 2.5],
            'circle-color': '#d97706',
            'circle-opacity': ['interpolate', ['linear'], ['zoom'],
              8.5, 0,
              9.5, 0.25,
              10.5, 0.5,
            ],
          },
        })

        // Chimney icons — appear at z10+ as the dots phase out
        map.addLayer({
          id: 'brick-kilns-layer', type: 'symbol', source: 'brick-kilns',
          minzoom: 10,
          layout: {
            'icon-image': 'kiln-chimney',
            'icon-size': ['interpolate', ['linear'], ['zoom'], 10, 0.4, 12, 0.65, 14, 0.9],
            'icon-allow-overlap': true,
            'icon-ignore-placement': true,
          },
          paint: {
            'icon-opacity': ['interpolate', ['linear'], ['zoom'],
              10, 0.3,
              11, 0.6,
              12, 0.85,
            ],
          },
        })

        // Hover popup — z10+
        const kilnPopup = new mapboxgl.Popup({ closeButton: false, closeOnClick: false, maxWidth: '220px' })

        map.on('mouseenter', 'brick-kilns-layer', (e) => {
          if (!e.features?.[0] || map.getZoom() < 10) return
          map.getCanvas().style.cursor = 'pointer'
          const props = e.features[0].properties!
          const coords = (e.features[0].geometry as GeoJSON.Point).coordinates.slice() as [number, number]
          kilnPopup.setLngLat(coords).setHTML(`
            <div style="font-family:system-ui,-apple-system,sans-serif;font-size:12px;line-height:1.5">
              <div style="font-weight:600;color:#b45309;margin-bottom:4px">Brick Kiln ${props.id || ''}</div>
              <div>PM₂.₅: <b>${props.pm25_t_yr ?? '—'} t/yr</b></div>
              <div>Fuel: <b style="text-transform:capitalize">${props.fuel || '—'}</b></div>
              <div>State: <b>${props.state || '—'}</b></div>
              ${props.pop1km ? `<div style="color:#64748b;font-size:11px;margin-top:2px">Pop within 1km: ${Number(props.pop1km).toLocaleString()}</div>` : ''}
            </div>
          `).addTo(map)
        })

        map.on('mouseleave', 'brick-kilns-layer', () => {
          map.getCanvas().style.cursor = ''
          kilnPopup.remove()
        })
      } catch (e) {
        console.warn('[BrickKilns] Failed to load:', e)
      }

      // ── Industrial emission sources (power plants, cement, steel, etc.) ──
      try {
        const srcRes = await fetch('/emission_sources.json')
        const srcData = await srcRes.json()

        const INDUSTRY_LAYERS = [
          { key: 'power_plants', color: '#ef4444', label: 'Power Plant' },
          { key: 'cement_plants', color: '#8b5cf6', label: 'Cement Plant' },
          { key: 'steel_sites', color: '#6366f1', label: 'Steel Site' },
          { key: 'sugar_mills', color: '#10b981', label: 'Sugar Mill' },
          { key: 'industrial_sites', color: '#64748b', label: 'Industrial' },
          { key: 'mines_quarries', color: '#78716c', label: 'Mine/Quarry' },
        ]

        const industryPopup = new mapboxgl.Popup({ closeButton: false, closeOnClick: false, maxWidth: '220px' })

        for (const layer of INDUSTRY_LAYERS) {
          if (!srcData[layer.key]?.features?.length) continue
          const srcId = `industry-${layer.key}`
          const layerId = `industry-${layer.key}-layer`

          map.addSource(srcId, { type: 'geojson', data: srcData[layer.key] })
          map.addLayer({
            id: layerId, type: 'circle', source: srcId,
            minzoom: 7,
            layout: { visibility: 'none' },
            paint: {
              'circle-radius': ['interpolate', ['linear'], ['zoom'], 7, 2, 10, 4, 12, 7],
              'circle-color': layer.color,
              'circle-opacity': ['interpolate', ['linear'], ['zoom'],
                7, 0,
                8.5, 0.3,
                10, 0.7,
                12, 0.85,
              ],
              'circle-stroke-width': ['interpolate', ['linear'], ['zoom'], 7, 0, 10, 1],
              'circle-stroke-color': 'rgba(255,255,255,0.5)',
            },
          })

          map.on('mouseenter', layerId, (e) => {
            if (!e.features?.[0]) return
            map.getCanvas().style.cursor = 'pointer'
            const props = e.features[0].properties!
            const coords = (e.features[0].geometry as GeoJSON.Point).coordinates.slice() as [number, number]
            const lines = [`<div style="font-weight:600;color:${layer.color};margin-bottom:4px">${layer.label}</div>`]
            if (props.name) lines.push(`<div><b>${props.name}</b></div>`)
            if (props.fuel) lines.push(`<div>Fuel: <b>${props.fuel}</b></div>`)
            if (props.capacity_mw) lines.push(`<div>Capacity: <b>${props.capacity_mw} MW</b></div>`)
            if (props.capacity_mtpa) lines.push(`<div>Capacity: <b>${props.capacity_mtpa} Mt/yr</b></div>`)
            if (props.province) lines.push(`<div style="color:#64748b;font-size:11px">${props.province}</div>`)
            industryPopup.setLngLat(coords).setHTML(
              `<div style="font-family:system-ui,-apple-system,sans-serif;font-size:12px;line-height:1.5">${lines.join('')}</div>`
            ).addTo(map)
          })
          map.on('mouseleave', layerId, () => {
            map.getCanvas().style.cursor = ''
            industryPopup.remove()
          })
        }
      } catch (e) {
        console.warn('[Industry] Failed to load:', e)
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

        // Find stations in this district by city name match
        const districtLower = (districtName ?? '').toLowerCase()
        const districtStations = stationsRef.current.filter(s => {
          const city = (s.city ?? '').toLowerCase()
          return city.includes(districtLower) || districtLower.includes(city)
        })

        try {
          const extraParams = [smoothed && 'smoothed=true', model !== 'backbone' && `model=${model}`].filter(Boolean).map(p => '&' + p).join('')
          const res = await fetch(
            `${API_BASE}/api/v1/ops/pipeline/tiles/${selectedDate}/point?lat=${centroid[1]}&lon=${centroid[0]}${extraParams}`,
            { headers: { Authorization: `Bearer ${API_TOKEN}` } }
          )
          if (res.ok) {
            const data = await res.json()
            setSelectedDistrict({ name: districtName, pm25: data.pm25, stations: districtStations })
          } else {
            setSelectedDistrict({ name: districtName, pm25: null, stations: districtStations })
          }
        } catch {
          setSelectedDistrict({ name: districtName, pm25: null, stations: districtStations })
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

  // Render station markers
  useEffect(() => {
    if (!mapRef.current || !mapLoaded) return

    // Remove old markers
    markersRef.current.forEach(m => m.remove())
    markersRef.current = []

    const map = mapRef.current!

    for (const stn of stations) {
      const lat = stn.lat ?? stn.latitude
      const lon = stn.lon ?? stn.longitude
      if (lat == null || lon == null || stn.pm25 == null) continue

      const band = pm25ToBand(stn.pm25)
      const colorClass = bandToMarkerClass(band)
      const el = createMarkerEl(stn.pm25, colorClass)

      el.addEventListener('mouseenter', () => setHoveredStation(stn))
      el.addEventListener('mouseleave', () => setHoveredStation(null))

      const marker = new mapboxgl.Marker({ element: el, anchor: 'center' })
        .setLngLat([lon, lat])

      markersRef.current.push(marker)
    }

    // Zoom-based visibility + stem animation (same as analyst desk)
    const updateVisibility = () => {
      const zoom = map.getZoom()
      const visible = zoom >= 4
      const close = zoom >= 10
      for (const marker of markersRef.current) {
        if (visible) {
          marker.addTo(map)
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
    updateVisibility()
    map.on('zoom', updateVisibility)
  }, [stations, mapLoaded])

  // Toggle brick kiln layer visibility
  useEffect(() => {
    if (!mapRef.current || !mapLoaded) return
    const map = mapRef.current
    const vis = showKilns ? 'visible' : 'none'
    for (const id of ['brick-kilns-layer', 'brick-kilns-glow', 'brick-kilns-dots']) {
      if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', vis)
    }
  }, [showKilns, mapLoaded])

  // Toggle industry layers visibility
  useEffect(() => {
    if (!mapRef.current || !mapLoaded) return
    const map = mapRef.current
    const vis = showIndustry ? 'visible' : 'none'
    for (const key of ['power_plants', 'cement_plants', 'steel_sites', 'sugar_mills', 'industrial_sites', 'mines_quarries']) {
      const layerId = `industry-${key}-layer`
      if (map.getLayer(layerId)) map.setLayoutProperty(layerId, 'visibility', vis)
    }
  }, [showIndustry, mapLoaded])

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
          3, 0.7,
          7, 0.65,
          9, 0.4,
          12, 0.2,
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
              10, 0.35,
              11, 0.55,
              13, 0.65,
              15, 0.5,
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

      {/* Station hover tooltip */}
      {hoveredStation && (
        <div className="absolute top-6 left-6 z-20 bg-white/95 backdrop-blur-sm rounded-lg shadow-lg border border-slate-200/60 px-3 py-2.5 min-w-[160px]">
          <div className="text-xs font-semibold text-slate-800">{hoveredStation.name}</div>
          <div className="text-[10px] text-slate-500 mt-0.5">{hoveredStation.city}</div>
          <div className="flex items-baseline gap-1 mt-1.5">
            <div className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: BAND_COLORS[pm25ToBand(hoveredStation.pm25)] || '#9ca3af' }} />
            <span className="text-lg font-bold text-slate-900">{hoveredStation.pm25.toFixed(1)}</span>
            <span className="text-xs text-slate-500">µg/m³</span>
          </div>
          <div className="text-[10px] text-slate-400 mt-1">
            Daily Mean (QA){hoveredStation.valid_hours != null ? ` · ${hoveredStation.valid_hours}h` : ''}
          </div>
        </div>
      )}

      {/* Urban grid hover readout */}
      {hoverPM25 && !selectedDistrict && !hoveredStation && (
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
        <div className="absolute top-6 left-6 z-20 bg-white/95 backdrop-blur-sm rounded-xl shadow-2xl border border-slate-200/60 overflow-hidden min-w-[200px]">
          <div className="flex items-center justify-between px-4 py-3 bg-slate-50 border-b border-slate-200">
            <h3 className="text-sm font-bold text-slate-800">{selectedDistrict.name}</h3>
            <button onClick={() => setSelectedDistrict(null)} className="ml-3 text-slate-400 hover:text-slate-600">
              <X size={14} />
            </button>
          </div>
          <div className="px-4 py-3">
            <div className="text-[10px] text-slate-500 uppercase tracking-wide font-medium">PM₂.₅ Prediction</div>
            <div className="flex items-baseline gap-1.5 mt-1">
              <span className="text-3xl font-bold" style={{ color: selectedDistrict.pm25 != null ? BAND_COLORS[pm25ToBand(selectedDistrict.pm25)] : '#94a3b8' }}>
                {selectedDistrict.pm25 !== null ? selectedDistrict.pm25.toFixed(1) : '—'}
              </span>
              <span className="text-sm text-slate-500">μg/m³</span>
            </div>
            {selectedDistrict.stations.length > 0 && (
              <div className="mt-2 pt-2 border-t border-slate-100">
                <div className="text-[10px] text-slate-500 uppercase tracking-wide font-medium mb-1">
                  Observed ({selectedDistrict.stations.length} station{selectedDistrict.stations.length > 1 ? 's' : ''})
                </div>
                {selectedDistrict.stations.map((stn, i) => (
                  <div key={i} className="flex items-center justify-between text-[11px] py-0.5">
                    <span className="text-slate-600 truncate max-w-[120px]">{stn.name}</span>
                    <span className="font-semibold tabular-nums ml-2" style={{ color: BAND_COLORS[pm25ToBand(stn.pm25)] }}>
                      {stn.pm25.toFixed(1)}
                    </span>
                  </div>
                ))}
              </div>
            )}
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
