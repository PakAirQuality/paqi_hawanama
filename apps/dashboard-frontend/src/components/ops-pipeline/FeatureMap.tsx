"use client"

import { useRef, useState, useEffect } from 'react'
import { Loader2 } from 'lucide-react'
import mapboxgl from 'mapbox-gl'
import 'mapbox-gl/dist/mapbox-gl.css'
import { API_BASE, API_TOKEN } from './api'
import type { FeatureInfo } from './types'

mapboxgl.accessToken = process.env.NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN || ''

const STYLE_URL = 'mapbox://styles/rehan0900/cmmh9p69z009m01qu0nnn3iwu'
const INITIAL_CENTER: [number, number] = [69.3459, 30.3]
const INITIAL_ZOOM = 3.5

interface FeatureMapProps {
  selectedDate: string
  feature: FeatureInfo
}

interface SelectedDistrict {
  name: string
  value: number | null
}

export function FeatureMap({ selectedDate, feature }: FeatureMapProps) {
  const mapContainer = useRef<HTMLDivElement>(null)
  const mapRef = useRef<mapboxgl.Map | null>(null)
  const [mapLoaded, setMapLoaded] = useState(false)
  const [hoveredDistrict, setHoveredDistrict] = useState<string | null>(null)
  const [selectedDistrict, setSelectedDistrict] = useState<SelectedDistrict | null>(null)

  // Initialize map once
  useEffect(() => {
    if (!mapContainer.current || mapRef.current) return

    const map = new mapboxgl.Map({
      container: mapContainer.current,
      style: STYLE_URL,
      center: INITIAL_CENTER,
      zoom: INITIAL_ZOOM,
      minZoom: 2,
      maxZoom: 10,
      attributionControl: false,
      transformRequest: (url: string) => {
        if (url.includes('/ops/pipeline/tiles/')) {
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
      // Load district boundaries (ADM2)
      const districtsResponse = await fetch('/pakistan_districts.geojson')
      const districtsGeoJSON = await districtsResponse.json()

      // Load province boundaries (ADM1)
      const adm1Response = await fetch('/pakistan_adm1.geojson')
      const adm1GeoJSON = await adm1Response.json()

      // Load dissolved ADM2 boundary (same geometry used for raster clipping)
      const dissolvedResponse = await fetch('/pakistan_adm2_dissolved.geojson')
      const dissolvedGeoJSON = await dissolvedResponse.json()

      // Add sources
      map.addSource('pakistan-districts', {
        type: 'geojson',
        data: districtsGeoJSON,
        promoteId: 'shapeName'
      })

      map.addSource('pakistan-adm1', {
        type: 'geojson',
        data: adm1GeoJSON
      })

      map.addSource('pakistan-boundary', {
        type: 'geojson',
        data: dissolvedGeoJSON
      })

      // Feature tile source
      const tileUrl = `${API_BASE}/api/v1/ops/pipeline/tiles/features/${feature.name}/${selectedDate}/{z}/{x}/{y}.png`
      map.addSource('feature-tiles', {
        type: 'raster',
        tiles: [tileUrl],
        tileSize: 256,
        bounds: [60.45, 23.25, 77.95, 37.35],
        minzoom: 0,
        maxzoom: 12,
      })

      // 1. Feature raster layer — 'middle' slot places it below basemap labels
      map.addLayer({
        id: 'feature-raster',
        type: 'raster',
        source: 'feature-tiles',
        slot: 'middle',
        paint: {
          'raster-opacity': 0.85,
          'raster-resampling': 'linear',
        },
      })

      // 2. District fill layer (transparent, for interaction)
      map.addLayer({
        id: 'districts-fill',
        type: 'fill',
        source: 'pakistan-districts',
        paint: {
          'fill-color': 'transparent',
          'fill-opacity': 0
        }
      })

      // 3. District hover highlight
      map.addLayer({
        id: 'districts-hover',
        type: 'fill',
        source: 'pakistan-districts',
        paint: {
          'fill-color': '#ffffff',
          'fill-opacity': [
            'case',
            ['boolean', ['feature-state', 'hover'], false],
            0.3,
            0
          ]
        }
      })

      // 4. District selection highlight
      map.addLayer({
        id: 'districts-selected',
        type: 'fill',
        source: 'pakistan-districts',
        paint: {
          'fill-color': '#3b82f6',
          'fill-opacity': [
            'case',
            ['boolean', ['feature-state', 'selected'], false],
            0.4,
            0
          ]
        }
      })

      // 5. District borders - subtle
      map.addLayer({
        id: 'districts-borders',
        type: 'line',
        source: 'pakistan-districts',
        paint: {
          'line-color': [
            'case',
            ['boolean', ['feature-state', 'selected'], false],
            '#475569',
            ['boolean', ['feature-state', 'hover'], false],
            '#64748b',
            '#94a3b8'
          ],
          'line-width': [
            'case',
            ['boolean', ['feature-state', 'selected'], false],
            1.5,
            ['boolean', ['feature-state', 'hover'], false],
            1,
            0.3
          ],
          'line-opacity': 0.5
        }
      })

      // 6. Province borders - subtle
      map.addLayer({
        id: 'province-borders',
        type: 'line',
        source: 'pakistan-adm1',
        paint: {
          'line-color': '#94a3b8',
          'line-width': 1,
          'line-opacity': 0.7
        }
      })

      // 7. Country outline — matches the exact geometry used for raster clipping
      map.addLayer({
        id: 'country-outline',
        type: 'line',
        source: 'pakistan-boundary',
        paint: {
          'line-color': '#64748b',
          'line-width': 1.5,
          'line-opacity': 0.9
        }
      })

      // Track hovered feature
      let hoveredId: string | null = null

      // Hover handlers
      map.on('mousemove', 'districts-fill', (e) => {
        if (e.features && e.features.length > 0) {
          const feat = e.features[0]
          const newId = feat.properties?.shapeName

          if (hoveredId !== newId) {
            if (hoveredId) {
              map.setFeatureState(
                { source: 'pakistan-districts', id: hoveredId },
                { hover: false }
              )
            }
            hoveredId = newId
            map.setFeatureState(
              { source: 'pakistan-districts', id: newId },
              { hover: true }
            )
            setHoveredDistrict(newId)
          }
          map.getCanvas().style.cursor = 'pointer'
        }
      })

      map.on('mouseleave', 'districts-fill', () => {
        if (hoveredId) {
          map.setFeatureState(
            { source: 'pakistan-districts', id: hoveredId },
            { hover: false }
          )
          hoveredId = null
        }
        setHoveredDistrict(null)
        map.getCanvas().style.cursor = ''
      })

      // Click handler - select district and fetch value
      let selectedId: string | null = null

      map.on('click', 'districts-fill', async (e) => {
        if (!e.features || e.features.length === 0) return

        const feat = e.features[0]
        const districtName = feat.properties?.shapeName
        const newId = districtName

        // Reset previous selection
        if (selectedId) {
          map.setFeatureState(
            { source: 'pakistan-districts', id: selectedId },
            { selected: false }
          )
        }

        // Set new selection
        selectedId = newId
        map.setFeatureState(
          { source: 'pakistan-districts', id: newId },
          { selected: true }
        )

        // Get centroid for point query
        let centroid: [number, number]

        if (feat.geometry.type === 'Polygon') {
          centroid = getCentroid((feat.geometry as any).coordinates[0])
        } else if (feat.geometry.type === 'MultiPolygon') {
          const largest = (feat.geometry as any).coordinates.reduce((a: any, b: any) =>
            a[0].length > b[0].length ? a : b
          )
          centroid = getCentroid(largest[0])
        } else {
          centroid = [e.lngLat.lng, e.lngLat.lat]
        }

        // Fetch feature value
        try {
          const res = await fetch(
            `${API_BASE}/api/v1/ops/pipeline/tiles/features/${feature.name}/${selectedDate}/point?lat=${centroid[1]}&lon=${centroid[0]}`,
            { headers: { Authorization: `Bearer ${API_TOKEN}` } }
          )
          if (res.ok) {
            const data = await res.json()
            setSelectedDistrict({
              name: districtName,
              value: data.value
            })
          } else {
            setSelectedDistrict({
              name: districtName,
              value: null
            })
          }
        } catch (err) {
          console.error('Point query failed:', err)
          setSelectedDistrict({
            name: districtName,
            value: null
          })
        }
      })

      // Click outside to deselect
      map.on('click', (e) => {
        const features = map.queryRenderedFeatures(e.point, { layers: ['districts-fill'] })
        if (features.length === 0 && selectedId) {
          map.setFeatureState(
            { source: 'pakistan-districts', id: selectedId },
            { selected: false }
          )
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

  // Update tile source when date or feature changes
  useEffect(() => {
    if (!mapRef.current || !mapLoaded) return

    const map = mapRef.current
    const tileUrl = `${API_BASE}/api/v1/ops/pipeline/tiles/features/${feature.name}/${selectedDate}/{z}/{x}/{y}.png`

    // Remove old and re-add with new URL
    if (map.getLayer('feature-raster')) map.removeLayer('feature-raster')
    if (map.getSource('feature-tiles')) map.removeSource('feature-tiles')

    map.addSource('feature-tiles', {
      type: 'raster',
      tiles: [tileUrl],
      tileSize: 256,
      bounds: [60.45, 23.25, 77.95, 37.35],
      minzoom: 0,
      maxzoom: 12,
    })

    map.addLayer({
      id: 'feature-raster',
      type: 'raster',
      source: 'feature-tiles',
      slot: 'middle',
      paint: {
        'raster-opacity': 0.85,
        'raster-resampling': 'linear',
      },
    })

    // Clear selection when date/feature changes
    setSelectedDistrict(null)
  }, [selectedDate, feature.name, mapLoaded])

  return (
    <div className="relative w-full h-full">
      <div ref={mapContainer} className="w-full h-full" />

      {/* Selected district info panel */}
      {selectedDistrict && (
        <div className="absolute top-6 left-6 bg-white/95 backdrop-blur-sm rounded-xl shadow-2xl border border-slate-200/60 overflow-hidden min-w-[200px]">
          <div className="px-4 py-3 bg-slate-50 border-b border-slate-200">
            <h3 className="text-lg font-bold text-slate-800">{selectedDistrict.name}</h3>
          </div>
          <div className="px-4 py-4">
            <div className="text-xs text-slate-500 uppercase tracking-wide font-medium">{feature.name}</div>
            <div className="flex items-baseline gap-1.5 mt-1">
              <span className="text-3xl font-bold text-slate-900">
                {selectedDistrict.value !== null
                  ? (typeof selectedDistrict.value === 'number' ? selectedDistrict.value.toPrecision(4) : selectedDistrict.value)
                  : '—'}
              </span>
              <span className="text-sm text-slate-500">{feature.unit}</span>
            </div>
          </div>
        </div>
      )}

      {/* Hover tooltip */}
      {hoveredDistrict && !selectedDistrict && (
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

// Calculate centroid of a polygon ring
function getCentroid(ring: number[][]): [number, number] {
  let x = 0, y = 0
  for (const coord of ring) {
    x += coord[0]
    y += coord[1]
  }
  return [x / ring.length, y / ring.length]
}
