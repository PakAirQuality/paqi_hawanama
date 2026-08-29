'use client'

import React, { useEffect, useRef, useState } from 'react'
import mapboxgl from 'mapbox-gl'
import 'mapbox-gl/dist/mapbox-gl.css'

interface StationReading {
  id: string
  name: string
  latitude: number
  longitude: number
  city: string | null
  pm25: number | null
  aqi_raw: number | null
  aqi_category: string | null
}

interface Props {}

mapboxgl.accessToken = process.env.NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN || ''

const INITIAL_CENTER: [number, number] = [69.3459, 30.3]
const INITIAL_ZOOM = 4.2

// AQI color class (matching public app exactly)
const getAQIColorClass = (aqi: number | null): string => {
  if (aqi == null || aqi <= 0) return 'bg-no-reading'
  if (aqi <= 50) return 'bg-good'
  if (aqi <= 100) return 'bg-moderate'
  if (aqi <= 150) return 'bg-unhealthy-sensitive'
  if (aqi <= 200) return 'bg-unhealthy'
  if (aqi <= 300) return 'bg-very-unhealthy'
  return 'bg-hazardous'
}

// Inline color for popup dot only
const getAQIBgColor = (aqi: number | null): string => {
  if (aqi == null || aqi <= 0) return '#ccc'
  if (aqi <= 50) return 'rgba(110,204,57,1)'
  if (aqi <= 100) return 'rgba(240,194,12,1)'
  if (aqi <= 150) return 'rgba(241,128,23,1)'
  if (aqi <= 200) return 'rgba(239,120,85,1)'
  if (aqi <= 300) return '#a070b5'
  return '#991b1b'
}

const getAQIStatus = (aqi: number | null): string => {
  if (aqi == null) return 'No Data'
  if (aqi <= 50) return 'Good'
  if (aqi <= 100) return 'Moderate'
  if (aqi <= 150) return 'Unhealthy for Sensitive'
  if (aqi <= 200) return 'Unhealthy'
  if (aqi <= 300) return 'Very Unhealthy'
  return 'Hazardous'
}

const API_BASE = 'https://hawanama-152782825429.asia-south1.run.app'

// ── Point-in-polygon (ray casting) for Pakistan boundary filtering ──

type Ring = [number, number][]  // [lng, lat][]

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

