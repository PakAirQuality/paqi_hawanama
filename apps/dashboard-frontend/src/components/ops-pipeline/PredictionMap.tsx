"use client"

import { useRef, useState, useEffect } from 'react'
import { Loader2 } from 'lucide-react'
import { API_BASE, API_TOKEN } from './api'

const MAPBOX_TOKEN = '***REMOVED***'
const INITIAL_CENTER: [number, number] = [69.3459, 30.3]
const INITIAL_ZOOM = 3.5

interface PredictionMapProps {
  selectedDate: string
  smoothed?: boolean
}

interface SelectedDistrict {
  name: string
  pm25: number | null
}

export function PredictionMap({ selectedDate, smoothed = false }: PredictionMapProps) {
  const mapContainer = useRef<HTMLDivElement>(null)
  const mapRef = useRef<any>(null)
  const [mapLoaded, setMapLoaded] = useState(false)
  const [hoveredDistrict, setHoveredDistrict] = useState<string | null>(null)
  const [selectedDistrict, setSelectedDistrict] = useState<SelectedDistrict | null>(null)

  // Initialize map once
  useEffect(() => {
    if (!mapContainer.current) return

    import('maplibre-gl').then((maplibregl) => {
      import('maplibre-gl/dist/maplibre-gl.css')

      if (mapRef.current) return

      // Mapbox light style (same as main dashboard)
      const mapStyle = {
        version: 8 as const,
        sources: {
          'mapbox-streets': {
            type: 'raster' as const,
            tiles: [
              `https://api.mapbox.com/styles/v1/mapbox/light-v11/tiles/{z}/{x}/{y}?access_token=${MAPBOX_TOKEN}`
            ],
            tileSize: 512,
            attribution: '© Mapbox © OpenStreetMap'
          }
        },
        layers: [
          {
            id: 'mapbox-tiles',
            type: 'raster' as const,
            source: 'mapbox-streets',
            minzoom: 0,
            maxzoom: 22
          }
        ]
      }

      const map = new maplibregl.default.Map({
        container: mapContainer.current!,
        style: mapStyle,
        center: INITIAL_CENTER,
        zoom: INITIAL_ZOOM,
        minZoom: 2,
        maxZoom: 10,
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

        // Add COG tile source
        const smoothParam = smoothed ? '?smoothed=true' : ''
        const tileUrl = `${API_BASE}/api/v1/ops/pipeline/tiles/${selectedDate}/{z}/{x}/{y}.png${smoothParam}`
        map.addSource('pm25-tiles', {
          type: 'raster',
          tiles: [tileUrl],
          tileSize: 256,
          bounds: [60.45, 23.25, 77.95, 37.35],
          minzoom: 0,
          maxzoom: 12,
        })

        // 1. PM2.5 raster layer (server-side clipped to Pakistan boundary)
        map.addLayer({
          id: 'pm25-raster',
          type: 'raster',
          source: 'pm25-tiles',
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

        // 4. District hover highlight
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

        // 5. District selection highlight
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

        // 6. District borders - subtle
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

        // 7. Province borders - subtle
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

        // Track hovered feature
        let hoveredId: string | null = null

        // Hover handlers
        map.on('mousemove', 'districts-fill', (e: any) => {
          if (e.features && e.features.length > 0) {
            const feature = e.features[0]
            const newId = feature.properties.shapeName

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

        // Click handler - select district and fetch PM2.5
        let selectedId: string | null = null

        map.on('click', 'districts-fill', async (e: any) => {
          if (!e.features || e.features.length === 0) return

          const feature = e.features[0]
          const districtName = feature.properties.shapeName
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

          if (feature.geometry.type === 'Polygon') {
            centroid = getCentroid(feature.geometry.coordinates[0])
          } else if (feature.geometry.type === 'MultiPolygon') {
            const largest = feature.geometry.coordinates.reduce((a: any, b: any) =>
              a[0].length > b[0].length ? a : b
            )
            centroid = getCentroid(largest[0])
          } else {
            centroid = [e.lngLat.lng, e.lngLat.lat]
          }

          // Fetch PM2.5 value
          try {
            const smoothParam = smoothed ? '&smoothed=true' : ''
            const res = await fetch(
              `${API_BASE}/api/v1/ops/pipeline/tiles/${selectedDate}/point?lat=${centroid[1]}&lon=${centroid[0]}${smoothParam}`,
              { headers: { Authorization: `Bearer ${API_TOKEN}` } }
            )
            if (res.ok) {
              const data = await res.json()
              setSelectedDistrict({
                name: districtName,
                pm25: data.pm25
              })
            } else {
              setSelectedDistrict({
                name: districtName,
                pm25: null
              })
            }
          } catch (err) {
            console.error('Point query failed:', err)
            setSelectedDistrict({
              name: districtName,
              pm25: null
            })
          }
        })

        // Click outside to deselect
        map.on('click', (e: any) => {
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
    })

    return () => {
      if (mapRef.current) {
        mapRef.current.remove()
        mapRef.current = null
      }
    }
  }, [])

  // Update tile source when date or smoothed changes
  useEffect(() => {
    if (!mapRef.current || !mapLoaded) return

    const map = mapRef.current
    const src = map.getSource('pm25-tiles')
    if (src) {
      const smoothParam = smoothed ? '?smoothed=true' : ''
      const tileUrl = `${API_BASE}/api/v1/ops/pipeline/tiles/${selectedDate}/{z}/{x}/{y}.png${smoothParam}`
      src.setTiles([tileUrl])
    }

    // Clear selection when date changes
    setSelectedDistrict(null)
  }, [selectedDate, smoothed, mapLoaded])

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

