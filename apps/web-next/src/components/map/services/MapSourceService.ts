import type mapboxglType from 'mapbox-gl'
import type { Station } from '@/lib/api'
import { STYLES } from '../config/mapConfig'

/**
 * Service for managing map data sources
 */
export class MapSourceService {
  constructor(private map: mapboxglType.Map) {}

  /**
   * Initialize all map sources
   */
  initializeSources() {
    if (!this.map.getSource('clusters')) {
      this.map.addSource('clusters', { 
        type: 'geojson', 
        data: { type: 'FeatureCollection', features: [] } 
      })
    }
    
    if (!this.map.getSource('unclustered-points')) {
      this.map.addSource('unclustered-points', { 
        type: 'geojson', 
        data: { type: 'FeatureCollection', features: [] } 
      })
    }
    
    
    if (!this.map.getSource('heatmap-points')) {
      this.map.addSource('heatmap-points', { 
        type: 'geojson', 
        data: { type: 'FeatureCollection', features: [] } 
      })
    }
    
    // Add Pakistan boundary and country focus layers with delay
    setTimeout(() => {
      // Check if map is still valid and available
      if (!this.map || this.map._removed) return
      
      if (!this.map.getSource('pakistan-boundary')) {
        this.map.addSource('pakistan-boundary', { 
          type: 'geojson', 
          data: '/pakistan.geojson' 
        })
        
        if (!this.map.getLayer('pakistan-outline')) {
          this.map.addLayer({
            id: 'pakistan-outline',
            type: 'line',
            source: 'pakistan-boundary',
            paint: { 
              'line-color': STYLES.pakistan.lineColor, 
              'line-width': STYLES.pakistan.lineWidth, 
              'line-opacity': STYLES.pakistan.lineOpacity 
            }
          })
        }
      }
      
      // Add world mask source for outside dimming
      if (!this.map.getSource('world-mask')) {
        // Create a world polygon that excludes Pakistan
        this.map.addSource('world-mask', {
          type: 'geojson',
          data: {
            type: 'FeatureCollection',
            features: [{
              type: 'Feature',
              properties: {},
              geometry: {
                type: 'Polygon',
                coordinates: [[
                  [-180, -85], [-180, 85], [180, 85], [180, -85], [-180, -85]
                ]]
              }
            }]
          }
        })
      }
      
      // Add provincial boundaries source
      if (!this.map.getSource('provincial-boundaries')) {
        this.map.addSource('provincial-boundaries', { 
          type: 'geojson', 
          data: '/pakistan_provinces.geojson' 
        })
      }
    }, 1000)
  }

  /**
   * Update cluster data source
   */
  updateClusters(features: any[]) {
    const source = this.map.getSource('clusters') as mapboxglType.GeoJSONSource
    source?.setData({ type: 'FeatureCollection', features })
  }

  /**
   * Update unclustered points data source
   */
  updatePoints(features: any[]) {
    const source = this.map.getSource('unclustered-points') as mapboxglType.GeoJSONSource
    source?.setData({ type: 'FeatureCollection', features })
  }

  /**
   * Update heatmap points data source
   */
  updateHeatmapPoints(stations: Station[]) {
    const heatmapFeatures = stations.map(station => ({
      type: 'Feature' as const,
      properties: {
        id: station.id,
        aqi: station.aqi_raw || 0,  // Fixed: use aqi_raw instead of nested pollution_aqius
        pm25: station.pm25 || 0,    // Fixed: use pm25 instead of nested p2_conc
        name: station.name,
        city: station.city
      },
      geometry: {
        type: 'Point' as const,
        coordinates: [station.longitude, station.latitude]
      }
    }))

    const source = this.map.getSource('heatmap-points') as mapboxglType.GeoJSONSource
    source?.setData({ type: 'FeatureCollection', features: heatmapFeatures })
  }
  
  
  /**
   * Show country focus layers (Pakistan emphasis + world dimming)
   */
  showCountryFocus() {
    // These layers are initialized by MapLayerService
    if (this.map.getLayer('pakistan-focus-fill')) {
      this.map.setLayoutProperty('pakistan-focus-fill', 'visibility', 'visible')
    }
    if (this.map.getLayer('pakistan-focus-glow')) {
      this.map.setLayoutProperty('pakistan-focus-glow', 'visibility', 'visible')
    }
    if (this.map.getLayer('pakistan-focus-stroke')) {
      this.map.setLayoutProperty('pakistan-focus-stroke', 'visibility', 'visible')
    }
    if (this.map.getLayer('world-mask-fill')) {
      this.map.setLayoutProperty('world-mask-fill', 'visibility', 'visible')
    }
  }
  
  /**
   * Hide country focus layers
   */
  hideCountryFocus() {
    if (this.map.getLayer('pakistan-focus-fill')) {
      this.map.setLayoutProperty('pakistan-focus-fill', 'visibility', 'none')
    }
    if (this.map.getLayer('pakistan-focus-glow')) {
      this.map.setLayoutProperty('pakistan-focus-glow', 'visibility', 'none')
    }
    if (this.map.getLayer('pakistan-focus-stroke')) {
      this.map.setLayoutProperty('pakistan-focus-stroke', 'visibility', 'none')
    }
    if (this.map.getLayer('world-mask-fill')) {
      this.map.setLayoutProperty('world-mask-fill', 'visibility', 'none')
    }
  }
  
  /**
   * Show provincial boundaries
   */
  showProvincialBoundaries() {
    if (this.map.getLayer('provincial-boundaries-line')) {
      this.map.setLayoutProperty('provincial-boundaries-line', 'visibility', 'visible')
    }
    if (this.map.getLayer('provincial-boundaries-fill')) {
      this.map.setLayoutProperty('provincial-boundaries-fill', 'visibility', 'visible')
    }
  }
  
  /**
   * Hide provincial boundaries
   */
  hideProvincialBoundaries() {
    if (this.map.getLayer('provincial-boundaries-line')) {
      this.map.setLayoutProperty('provincial-boundaries-line', 'visibility', 'none')
    }
    if (this.map.getLayer('provincial-boundaries-fill')) {
      this.map.setLayoutProperty('provincial-boundaries-fill', 'visibility', 'none')
    }
  }
  
  /**
   * Show AQI circles layer
   */
  showHeatmap() {
    if (this.map.getLayer('aqi-circles')) {
      this.map.setLayoutProperty('aqi-circles', 'visibility', 'visible')
    }
  }
  
  /**
   * Hide AQI circles layer
   */
  hideHeatmap() {
    if (this.map.getLayer('aqi-circles')) {
      this.map.setLayoutProperty('aqi-circles', 'visibility', 'none')
    }
  }
}