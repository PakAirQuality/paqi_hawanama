import { useEffect, useRef, useState } from 'react'
import type mapboxglType from 'mapbox-gl'
import { MAP_CONFIG } from '../config/mapConfig'
import { waitForContainerSize, applyClimateTracePolish } from '../utils/mapUtils'

interface UseMapInstanceProps {
  center?: [number, number]
  zoom?: number
  onLoad?: (map: mapboxglType.Map) => void
  loading?: boolean
}

/**
 * Hook for initializing and managing Mapbox map instance
 */
export const useMapInstance = ({ 
  center = MAP_CONFIG.center, 
  zoom = MAP_CONFIG.zoom, 
  onLoad,
  loading = false
}: UseMapInstanceProps) => {
  const mapContainer = useRef<HTMLDivElement>(null)
  const map = useRef<mapboxglType.Map | null>(null)
  const [mapInstance, setMapInstance] = useState<mapboxglType.Map | null>(null)
  const onLoadRef = useRef(onLoad)
  
  // Update onLoad ref when it changes
  useEffect(() => {
    onLoadRef.current = onLoad
  }, [onLoad])

  useEffect(() => {
    let cancelled = false
    
    if (loading || !mapContainer.current) return

    const initializeMap = async () => {
      try {
        const mapboxgl = (await import('mapbox-gl')).default as typeof mapboxglType
        
        if (!MAP_CONFIG.accessToken) {
          console.error('Mapbox access token not found')
          return
        }
        
        mapboxgl.accessToken = MAP_CONFIG.accessToken
        await waitForContainerSize(mapContainer.current!)
        
        if (cancelled) return

        // Clean up existing map
        if (map.current) { 
          map.current.remove()
          map.current = null 
        }

        const newMapInstance = new mapboxgl.Map({
          container: mapContainer.current!,
          style: MAP_CONFIG.style,
          center,
          zoom,
          projection: MAP_CONFIG.projection,
          attributionControl: false,
          config: MAP_CONFIG.config,
          minZoom: 2,
          maxZoom: 18,
          antialias: true,                  // <— smoother 3D edges
        })
        
        map.current = newMapInstance
        setMapInstance(newMapInstance)

        const loadTimeout = setTimeout(() => { 
          if (!cancelled) console.error('map load timeout') 
        }, 10000)

        newMapInstance.once('load', () => {
          clearTimeout(loadTimeout)
          if (cancelled) return
          
          newMapInstance.resize()
          newMapInstance.setPitch(0)
          newMapInstance.triggerRepaint()
          
          onLoadRef.current?.(newMapInstance)
        })

        // Apply Climate TRACE polish after style loads
        newMapInstance.once('style.load', () => {
          if (cancelled) return
          applyClimateTracePolish(newMapInstance)
        })

        newMapInstance.on('error', (e: any) => {
          console.error('mapbox error:', e?.error || e)
        })

      } catch (error) {
        console.error('Map initialization error:', error)
      }
    }

    initializeMap()
    
    return () => {
      cancelled = true
      map.current?.remove()
      map.current = null
      setMapInstance(null)
    }
  }, [center, zoom, loading])

  return { mapContainer, map: mapInstance }
}