function pointInMultiPolygon(lng: number, lat: number, multiPoly: Ring[][][]): boolean {
  for (const polygon of multiPoly) {
    // polygon[0] is outer ring, polygon[1..] are holes
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

/** Create a DOM element for a station marker (matching public app exactly). */
function createMarkerEl(station: StationReading): HTMLDivElement {
  const colorClass = getAQIColorClass(station.aqi_raw)
  const pm25 = station.pm25 != null ? Math.round(station.pm25) : '-'

  const container = document.createElement('div')
  container.className = 'aqi-marker-container point'
  container.style.width = '28px'
  container.style.height = '28px'

  const marker = document.createElement('div')
  marker.className = `aqi-marker ${colorClass}`
  marker.textContent = String(pm25)

  container.appendChild(marker)
  return container
}

export const InteractiveRegionalMap: React.FC<Props> = () => {
  const mapContainer = useRef<HTMLDivElement>(null)
  const map = useRef<mapboxgl.Map | null>(null)
  const markersRef = useRef<mapboxgl.Marker[]>([])
  const popupRef = useRef<mapboxgl.Popup | null>(null)
  const [stations, setStations] = useState<StationReading[]>([])
  const [pakGeom, setPakGeom] = useState<Ring[][][] | null>(null)
  const [loading, setLoading] = useState(true)

  // Fetch station data + Pakistan boundary in parallel
  useEffect(() => {
    const fetchData = async () => {
      setLoading(true)
      try {
        const [stationsRes, boundaryRes] = await Promise.all([
          fetch(`${API_BASE}/api/v1/stations`),
          fetch('/pakistan_country.geojson'),
        ])
        if (!stationsRes.ok) throw new Error('Failed to fetch stations')
        const stationsData = await stationsRes.json()
        setStations(stationsData.stations ?? [])

        if (boundaryRes.ok) {
          const gj = await boundaryRes.json()
          const geom = gj.features?.[0]?.geometry
          if (geom?.type === 'MultiPolygon') {
            setPakGeom(geom.coordinates)
          } else if (geom?.type === 'Polygon') {
            setPakGeom([geom.coordinates])
          }
        }
      } catch (error) {
        console.error('Error fetching data:', error)
      } finally {
        setLoading(false)
      }
    }
    fetchData()
  }, [])

  // Initialize map once stations + boundary are loaded
  useEffect(() => {
    if (!mapContainer.current || map.current || loading || stations.length === 0 || !pakGeom) return

    // Filter to stations inside Pakistan boundary with valid PM2.5
    const validStations = stations.filter(s =>
      s.latitude && s.longitude && s.pm25 != null &&
      pointInMultiPolygon(s.longitude, s.latitude, pakGeom)
    )

    map.current = new mapboxgl.Map({
      container: mapContainer.current,
      style: 'mapbox://styles/rehan0900/cmmh9p69z009m01qu0nnn3iwu',
      center: INITIAL_CENTER,
      zoom: INITIAL_ZOOM,
      maxZoom: 14,
      minZoom: 2,
      projection: 'globe',
    })

    map.current.on('load', () => {
      if (!map.current) return

      // Satellite PM2.5 background — annual mean (2022 baseline)
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
        paint: {
          'raster-opacity': 0.75,
        },
        slot: 'middle',
      })

      // ── District boundaries (ADM2) — clickable ──
      map.current.addSource('pakistan-districts', {
        type: 'geojson',
        data: '/pakistan_districts.geojson',
        promoteId: 'shapeName',
      })

      // Invisible fill for click/hover interaction
      map.current.addLayer({
        id: 'districts-fill',
        type: 'fill',
        source: 'pakistan-districts',
        paint: {
          'fill-color': 'transparent',
          'fill-opacity': 0,
        },
      })

      // Hover highlight
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

      // District border lines
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

      // Province boundaries (ADM1)
      map.current.addSource('pakistan-provinces', {
        type: 'geojson',
        data: '/pakistan_adm1.geojson',
      })

      map.current.addLayer({
        id: 'provinces-line',
        type: 'line',
        source: 'pakistan-provinces',
        paint: {
          'line-color': '#94a3b8',
          'line-width': 1,
          'line-opacity': 0.7,
        },
      })

      // Country outline
      map.current.addSource('pakistan-boundary', {
        type: 'geojson',
        data: '/pakistan_country.geojson',
      })

      map.current.addLayer({
        id: 'country-outline',
        type: 'line',
        source: 'pakistan-boundary',
        paint: {
          'line-color': '#64748b',
          'line-width': 1.5,
          'line-opacity': 0.9,
        },
      })

      // ── District hover tracking ──
      let hoveredDistrictId: string | null = null

      map.current.on('mousemove', 'districts-fill', (e) => {
        if (!map.current || !e.features || !e.features[0]) return
        map.current.getCanvas().style.cursor = 'pointer'

        const id = e.features[0].id as string
        if (hoveredDistrictId && hoveredDistrictId !== id) {
          map.current.setFeatureState(
            { source: 'pakistan-districts', id: hoveredDistrictId },
            { hover: false }
          )
        }
        hoveredDistrictId = id
        map.current.setFeatureState(
          { source: 'pakistan-districts', id },
          { hover: true }
        )
      })

      map.current.on('mouseleave', 'districts-fill', () => {
        if (!map.current) return
        map.current.getCanvas().style.cursor = ''
        if (hoveredDistrictId) {
          map.current.setFeatureState(
            { source: 'pakistan-districts', id: hoveredDistrictId },
            { hover: false }
          )
          hoveredDistrictId = null
        }
      })

      // ── District click → zoom to bounds ──
      map.current.on('click', 'districts-fill', (e) => {
        if (!map.current || !e.features || !e.features[0]) return
        const feature = e.features[0]
        const geom = feature.geometry as GeoJSON.Polygon | GeoJSON.MultiPolygon

        // Compute bounding box of the clicked district
        const coords: [number, number][] = []
        if (geom.type === 'Polygon') {
          geom.coordinates[0].forEach(c => coords.push(c as [number, number]))
        } else {
          geom.coordinates.forEach(poly =>
            poly[0].forEach(c => coords.push(c as [number, number]))
          )
        }

        const bounds = coords.reduce(
          (b, [lng, lat]) => {
            b[0] = Math.min(b[0], lng)
            b[1] = Math.min(b[1], lat)
            b[2] = Math.max(b[2], lng)
            b[3] = Math.max(b[3], lat)
            return b
          },
          [Infinity, Infinity, -Infinity, -Infinity]
        )

        map.current.fitBounds(
          [[bounds[0], bounds[1]], [bounds[2], bounds[3]]],
          { padding: 100, maxZoom: 7.5, duration: 600 }
        )
      })

      // ── Station markers (DOM-based, hidden until zoom ≥ 7) ──
      const MARKER_MIN_ZOOM = 7

      for (const station of validStations) {
        const el = createMarkerEl(station)

        const dotColor = getAQIBgColor(station.aqi_raw)
        const pm25Str = station.pm25 != null ? Number(station.pm25).toFixed(1) : '—'
        const aqiStr = station.aqi_raw != null ? station.aqi_raw : '—'
        const status = getAQIStatus(station.aqi_raw)

        const popup = new mapboxgl.Popup({
          closeButton: false,
          closeOnClick: false,
          offset: 16,
          maxWidth: '240px',
        }).setHTML(`
          <div style="font-family: system-ui, sans-serif; min-width: 160px;">
            <div style="font-weight: 600; font-size: 14px; color: #1e293b; margin-bottom: 4px;">${station.name}</div>
            ${station.city ? `<div style="font-size: 11px; color: #64748b; margin-bottom: 8px;">${station.city}</div>` : ''}
            <div style="display: flex; align-items: center; gap: 6px; margin-bottom: 4px;">
              <span style="width: 8px; height: 8px; border-radius: 50%; background: ${dotColor}; display: inline-block;"></span>
              <span style="font-size: 11px; color: #64748b;">${status}</span>
            </div>
            <div style="display: flex; gap: 16px; margin-top: 6px;">
              <div>
                <div style="font-size: 10px; color: #94a3b8; text-transform: uppercase;">PM2.5</div>
                <div style="font-size: 18px; font-weight: 700; color: #0f172a;">${pm25Str}</div>
              </div>
              <div>
                <div style="font-size: 10px; color: #94a3b8; text-transform: uppercase;">AQI</div>
                <div style="font-size: 18px; font-weight: 700; color: #0f172a;">${aqiStr}</div>
              </div>
            </div>
          </div>
        `)

        const marker = new mapboxgl.Marker({ element: el })
          .setLngLat([station.longitude, station.latitude])
          .setPopup(popup)

        // Show popup on hover
        el.addEventListener('mouseenter', () => { marker.togglePopup() })
        el.addEventListener('mouseleave', () => { marker.togglePopup() })

        markersRef.current.push(marker)
      }

      // ── Show/hide markers based on zoom ──
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

      // Initial state + listen to zoom changes
      updateMarkerVisibility()
      map.current.on('zoom', updateMarkerVisibility)
    })

    return () => {
      markersRef.current.forEach(m => m.remove())
      markersRef.current = []
      if (popupRef.current) {
        popupRef.current.remove()
        popupRef.current = null
      }
      if (map.current) {
        map.current.remove()
        map.current = null
      }
    }
  }, [stations, loading, pakGeom])

  return (
    <div className="relative w-full h-[calc(100vh-108px)] min-h-[500px]">
      {loading ? (
        <div className="absolute inset-0 flex items-center justify-center bg-slate-100">
          <div className="text-slate-500 text-sm">Loading...</div>
        </div>
      ) : (
        <div ref={mapContainer} className="w-full h-full" />
      )}
    </div>
  )
}
