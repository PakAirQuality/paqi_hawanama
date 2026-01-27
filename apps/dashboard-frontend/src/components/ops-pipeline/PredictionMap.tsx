"use client"

import { useRef, useState, useEffect } from 'react'
import { Loader2 } from 'lucide-react'
import { API_BASE, API_TOKEN } from './api'

interface PredictionMapProps {
  selectedDate: string
}

export function PredictionMap({ selectedDate }: PredictionMapProps) {
  const mapContainer = useRef<HTMLDivElement>(null)
  const mapRef = useRef<any>(null)
  const [mapLoaded, setMapLoaded] = useState(false)
  const [showPredictions, setShowPredictions] = useState(true)
  const [opacity, setOpacity] = useState(0.8)
  const [hoveredValue, setHoveredValue] = useState<number | null>(null)

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
        zoom: 4.8,
        minZoom: 3,
        maxZoom: 10,
        transformRequest: (url: string) => {
          // Add auth header for tile requests
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
        // Load Pakistan ADM1 boundaries (provinces) - same as used for inference
        const adm1Response = await fetch('/pakistan_adm1.geojson')
        const adm1GeoJSON = await adm1Response.json()

        // Add Pakistan ADM1 source (provinces)
        map.addSource('pakistan-adm1', {
          type: 'geojson',
          data: adm1GeoJSON
        })

        // Create mask from ADM1 boundaries (all provinces combined)
        const maskGeoJSON = createMaskFromFeatureCollection(adm1GeoJSON)
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
            'raster-opacity': 0.8,
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

        // 3. Pakistan province borders (ADM1)
        map.addLayer({
          id: 'pakistan-borders',
          type: 'line',
          source: 'pakistan-adm1',
          paint: {
            'line-color': '#64748b',
            'line-width': [
              'interpolate', ['linear'], ['zoom'],
              4, 0.5,
              6, 0.8,
              8, 1.2
            ],
            'line-opacity': 0.7
          }
        })

        // 4. Pakistan country outline (thicker, from combined ADM1)
        map.addLayer({
          id: 'pakistan-outer-border',
          type: 'line',
          source: 'pakistan-adm1',
          paint: {
            'line-color': '#334155',
            'line-width': [
              'interpolate', ['linear'], ['zoom'],
              4, 1.5,
              6, 2,
              8, 2.5
            ],
            'line-opacity': 0.9
          }
        })

        // Fit to Pakistan bounds
        map.fitBounds([[60.5, 23.5], [77.5, 37]], {
          padding: { top: 20, bottom: 20, left: 20, right: 20 },
          duration: 0
        })

        // Click handler - query point value from API
        map.on('click', async (e: any) => {
          const { lng, lat } = e.lngLat

          // Check if inside Pakistan bounds roughly
          if (lng < 60 || lng > 78 || lat < 23 || lat > 38) return

          try {
            const res = await fetch(
              `${API_BASE}/api/v1/ops/pipeline/tiles/${selectedDate}/point?lat=${lat}&lon=${lng}`,
              { headers: { Authorization: `Bearer ${API_TOKEN}` } }
            )
            if (!res.ok) return

            const data = await res.json()
            if (data.pm25 === null) return

            new maplibregl.default.Popup({
              closeButton: true,
              closeOnClick: true,
              className: 'pm25-popup'
            })
              .setLngLat(e.lngLat)
              .setHTML(`
                <div style="padding: 8px 12px; font-family: system-ui, sans-serif;">
                  <div style="font-size: 12px; color: #64748b; margin-bottom: 2px;">PM2.5 Concentration</div>
                  <div style="font-size: 18px; font-weight: 700; color: #1e293b;">${data.pm25.toFixed(1)} <span style="font-size: 12px; font-weight: 500;">ug/m3</span></div>
                </div>
              `)
              .addTo(map)
          } catch (err) {
            console.error('Point query failed:', err)
          }
        })

        // Cursor change on hover
        map.on('mousemove', (e: any) => {
          const { lng, lat } = e.lngLat
          const insideBounds = lng >= 60 && lng <= 78 && lat >= 23 && lat <= 38
          map.getCanvas().style.cursor = insideBounds ? 'pointer' : ''
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
      // Update tile URL for new date
      const tileUrl = `${API_BASE}/api/v1/ops/pipeline/tiles/${selectedDate}/{z}/{x}/{y}.png`
      src.setTiles([tileUrl])
    }
  }, [selectedDate, mapLoaded])

  // Toggle prediction layer visibility
  useEffect(() => {
    if (!mapRef.current || !mapLoaded) return
    const map = mapRef.current
    map.setLayoutProperty('pm25-raster', 'visibility', showPredictions ? 'visible' : 'none')
  }, [showPredictions, mapLoaded])

  // Update opacity
  useEffect(() => {
    if (!mapRef.current || !mapLoaded) return
    const map = mapRef.current
    map.setPaintProperty('pm25-raster', 'raster-opacity', opacity)
  }, [opacity, mapLoaded])

  return (
    <div className="relative w-full h-full">
      <div ref={mapContainer} className="w-full h-full rounded-xl" />

      {/* Layer Controls */}
      {mapLoaded && (
        <div className="absolute top-3 right-3 bg-white/95 backdrop-blur-sm rounded-lg shadow-lg border border-slate-200 p-3 space-y-3">
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="show-predictions"
              checked={showPredictions}
              onChange={(e) => setShowPredictions(e.target.checked)}
              className="w-4 h-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
            />
            <label htmlFor="show-predictions" className="text-sm font-medium text-slate-700">
              Show PM2.5
            </label>
          </div>

          {showPredictions && (
            <div className="space-y-1">
              <label className="text-xs text-slate-500">Opacity</label>
              <input
                type="range"
                min="0.1"
                max="1"
                step="0.1"
                value={opacity}
                onChange={(e) => setOpacity(parseFloat(e.target.value))}
                className="w-full h-1.5 bg-slate-200 rounded-lg appearance-none cursor-pointer"
              />
            </div>
          )}

          {/* Color scale legend */}
          <div className="pt-2 border-t border-slate-100">
            <div className="text-xs text-slate-500 mb-1">PM2.5 (ug/m3)</div>
            <div className="h-2 rounded" style={{
              background: 'linear-gradient(to right, #30123b, #4662d7, #36aaf9, #1be5b5, #afea3b, #fbc424, #e45a31, #7a0403)'
            }}></div>
            <div className="flex justify-between text-[10px] text-slate-400 mt-0.5">
              <span>20</span>
              <span>180</span>
            </div>
          </div>
        </div>
      )}

      {!mapLoaded && (
        <div className="absolute inset-0 flex items-center justify-center bg-slate-100 rounded-xl">
          <Loader2 className="w-8 h-8 animate-spin text-blue-500" />
        </div>
      )}
    </div>
  )
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

  // Collect all polygon rings from all features
  let holes: number[][][] = []

  const features = featureCollection.features || [featureCollection]

  for (const feature of features) {
    const geom = feature.geometry
    if (geom.type === 'Polygon') {
      // For Polygon, coordinates is [outer, ...holes]
      // We only want the outer ring as our hole
      holes.push(geom.coordinates[0])
    } else if (geom.type === 'MultiPolygon') {
      // For MultiPolygon, coordinates is [[outer, ...holes], ...]
      for (const poly of geom.coordinates) {
        holes.push(poly[0]) // Get outer ring of each polygon
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
