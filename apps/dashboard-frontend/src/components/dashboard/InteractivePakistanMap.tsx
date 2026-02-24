'use client'

import React, { useEffect, useRef, useState } from 'react'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'

interface CityAQI {
  city: string
  aqi: number
  status: string
  pm25?: number
  stationCount?: number
}

interface Props {}

const MAPBOX_TOKEN = '***REMOVED***'

// Zoom threshold for transitioning between province and district views
const DISTRICT_ZOOM_THRESHOLD = 5

// AQLI-style warm color scale (yellow → orange → red → maroon)
const getAQIColor = (aqi: number): string => {
  if (aqi === 0) return '#e5e7eb'      // No data - light gray
  if (aqi <= 50) return '#ffffb2'      // Good - light yellow
  if (aqi <= 100) return '#fecc5c'     // Moderate - yellow-orange
  if (aqi <= 150) return '#fd8d3c'     // Unhealthy for Sensitive - orange
  if (aqi <= 200) return '#f03b20'     // Unhealthy - red-orange
  if (aqi <= 300) return '#bd0026'     // Very Unhealthy - dark red
  return '#7a0023'                      // Hazardous - maroon
}

const getAQIStatus = (aqi: number): string => {
  if (aqi === 0) return 'No Data'
  if (aqi <= 50) return 'Good'
  if (aqi <= 100) return 'Moderate'
  if (aqi <= 150) return 'Unhealthy for Sensitive'
  if (aqi <= 200) return 'Unhealthy'
  if (aqi <= 300) return 'Very Unhealthy'
  return 'Hazardous'
}

const getStatusColor = (status: string, aqi: number) => {
  if (aqi === 0) return { bg: 'bg-gray-100', text: 'text-gray-600', border: 'border-gray-200' }
  if (aqi <= 50) return { bg: 'bg-yellow-50', text: 'text-yellow-700', border: 'border-yellow-200' }
  if (aqi <= 100) return { bg: 'bg-amber-50', text: 'text-amber-700', border: 'border-amber-200' }
  if (aqi <= 150) return { bg: 'bg-orange-50', text: 'text-orange-700', border: 'border-orange-200' }
  if (aqi <= 200) return { bg: 'bg-red-50', text: 'text-red-700', border: 'border-red-200' }
  if (aqi <= 300) return { bg: 'bg-red-100', text: 'text-red-800', border: 'border-red-300' }
  return { bg: 'bg-red-200', text: 'text-red-900', border: 'border-red-400' }
}

const INITIAL_CENTER: [number, number] = [69.3459, 30.3]
const INITIAL_ZOOM = 3.5


