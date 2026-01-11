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
  topStations?: Array<{
    station_name: string
    pm25_concentration: number
    aqi: number
  }>
}

interface Props {}

// AQI Color Scheme (US EPA Standard)
const getAQIColor = (aqi: number): string => {
  if (aqi === 0) return '#d1d5db'    // No data (gray)
  if (aqi <= 50) return '#00e400'    // Good (0-50)
  if (aqi <= 100) return '#ffff00'   // Moderate (51-100)
  if (aqi <= 150) return '#ff7e00'   // Unhealthy for Sensitive (101-150)
  if (aqi <= 200) return '#ff0000'   // Unhealthy (151-200)
  if (aqi <= 300) return '#8f3f97'   // Very Unhealthy (201-300)
  return '#7e0023'                   // Hazardous (301+)
}

const getAQIStatus = (aqi: number): string => {
  if (aqi === 0) return 'No Data'
  if (aqi <= 50) return 'Good'
  if (aqi <= 100) return 'Moderate'
  if (aqi <= 150) return 'Unhealthy for Sensitive Groups'
  if (aqi <= 200) return 'Unhealthy'
  if (aqi <= 300) return 'Very Unhealthy'
  return 'Hazardous'
}

// Compact camera settings
const INITIAL_CENTER: [number, number] = [69.3459, 30.8] // a bit north of center
const INITIAL_ZOOM = 1.3                                // zoomed out so map is smaller

