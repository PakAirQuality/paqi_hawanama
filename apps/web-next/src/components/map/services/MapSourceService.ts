import type mapboxglType from 'mapbox-gl'
import type { Station } from '@/lib/api'

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