export const InteractiveRegionalMap: React.FC<Props> = () => {
  const mapContainer = useRef<HTMLDivElement>(null)
  const map = useRef<maplibregl.Map | null>(null)
  const [hoveredCity, setHoveredCity] = useState<CityAQI | null>(null)
  const [hoveredProvince, setHoveredProvince] = useState<string | null>(null)
  const [cityAQIData, setCityAQIData] = useState<CityAQI[]>([])
  const [loading, setLoading] = useState(true)
  const [viewLevel, setViewLevel] = useState<'province' | 'district'>('province')

  const API_BASE = 'https://hawanama-152782825429.asia-south1.run.app'

  useEffect(() => {
    const fetchCityData = async () => {
      setLoading(true)
      try {
        const response = await fetch(`${API_BASE}/api/v1/cities/summary-all`)
        if (!response.ok) throw new Error('Failed to fetch city summaries')

        const data = await response.json()
        const results: CityAQI[] = data.cities.map((city: any) => ({
          city: city.city_name,
          aqi: city.avg_aqi || 0,
          status: city.aqi_category,
          pm25: city.avg_pm25,
          stationCount: city.station_count,
        }))

        setCityAQIData(results)
      } catch (error) {
        console.error('Error fetching city data:', error)
      } finally {
        setLoading(false)
      }
    }

    fetchCityData()
  }, [])

  useEffect(() => {
    if (!mapContainer.current || map.current || loading || cityAQIData.length === 0) return

    // Simple raster tile style
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

    map.current = new maplibregl.Map({
      container: mapContainer.current,
      style: mapStyle,
      center: INITIAL_CENTER,
      zoom: INITIAL_ZOOM,
      maxZoom: 10,
      minZoom: 2,
    })

    map.current.on('load', () => {
        if (!map.current) return

        // Load district boundaries
        map.current.addSource('pakistan-districts', {
          type: 'geojson',
          data: '/pakistan_districts.geojson',
          generateId: true,
        })

        // Load province boundaries
        map.current.addSource('pakistan-provinces', {
          type: 'geojson',
          data: '/pakistan_adm1.geojson',
          generateId: true,
        })

        // District color expression
        const districtColorExpression: any[] = ['case']
        cityAQIData.forEach(cityData => {
          districtColorExpression.push(['==', ['get', 'shapeName'], cityData.city])
          districtColorExpression.push(getAQIColor(cityData.aqi))
        })
        districtColorExpression.push('#e5e7eb')

        // === PROVINCE LAYERS (visible at low zoom, fade out as zoom increases) ===

        // Province fill layer - transparent, just for interaction
        map.current.addLayer({
          id: 'provinces-fill',
          type: 'fill',
          source: 'pakistan-provinces',
          maxzoom: DISTRICT_ZOOM_THRESHOLD + 0.5,
          paint: {
            'fill-color': [
              'case',
              ['boolean', ['feature-state', 'hover'], false],
              '#e2e8f0',
              'transparent'
            ],
            'fill-opacity': [
              'interpolate', ['linear'], ['zoom'],
              DISTRICT_ZOOM_THRESHOLD - 0.5, ['case', ['boolean', ['feature-state', 'hover'], false], 0.5, 0],
              DISTRICT_ZOOM_THRESHOLD + 0.5, 0
            ]
          }
        })

        // Province borders - subtle, darker on hover
        map.current.addLayer({
          id: 'provinces-line',
          type: 'line',
          source: 'pakistan-provinces',
          paint: {
            'line-color': [
              'case',
              ['boolean', ['feature-state', 'hover'], false],
              '#1f2937',
              '#94a3b8'
            ],
            'line-width': [
              'interpolate', ['linear'], ['zoom'],
              DISTRICT_ZOOM_THRESHOLD - 0.5, ['case', ['boolean', ['feature-state', 'hover'], false], 2.5, 1],
              DISTRICT_ZOOM_THRESHOLD + 1, ['case', ['boolean', ['feature-state', 'hover'], false], 1.5, 0.5]
            ],
            'line-opacity': [
              'interpolate', ['linear'], ['zoom'],
              DISTRICT_ZOOM_THRESHOLD - 0.5, 0.7,
              DISTRICT_ZOOM_THRESHOLD + 1, 0.3
            ]
          }
        })

        // === DISTRICT LAYERS (fade in as zoom increases) ===

        // District fill layer
        map.current.addLayer({
          id: 'districts-fill',
          type: 'fill',
          source: 'pakistan-districts',
          minzoom: DISTRICT_ZOOM_THRESHOLD - 0.5,
          paint: {
            'fill-color': districtColorExpression,
            'fill-opacity': [
              'interpolate', ['linear'], ['zoom'],
              DISTRICT_ZOOM_THRESHOLD - 0.5, 0,
              DISTRICT_ZOOM_THRESHOLD + 0.5, ['case', ['boolean', ['feature-state', 'hover'], false], 0.9, 0.75]
            ]
          }
        })

        // District borders - subtle
        map.current.addLayer({
          id: 'districts-line',
          type: 'line',
          source: 'pakistan-districts',
          minzoom: DISTRICT_ZOOM_THRESHOLD - 0.5,
          paint: {
            'line-color': [
              'case',
              ['boolean', ['feature-state', 'hover'], false],
              '#475569',
              '#94a3b8'
            ],
            'line-width': [
              'case',
              ['boolean', ['feature-state', 'hover'], false],
              1.5,
              0.3
            ],
            'line-opacity': [
              'interpolate', ['linear'], ['zoom'],
              DISTRICT_ZOOM_THRESHOLD - 0.5, 0,
              DISTRICT_ZOOM_THRESHOLD + 0.5, 0.5
            ]
          }
        })

        // === ZOOM-BASED VIEW LEVEL TRACKING ===

        map.current.on('zoom', () => {
          if (!map.current) return
          const currentZoom = map.current.getZoom()
          const newViewLevel = currentZoom >= DISTRICT_ZOOM_THRESHOLD ? 'district' : 'province'
          setViewLevel(newViewLevel)

          // Clear hover states when transitioning
          if (newViewLevel === 'province') {
            setHoveredCity(null)
          } else {
            setHoveredProvince(null)
          }
        })

        // === PROVINCE INTERACTIONS ===

        let hoveredProvinceId: string | number | undefined = undefined

        map.current.on('mousemove', 'provinces-fill', (e) => {
          if (!map.current || !e.features || !e.features[0]) return

          const currentZoom = map.current.getZoom()
          if (currentZoom >= DISTRICT_ZOOM_THRESHOLD) return

          if (hoveredProvinceId !== undefined) {
            map.current.setFeatureState(
              { source: 'pakistan-provinces', id: hoveredProvinceId },
              { hover: false }
            )
          }

          hoveredProvinceId = e.features[0].id
          map.current.setFeatureState(
            { source: 'pakistan-provinces', id: hoveredProvinceId },
            { hover: true }
          )
          map.current.getCanvas().style.cursor = 'pointer'

          const provinceName = e.features[0].properties?.shapeName
          setHoveredProvince(provinceName)
        })

        map.current.on('mouseleave', 'provinces-fill', () => {
          if (!map.current) return
          if (hoveredProvinceId !== undefined) {
            map.current.setFeatureState(
              { source: 'pakistan-provinces', id: hoveredProvinceId },
              { hover: false }
            )
          }
          hoveredProvinceId = undefined
          map.current.getCanvas().style.cursor = ''
          setHoveredProvince(null)
        })

        map.current.on('click', 'provinces-fill', (e) => {
          if (!map.current || !e.features || !e.features[0]) return

          const currentZoom = map.current.getZoom()
          if (currentZoom >= DISTRICT_ZOOM_THRESHOLD) return

          const feature = e.features[0]

          if (feature.geometry) {
            const bounds = new maplibregl.LngLatBounds()

            const addCoords = (coords: any) => {
              if (typeof coords[0] === 'number') {
                bounds.extend(coords as [number, number])
              } else {
                coords.forEach(addCoords)
              }
            }

            if (feature.geometry.type === 'Polygon' || feature.geometry.type === 'MultiPolygon') {
              addCoords(feature.geometry.coordinates)
            }

            map.current.fitBounds(bounds, {
              padding: 50,
              maxZoom: 7,
              duration: 1000
            })
          }
        })

        // === DISTRICT INTERACTIONS ===

        let hoveredDistrictId: string | number | undefined = undefined

        map.current.on('mousemove', 'districts-fill', (e) => {
          if (!map.current || !e.features || !e.features[0]) return

          const currentZoom = map.current.getZoom()
          if (currentZoom < DISTRICT_ZOOM_THRESHOLD) return

          if (hoveredDistrictId !== undefined) {
            map.current.setFeatureState(
              { source: 'pakistan-districts', id: hoveredDistrictId },
              { hover: false }
            )
          }

          hoveredDistrictId = e.features[0].id
          map.current.setFeatureState(
            { source: 'pakistan-districts', id: hoveredDistrictId },
            { hover: true }
          )
          map.current.getCanvas().style.cursor = 'pointer'

          const districtName = e.features[0].properties?.shapeName
          const cityData = cityAQIData.find(city =>
            city.city.toLowerCase() === districtName?.toLowerCase()
          )
          setHoveredCity(cityData || { city: districtName || 'Unknown', aqi: 0, status: 'No Data' })
        })

        map.current.on('mouseleave', 'districts-fill', () => {
          if (!map.current) return
          if (hoveredDistrictId !== undefined) {
            map.current.setFeatureState(
              { source: 'pakistan-districts', id: hoveredDistrictId },
              { hover: false }
            )
          }
          hoveredDistrictId = undefined
          map.current.getCanvas().style.cursor = ''
          setHoveredCity(null)
        })

        map.current.on('click', 'districts-fill', (e) => {
          if (!map.current || !e.features || !e.features[0]) return

          const currentZoom = map.current.getZoom()
          if (currentZoom < DISTRICT_ZOOM_THRESHOLD) return

          const feature = e.features[0]

          if (feature.geometry && (feature.geometry.type === 'Polygon' || feature.geometry.type === 'MultiPolygon')) {
            const bounds = new maplibregl.LngLatBounds()

            const addCoords = (coords: any) => {
              if (typeof coords[0] === 'number') {
                bounds.extend(coords as [number, number])
              } else {
                coords.forEach(addCoords)
              }
            }

            addCoords(feature.geometry.coordinates)

            map.current.fitBounds(bounds, {
              padding: 50,
              maxZoom: 9,
              duration: 1000
            })
          }
        })
      })

    return () => {
      if (map.current) {
        map.current.remove()
        map.current = null
      }
    }
  }, [cityAQIData, loading])

  // Determine what to display
  const statusColors = hoveredCity ? getStatusColor(hoveredCity.status, hoveredCity.aqi) : null

  return (
    <div className="relative w-full h-[calc(100vh-108px)] min-h-[500px]">
      {loading ? (
        <div className="absolute inset-0 flex items-center justify-center bg-slate-100">
          <div className="text-slate-500 text-sm">Loading...</div>
        </div>
      ) : (
        <div ref={mapContainer} className="w-full h-full" />
      )}

      {/* Province hover tooltip */}
      {viewLevel === 'province' && hoveredProvince && (
        <div className="absolute top-6 left-6 bg-white/95 backdrop-blur-sm rounded-xl shadow-2xl border border-slate-200/60 overflow-hidden px-4 py-3">
          <h3 className="text-lg font-bold text-slate-800">{hoveredProvince}</h3>
          <p className="text-sm text-slate-500 mt-1">Click to explore districts</p>
        </div>
      )}

      {/* District info card */}
      {viewLevel === 'district' && hoveredCity && statusColors && (
        <div className="absolute top-6 left-6 bg-white/95 backdrop-blur-sm rounded-xl shadow-2xl border border-slate-200/60 overflow-hidden min-w-[220px]">
          {/* Header with city name */}
          <div className={`px-4 py-3 ${statusColors.bg} border-b ${statusColors.border}`}>
            <h3 className="text-lg font-bold text-slate-800">{hoveredCity.city}</h3>
            <div className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold mt-1.5 ${statusColors.bg} ${statusColors.text} border ${statusColors.border}`}>
              {getAQIStatus(hoveredCity.aqi)}
            </div>
          </div>

          {/* Stats */}
          <div className="px-4 py-4 space-y-3">
            <div>
              <div className="text-xs text-slate-500 uppercase tracking-wide font-medium">PM₂.₅ Level</div>
              <div className="flex items-baseline gap-1.5 mt-1">
                <span className="text-3xl font-bold text-slate-900">
                  {hoveredCity.pm25?.toFixed(1) || hoveredCity.aqi}
                </span>
                <span className="text-sm text-slate-500">µg/m³</span>
              </div>
            </div>

            {hoveredCity.stationCount && (
              <div className="flex items-center gap-2 text-slate-600 pt-3 border-t border-slate-100">
                <svg className="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
                </svg>
                <span className="text-sm font-medium">{hoveredCity.stationCount} monitoring stations</span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Zoom hint when at district level but not hovering */}
      {viewLevel === 'district' && !hoveredCity && (
        <div className="absolute top-6 left-6 bg-white/95 backdrop-blur-sm rounded-xl shadow-lg border border-slate-200/60 px-4 py-3">
          <p className="text-sm text-slate-600">Hover over districts for details</p>
          <p className="text-xs text-slate-400 mt-1">Zoom out to see provinces</p>
        </div>
      )}
    </div>
  )
}