export const InteractivePakistanMap: React.FC<Props> = () => {
  const mapContainer = useRef<HTMLDivElement>(null)
  const map = useRef<maplibregl.Map | null>(null)
  const [hoveredCity, setHoveredCity] = useState<CityAQI | null>(null)
  const [clickedCity, setClickedCity] = useState<CityAQI | null>(null)
  const [cityAQIData, setCityAQIData] = useState<CityAQI[]>([])
  const [loading, setLoading] = useState(true)

  const API_BASE = 'https://hawanama-152782825429.asia-south1.run.app'

  // Fetch real city data from API
  useEffect(() => {
    const fetchCityData = async () => {
      setLoading(true)
      try {
        const cities = [
          'lahore', 'karachi', 'islamabad', 'rawalpindi', 'multan', 'faisalabad',
          'peshawar', 'quetta', 'hyderabad', 'gujranwala', 'sialkot', 'bahawalpur',
          'abbottabad', 'aliabad', 'baffa', 'bhopalwala', 'chak-jhumra', 'charsadda',
          'daska-kalan', 'dera-ismail-khan', 'diplo', 'eminabad', 'gilgit', 'haripur',
          'hundal', 'jhang', 'jhelum', 'kahna-nau', 'kamra', 'kasur', 'khairpur-mir\'s',
          'kharan', 'khurrianwala', 'kot-malik-barkhurdar', 'kotli-loharan', 'kotri',
          'ladhewala-waraich', 'lodhran', 'malam-jabba', 'malir-cantonment', 'mandi-bahauddin',
          'mangla', 'mian-channun', 'mianwali', 'mirpur-khas', 'mohmand-agency', 'muridke',
          'murree', 'muzaffarabad', 'pasrur', 'pattoki', 'pindi-bhattian', 'qadirpur-ran',
          'rahim-yar-khan', 'raiwind', 'rojhan', 'sahiwal', 'sambrial', 'sharqpur-sharif',
          'sheikhupura', 'skardu', 'sukkur', 'swabi', 'vehari'
        ]

        const cityPromises = cities.map(async (citySlug) => {
          try {
            const [cityResponse, stationsResponse] = await Promise.all([
              fetch(`${API_BASE}/api/v1/cities/${citySlug}`),
              fetch(`${API_BASE}/api/v1/cities/${citySlug}/top3-stations`)
            ])

            if (!cityResponse.ok) throw new Error(`Failed to fetch ${citySlug}`)

            const cityData = await cityResponse.json()
            let topStations = []

            if (stationsResponse.ok) {
              const stationsData = await stationsResponse.json()
              topStations = stationsData.top_stations || []
            }

            return {
              city: cityData.city_name,
              aqi: Math.round(cityData.avg_aqi),
              status: cityData.aqi_category,
              pm25: Math.round(cityData.avg_pm25),
              stationCount: cityData.station_count,
              topStations
            }
          } catch (error) {
            console.warn(`Failed to fetch data for ${citySlug}:`, error)
            return null
          }
        })

        const results = await Promise.all(cityPromises)
        const validResults = results.filter(Boolean) as CityAQI[]
        setCityAQIData(validResults)
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

    map.current = new maplibregl.Map({
      container: mapContainer.current,
      style: {
        version: 8,
        sources: {},
        layers: [
          {
            id: 'background',
            type: 'background',
            paint: { 'background-color': '#ffffff' }
          }
        ]
      },
      center: INITIAL_CENTER,
      zoom: INITIAL_ZOOM,
      maxZoom: 8,
      minZoom: 1.0,
      // loose bounds – just to keep user around PK but allow some world around it
      maxBounds: [
        [56.0, 18.0],
        [86.0, 44.0],
      ],
      interactive: true,
      dragPan: true,
      scrollZoom: true,
      doubleClickZoom: true,
      touchZoomRotate: true,
      // small, symmetric padding
      padding: { top: 20, bottom: 20, left: 20, right: 20 },
    })

    map.current.on('load', () => {
      if (!map.current) return

      map.current.addSource('pakistan-districts', {
        type: 'geojson',
        data: '/pakistan_districts.geojson',
      })

      // NOTE: no fitBounds – we rely purely on center + zoom so the map stays small and stable

      const colorExpression: any[] = ['case']
      cityAQIData.forEach(cityData => {
        colorExpression.push(['==', ['get', 'shapeName'], cityData.city])
        colorExpression.push(getAQIColor(cityData.aqi))
      })
      colorExpression.push('#e5e7eb')

      map.current.addLayer({
        id: 'districts-fill',
        type: 'fill',
        source: 'pakistan-districts',
        paint: {
          'fill-color': colorExpression,
          'fill-opacity': [
            'case',
            ['boolean', ['feature-state', 'hover'], false],
            1.0,
            0.7
          ]
        }
      })

      map.current.addLayer({
        id: 'districts-line',
        type: 'line',
        source: 'pakistan-districts',
        paint: {
          'line-color': [
            'case',
            ['boolean', ['feature-state', 'hover'], false],
            '#1f2937',
            '#9ca3af'
          ],
          'line-width': [
            'case',
            ['boolean', ['feature-state', 'hover'], false],
            3,
            0.5
          ],
          'line-opacity': 0.8
        }
      })

      const majorCities = cityAQIData.map(city => city.city)
      map.current.addLayer({
        id: 'city-labels',
        type: 'symbol',
        source: 'pakistan-districts',
        filter: ['in', ['get', 'shapeName'], ['literal', majorCities]],
        layout: {
          'text-field': ['get', 'shapeName'],
          'text-font': ['Open Sans Regular', 'Arial Unicode MS Regular'],
          'text-size': [
            'interpolate',
            ['linear'],
            ['zoom'],
            4, 0,
            4.5, 10,
            6, 14
          ],
          'text-anchor': 'center',
          'text-allow-overlap': false,
          'text-ignore-placement': false,
          'visibility': 'visible'
        },
        paint: {
          'text-color': '#1f2937',
          'text-halo-color': '#ffffff',
          'text-halo-width': 1.5,
          'text-opacity': [
            'interpolate',
            ['linear'],
            ['zoom'],
            3.5, 0,
            4.5, 1
          ]
        }
      })

      let hoveredFeatureId: string | number | undefined = null

      map.current.on('mousemove', 'districts-fill', (e) => {
        if (!map.current || !e.features || !e.features[0]) return

        if (e.features.length > 0) {
          if (hoveredFeatureId !== null && hoveredFeatureId !== undefined) {
            map.current.setFeatureState(
              { source: 'pakistan-districts', id: hoveredFeatureId },
              { hover: false }
            )
          }

          hoveredFeatureId = e.features[0].id
          map.current.setFeatureState(
            { source: 'pakistan-districts', id: hoveredFeatureId },
            { hover: true }
          )

          map.current.getCanvas().style.cursor = 'pointer'

          const districtName = e.features[0].properties?.shapeName
          const cityData = cityAQIData.find(city =>
            city.city.toLowerCase() === districtName?.toLowerCase()
          )

          setHoveredCity(cityData || null)
        }
      })

      map.current.on('mouseleave', 'districts-fill', () => {
        if (!map.current) return

        if (hoveredFeatureId !== null && hoveredFeatureId !== undefined) {
          map.current.setFeatureState(
            { source: 'pakistan-districts', id: hoveredFeatureId },
            { hover: false }
          )
        }

        hoveredFeatureId = null
        map.current.getCanvas().style.cursor = ''
        setHoveredCity(null)
      })

      // Add click event for zoom functionality
      map.current.on('click', 'districts-fill', (e) => {
        if (!map.current || !e.features || !e.features[0]) return

        const feature = e.features[0]
        const districtName = feature.properties?.shapeName
        
        // Find and set the clicked city data
        const cityData = cityAQIData.find(city =>
          city.city.toLowerCase() === districtName?.toLowerCase()
        )
        
        if (cityData) {
          setClickedCity(cityData)
        }
        
        if (feature.geometry && feature.geometry.type === 'Polygon') {
          // Get the bounds of the clicked district
          const coordinates = feature.geometry.coordinates[0]
          
          // Calculate bounds
          let minLng = Infinity, minLat = Infinity
          let maxLng = -Infinity, maxLat = -Infinity
          
          coordinates.forEach((coord: number[]) => {
            const [lng, lat] = coord
            minLng = Math.min(minLng, lng)
            maxLng = Math.max(maxLng, lng)
            minLat = Math.min(minLat, lat)
            maxLat = Math.max(maxLat, lat)
          })
          
          // Zoom to the district bounds with padding
          map.current.fitBounds(
            [[minLng, minLat], [maxLng, maxLat]],
            {
              padding: 50,
              maxZoom: 6,
              duration: 1500 // smooth animation
            }
          )
        }
      })

      // Add double-click event to zoom back out to full Pakistan view
      map.current.on('dblclick', () => {
        if (!map.current) return
        
        // Clear clicked city when zooming out
        setClickedCity(null)
        
        map.current.flyTo({
          center: INITIAL_CENTER,
          zoom: INITIAL_ZOOM,
          duration: 1500
        })
      })
    })

    return () => {
      if (map.current) {
        map.current.remove()
        map.current = null
      }
    }
  }, [cityAQIData, loading])

  return (
    <div className="flex rounded-3xl bg-white shadow-sm border border-slate-100 p-8 gap-4 min-h-[550px]">
      {/* Left: numbers */}
      <div className="w-64 flex flex-col justify-between">
        <div className="space-y-4">
          {/* Always visible title */}
          <div>
            <h3 className="text-lg font-semibold text-slate-900">
              Air Quality Across Pakistan
            </h3>
            <div className="mt-2 text-sm text-slate-500">
              {hoveredCity ? 'Click to zoom in • Double-click to zoom out' : 'Hover over a city to see details'}
            </div>
          </div>

          {/* Display data: show hovered city, or clicked city if no hover */}
          {(hoveredCity || clickedCity) && (
            <div className="bg-gradient-to-br from-white via-slate-50 to-slate-100 rounded-2xl p-4 shadow-lg border border-white/50 backdrop-blur-sm">
              <div className="text-center space-y-3">
                <h4 className="text-lg font-bold text-slate-800 tracking-tight">
                  {(hoveredCity || clickedCity)?.city}
                </h4>

                <div className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-bold shadow-lg border-2 ${
                  (hoveredCity || clickedCity)?.aqi === 0 ? 'bg-gray-50 text-gray-800 border-gray-200' :
                  (hoveredCity || clickedCity)?.status === 'good' ? 'bg-emerald-50 text-emerald-800 border-emerald-200' :
                  (hoveredCity || clickedCity)?.status === 'moderate' ? 'bg-yellow-50 text-yellow-800 border-yellow-200' :
                  (hoveredCity || clickedCity)?.status === 'unhealthy_sensitive' ? 'bg-orange-50 text-orange-800 border-orange-200' :
                  (hoveredCity || clickedCity)?.status === 'unhealthy' ? 'bg-red-50 text-red-800 border-red-200' :
                  (hoveredCity || clickedCity)?.status === 'very_unhealthy' ? 'bg-purple-50 text-purple-800 border-purple-200' :
                  'bg-red-100 text-red-900 border-red-300'
                }`}>
                  {getAQIStatus((hoveredCity || clickedCity)?.aqi || 0)}
                </div>

                <div className="bg-white/80 rounded-lg p-3 shadow-inner border border-slate-200/50">
                  <div className="flex items-baseline justify-center gap-1">
                    <span className="text-2xl font-black text-slate-900 tracking-tight">
                      {(hoveredCity || clickedCity)?.pm25 || (hoveredCity || clickedCity)?.aqi}
                    </span>
                    <span className="text-xs font-medium text-slate-600">µg/m³</span>
                  </div>
                  <div className="text-xs text-slate-500 mt-1 font-medium">PM₂.₅ Concentration</div>
                </div>

                {(hoveredCity || clickedCity)?.stationCount && (
                  <div className="flex items-center justify-center gap-1 text-slate-600 bg-white/60 rounded-lg px-2 py-1 shadow-sm">
                    <svg className="w-3 h-3 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
                    </svg>
                    <span className="text-xs font-semibold">{(hoveredCity || clickedCity)?.stationCount} Stations</span>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Right: Interactive Map */}
      <div className="flex flex-1 items-center justify-center">
        {loading ? (
          <div className="w-[650px] h-[500px] rounded-xl bg-white flex items-center justify-center">
            <div className="text-gray-500 text-sm">Loading city data...</div>
          </div>
        ) : (
          <div
            ref={mapContainer}
            className="w-[650px] h-[500px] rounded-xl overflow-hidden"
          />
        )}
      </div>
    </div>
  )
}
