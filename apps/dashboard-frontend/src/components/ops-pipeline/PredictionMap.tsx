"use client"

import { useRef, useState, useEffect } from 'react'
import { Loader2 } from 'lucide-react'
import { API_BASE, API_TOKEN } from './api'
import { TURBO_GRADIENT } from './utils'

interface PredictionMapProps {
  selectedDate: string
}

interface SelectedDistrict {
  name: string
  pm25: number | null
}

export function PredictionMap({ selectedDate }: PredictionMapProps) {
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

      const map = new maplibregl.default.Map({
        container: mapContainer.current!,
        style: "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
        center: [69.5, 30.5],
        zoom: 5,
        minZoom: 2,
        maxZoom: 12,
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

        // Create mask from ADM1 boundaries (provinces combined)
        const maskGeoJSON = createMaskFromFeatureCollection(adm1GeoJSON)

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

        map.addSource('pakistan-mask', {
          type: 'geojson',
          data: maskGeoJSON
        })

        // Add COG tile source
        const tileUrl = `${API_BASE}/api/v1/ops/pipeline/tiles/${selectedDate}/{z}/{x}/{y}.png`
        map.addSource('pm25-tiles', {
          type: 'raster',
          tiles: [tileUrl],
          tileSize: 256,
          bounds: [60.45, 23.25, 77.95, 37.35],
          minzoom: 0,
          maxzoom: 12,
        })

        // 1. PM2.5 raster layer
        map.addLayer({
          id: 'pm25-raster',
          type: 'raster',
          source: 'pm25-tiles',
          paint: {
            'raster-opacity': 0.85,
            'raster-resampling': 'linear',
          },
        })

        // 2. Mask layer - covers everything outside Pakistan
        map.addLayer({
          id: 'outside-pakistan-mask',
          type: 'fill',
          source: 'pakistan-mask',
          paint: {
            'fill-color': '#f8fafc',
            'fill-opacity': 1
          }
        })

        // 3. District fill layer (transparent, for interaction)
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

        // 6. District borders
        map.addLayer({
          id: 'districts-borders',
          type: 'line',
          source: 'pakistan-districts',
          paint: {
            'line-color': [
              'case',
              ['boolean', ['feature-state', 'selected'], false],
              '#1d4ed8',
              ['boolean', ['feature-state', 'hover'], false],
              '#475569',
              '#94a3b8'
            ],
            'line-width': [
              'case',
              ['boolean', ['feature-state', 'selected'], false],
              2,
              ['boolean', ['feature-state', 'hover'], false],
              1.5,
              0.5
            ],
            'line-opacity': 0.8
          }
        })

        // 7. Province borders (thicker)
        map.addLayer({
          id: 'province-borders',
          type: 'line',
          source: 'pakistan-adm1',
          paint: {
            'line-color': '#334155',
            'line-width': [
              'interpolate', ['linear'], ['zoom'],
              4, 1,
              6, 1.5,
              8, 2
            ],
            'line-opacity': 0.9
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
            const res = await fetch(
              `${API_BASE}/api/v1/ops/pipeline/tiles/${selectedDate}/point?lat=${centroid[1]}&lon=${centroid[0]}`,
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

  // Update tile source when date changes
  useEffect(() => {
    if (!mapRef.current || !mapLoaded) return

    const map = mapRef.current
    const src = map.getSource('pm25-tiles')
    if (src) {
      const tileUrl = `${API_BASE}/api/v1/ops/pipeline/tiles/${selectedDate}/{z}/{x}/{y}.png`
      src.setTiles([tileUrl])
    }

    // Clear selection when date changes
    setSelectedDistrict(null)
  }, [selectedDate, mapLoaded])

  return (
    <div className="relative w-full h-full">
      <div ref={mapContainer} className="w-full h-full" />

      {/* Selected district info panel */}
      {selectedDistrict && (
        <div className="absolute top-3 left-3 bg-white rounded-lg shadow-lg border border-slate-200 p-4 min-w-[200px]">
          <div className="text-sm font-semibold text-slate-800 mb-1">
            {selectedDistrict.name}
          </div>
          <div className="text-2xl font-bold text-slate-900">
            {selectedDistrict.pm25 !== null ? (
              <>
                {selectedDistrict.pm25.toFixed(1)}
                <span className="text-sm font-medium text-slate-500 ml-1">μg/m³</span>
              </>
            ) : (
              <span className="text-sm text-slate-400">No data</span>
            )}
          </div>
          <div className="text-xs text-slate-500 mt-1">PM2.5 Concentration</div>
        </div>
      )}

      {/* Hover tooltip */}
      {hoveredDistrict && !selectedDistrict && (
        <div className="absolute top-3 left-3 bg-white/95 backdrop-blur-sm rounded-lg shadow-md border border-slate-200 px-3 py-2">
          <span className="text-sm font-medium text-slate-700">{hoveredDistrict}</span>
        </div>
      )}

      {/* Bottom legend bar */}
      {mapLoaded && (
        <div className="absolute bottom-0 left-0 right-0 bg-white/90 px-4 py-2">
          <div className="flex items-center gap-3">
            <span className="text-[11px] font-medium text-slate-600 whitespace-nowrap">PM2.5 (μg/m³)</span>
            <div className="flex-1 flex items-center gap-1">
              <span className="text-[10px] text-slate-500">20</span>
              <div className="flex-1 h-2 rounded-sm" style={{ background: TURBO_GRADIENT }} />
              <span className="text-[10px] text-slate-500">180</span>
            </div>
          </div>
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

// Create inverse mask from FeatureCollection (all provinces combined)
function createMaskFromFeatureCollection(featureCollection: any): any {
  const worldOuter = [
    [-180, -90],
    [180, -90],
    [180, 90],
    [-180, 90],
    [-180, -90]
  ]

  let holes: number[][][] = []
  const features = featureCollection.features || [featureCollection]

  for (const feature of features) {
    const geom = feature.geometry
    if (geom.type === 'Polygon') {
      holes.push(geom.coordinates[0])
    } else if (geom.type === 'MultiPolygon') {
      for (const poly of geom.coordinates) {
        holes.push(poly[0])
      }
    }
  }

  return {
    type: 'Feature',
    properties: {},
    geometry: {
      type: 'Polygon',
      coordinates: [worldOuter, ...holes]
    }
  }
}
