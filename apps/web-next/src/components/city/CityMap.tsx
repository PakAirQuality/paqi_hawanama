'use client'

import { useEffect, useRef, useCallback } from 'react'
import 'maplibre-gl/dist/maplibre-gl.css'
import type { Map as MapLibreMap, Marker } from 'maplibre-gl'

interface CityMapProps {
  center?: [number, number]
  zoom?: number
  className?: string
  cityName?: string
  stations?: Array<{ 
    id: string
    name: string
    latitude: number
    longitude: number
    latest_aqi?: number
    aqi_category?: string
    latest_pm25?: number
  }>
}

export default function CityMap({ 
  center = [78, 22], // South Asia center
  zoom = 11,
  className = "w-full h-full",
  cityName,
  stations = []
}: CityMapProps) {
  const mapContainer = useRef<HTMLDivElement>(null)
  const map = useRef<MapLibreMap | null>(null)
  const markersRef = useRef<Marker[]>([])

  // Calculate center from stations if not provided or if using fallback coordinates
  const calculateCenterFromStations = (): [number, number] => {
    if (!stations || stations.length === 0) {
      return [78, 22] // South Asia center fallback
    }
    
    const validStations = stations.filter(s => 
      s.longitude && s.latitude && 
      !isNaN(s.longitude) && !isNaN(s.latitude)
    )
    
    if (validStations.length === 0) {
      return [78, 22] // South Asia center fallback
    }
    
    // Calculate average coordinates
    const avgLng = validStations.reduce((sum, s) => sum + s.longitude, 0) / validStations.length
    const avgLat = validStations.reduce((sum, s) => sum + s.latitude, 0) / validStations.length
    
    console.log('🗺️ CityMap: Calculated center from stations:', [avgLng, avgLat])
    return [avgLng, avgLat]
  }

  // Use calculated center if provided center is the Lahore fallback or invalid
  const isLahoreFallback = (center[0] === 74.3587 && center[1] === 31.5204)
  const isInvalidCenter = !center || isNaN(center[0]) || isNaN(center[1])
  
  const validCenter: [number, number] = (isLahoreFallback || isInvalidCenter) 
    ? calculateCenterFromStations()
    : [
        (typeof center[0] === 'number' && !isNaN(center[0])) ? center[0] : 69.3451,
        (typeof center[1] === 'number' && !isNaN(center[1])) ? center[1] : 30.3753
      ]

  // AQI colors - match main map exactly
  const AQI_COLORS = {
    good: 'rgba(110, 204, 57, 1)',             // Green from cluster-small div
    moderate: 'rgba(240, 194, 12, 1)',         // Yellow from cluster-medium div  
    unhealthy_sensitive: 'rgba(241, 128, 23, 1)', // Orange from cluster-large div
    unhealthy: 'rgba(239, 120, 85, 1)',        // More red, slightly darker shade
    very_unhealthy: '#a070b5',                  // Purple for very unhealthy
    hazardous: '#991b1b',                       // Dark red for hazardous
    fallback: '#6b7280'                         // Gray
  }

  // Style configuration - match main map exactly
  const POINT_STYLE = {
    radius: 12,
    strokeWidth: 1,
    strokeColor: '#FFFFFF',
    textSize: 10,
    opacity: 1.0
  }

  const getAQIColor = (aqi_category?: string, aqi_value?: number) => {
    // Handle 0 AQI values with off-white color
    if (aqi_value === 0) return '#FFFFFFE6'
    
    switch (aqi_category) {
      case 'good': return AQI_COLORS.good
      case 'moderate': return AQI_COLORS.moderate
      case 'unhealthy_sensitive': return AQI_COLORS.unhealthy_sensitive
      case 'unhealthy': return AQI_COLORS.unhealthy
      case 'very_unhealthy': return AQI_COLORS.very_unhealthy
      case 'hazardous': return AQI_COLORS.hazardous
      default: return AQI_COLORS.fallback
    }
  }

  // Function to load and add city airshed polygon
  const addCityAirshed = useCallback(async () => {
    if (!map.current || !cityName) {
      console.log('🗺️ CityMap: Cannot add airshed:', { 
        hasMap: !!map.current,
        cityName
      })
      return
    }

    try {
      console.log('🗺️ CityMap: Loading airshed for city:', cityName)
      
      // Fetch the city polygons GeoJSON
      const response = await fetch('/city_station_polygons.geojson')
      const geoData = await response.json()
      
      // Find the polygon for this city (case-insensitive match)
      const cityFeature = geoData.features.find((feature: any) => 
        feature.properties.city_name.toLowerCase() === cityName.toLowerCase()
      )
      
      if (!cityFeature) {
        console.log('🗺️ CityMap: No airshed found for city:', cityName)
        return
      }
      
      console.log('🗺️ CityMap: Found airshed for', cityName, 'with area:', cityFeature.properties.area_km2, 'km²')
      
      // Add source if it doesn't exist
      if (!map.current.getSource('city-airshed')) {
        map.current.addSource('city-airshed', {
          type: 'geojson',
          data: {
            type: 'FeatureCollection',
            features: [cityFeature]
          }
        })
      }
      
      // Add fill layer for the airshed
      if (!map.current.getLayer('city-airshed-fill')) {
        map.current.addLayer({
          id: 'city-airshed-fill',
          type: 'fill',
          source: 'city-airshed',
          paint: {
            'fill-color': 'transparent', // Hide city boundary fill
            'fill-opacity': 0
          }
        })
      }
      
      // Add line layer for the airshed border
      if (!map.current.getLayer('city-airshed-line')) {
        map.current.addLayer({
          id: 'city-airshed-line',
          type: 'line',
          source: 'city-airshed',
          paint: {
            'line-color': 'transparent', // Hide city boundary line
            'line-width': 0,
            'line-opacity': 0
          }
        })
      }
      
      console.log('🗺️ CityMap: Successfully added airshed for', cityName)
    } catch (error) {
      console.error('🗺️ CityMap: Error loading airshed:', error)
    }
  }, [cityName])

  // Function to create station markers
  const addMarkers = useCallback(async () => {
    if (!map.current || !stations || stations.length === 0) {
      console.log('🗺️ CityMap: Cannot add markers:', { 
        hasMap: !!map.current,
        stationsCount: stations?.length 
      })
      return
    }
    
    console.log('🗺️ CityMap: Adding markers for', stations.length, 'stations')
    console.log('🗺️ CityMap: First station sample:', stations[0])
    
    try {
      // Import MapLibre GL for marker creation
      const maplibre = await import('maplibre-gl')
      
      // Clear existing markers
      markersRef.current.forEach(marker => marker.remove())
      markersRef.current = []

      stations.forEach((station, index) => {
        if (!station.longitude || !station.latitude) {
          console.log('🗺️ CityMap: Skipping station without coordinates:', station.name)
          return
        }

        // Debug station data
        if (index === 0) {
          console.log('🗺️ CityMap: Station data fields:', {
            id: station.id,
            name: station.name,
            latest_aqi: station.latest_aqi,
            aqi_category: station.aqi_category,
            latest_pm25: station.latest_pm25,
            lat: station.latitude,
            lng: station.longitude
          })
        }

        // Create circular marker element - match main map styling exactly
        const el = document.createElement('div')
        el.className = 'station-marker'
        el.style.width = `${POINT_STYLE.radius * 2}px`
        el.style.height = `${POINT_STYLE.radius * 2}px`
        el.style.borderRadius = '50%'
        el.style.backgroundColor = getAQIColor(station.aqi_category, station.latest_aqi)
        el.style.border = `${POINT_STYLE.strokeWidth}px solid ${POINT_STYLE.strokeColor}`
        el.style.boxShadow = '0 2px 4px rgba(0,0,0,0.3)'
        el.style.display = 'flex'
        el.style.alignItems = 'center'
        el.style.justifyContent = 'center'
        el.style.fontSize = `${POINT_STYLE.textSize}px`
        el.style.fontWeight = 'bold'
        el.style.fontFamily = 'Arial, sans-serif'
        el.style.color = 'rgb(0,0,0)'  // Black text like main map
        el.style.textShadow = '0 0 1px rgb(255,255,255)'  // White halo like main map
        el.style.opacity = POINT_STYLE.opacity.toString()
        
        // Add PM2.5 value as text inside circle - match main map field
        if (station.latest_pm25 && station.latest_pm25 > 0) {
          el.textContent = Math.round(station.latest_pm25).toString()
        }

        // No click handlers - user requested no navigation

        // Create marker
        const marker = new maplibre.Marker({ element: el })
          .setLngLat([station.longitude, station.latitude])
          .addTo(map.current!)

        markersRef.current.push(marker)
      })

      console.log('🗺️ CityMap: Successfully added', markersRef.current.length, 'markers')
    } catch (error) {
      console.error('🗺️ CityMap: Error adding markers:', error)
    }
  }, [stations])

  // Initialize map
  useEffect(() => {
    if (map.current) return // Initialize map only once
    
    const initMap = async () => {
      if (!mapContainer.current) return
      
      try {
        // Dynamic import of MapLibre GL
        const maplibre = await import('maplibre-gl')
        console.log('🗺️ CityMap: Initializing with center:', validCenter, 'zoom:', zoom)
        
        map.current = new maplibre.Map({
          container: mapContainer.current,
          style: {
            version: 8,
            sources: {
              'osm': {
                type: 'raster',
                tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
                tileSize: 256,
                attribution: '© OpenStreetMap contributors'
              }
            },
            layers: [
              {
                id: 'osm',
                type: 'raster',
                source: 'osm'
              }
            ]
          },
          center: validCenter,
          zoom: zoom
        })

        map.current.on('load', () => {
          console.log('🗺️ CityMap: Map loaded, adding markers for', stations.length, 'stations')
          addCityAirshed() // Add city airshed first
          addMarkers()
          
          // Auto-fit to stations if we have them
          if (stations && stations.length > 1) {
            fitMapToStations()
          }
        })

        map.current.on('error', (e: any) => {
          console.error('🗺️ CityMap: Map error:', e)
        })

      } catch (error) {
        console.error('🗺️ CityMap: Failed to initialize map:', error)
      }
    }

    initMap()

    return () => {
      if (map.current) {
        markersRef.current.forEach(marker => marker.remove())
        markersRef.current = []
        map.current.remove()
        map.current = null
      }
    }
  }, [validCenter[0], validCenter[1], zoom, stations?.length, addCityAirshed]) // Add stations length to re-initialize if stations change significantly

  // Update markers when stations data changes
  useEffect(() => {
    if (!map.current || !stations) return
    
    console.log('🗺️ CityMap: Stations data updated, refreshing markers')
    addMarkers()
  }, [stations, addMarkers])

  // Function to fit map bounds to all stations
  const fitMapToStations = useCallback(() => {
    if (!map.current || !stations || stations.length === 0) return
    
    const validStations = stations.filter(s => 
      s.longitude && s.latitude && 
      !isNaN(s.longitude) && !isNaN(s.latitude)
    )
    
    if (validStations.length === 0) return
    
    if (validStations.length === 1) {
      // Single station - center on it
      map.current.setCenter([validStations[0].longitude, validStations[0].latitude])
      map.current.setZoom(12)
      return
    }
    
    // Multiple stations - fit bounds
    const bounds = validStations.reduce(
      (bounds, station) => {
        return [
          [Math.min(bounds[0][0], station.longitude), Math.min(bounds[0][1], station.latitude)],
          [Math.max(bounds[1][0], station.longitude), Math.max(bounds[1][1], station.latitude)]
        ]
      },
      [[validStations[0].longitude, validStations[0].latitude], [validStations[0].longitude, validStations[0].latitude]]
    )
    
    map.current.fitBounds(bounds as [[number, number], [number, number]], {
      padding: 50,
      maxZoom: 14
    })
    
    console.log('🗺️ CityMap: Fitted map to', validStations.length, 'stations')
  }, [stations])

  return (
    <div className="relative w-full h-full">
      <div 
        ref={mapContainer} 
        className="w-full h-full min-h-[300px]"
        style={{ minHeight: '300px' }}
      />
    </div>
  )
}