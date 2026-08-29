import type mapboxglType from 'mapbox-gl'
import { createRoot } from 'react-dom/client'
import AqiMarker from '../components/AqiMarker'
import React from 'react'

/**
 * Service for managing map layers
 */
export class MapLayerService {
  private markerElements: Map<string, { element: HTMLElement, marker: mapboxglType.Marker, feature: any }> = new Map()
  private supercluster: any = null
  private isTransitioning: boolean = false
  private transitionTimeout: NodeJS.Timeout | null = null
  private animationQueue: string[] = []
  private lastZoom: number = 0
  private debounceTimeout: NodeJS.Timeout | null = null

  constructor(private map: mapboxglType.Map, private mapboxgl: typeof mapboxglType, private openStation?: (id: string) => void) {}

  /**
   * Initialize all map layers
   */
  initializeLayers() {
    // No overlay layers needed currently
  }

  /**
   * Update markers based on cluster/point data with smooth transitions
   */
  updateMarkers(clusterData: any[], pointData: any[], supercluster?: any) {
    // Store supercluster instance for cluster expansion
    if (supercluster) {
      this.supercluster = supercluster
    }

    // Debounce rapid updates during zoom/pan
    if (this.debounceTimeout) {
      clearTimeout(this.debounceTimeout)
    }

    this.debounceTimeout = setTimeout(() => {
      this.performMarkerUpdate(clusterData, pointData)
    }, 30) // Faster response for smoother experience
  }

  /**
   * Perform the actual marker update with smooth transitions
   */
  private performMarkerUpdate(clusterData: any[], pointData: any[]) {
    const currentZoom = this.map.getZoom()
    const zoomChanged = Math.abs(currentZoom - this.lastZoom) > 0.1
    this.lastZoom = currentZoom

    // Get current and new marker sets
    const currentMarkerIds = new Set(this.markerElements.keys())
    const newFeatureMap = new Map<string, { feature: any, isCluster: boolean }>()
    
    // Build new feature map
    clusterData.forEach(cluster => {
      const id = `cluster-${cluster.properties.cluster_id}`
      newFeatureMap.set(id, { feature: cluster, isCluster: true })
    })
    
    pointData.forEach(point => {
      const id = `point-${point.properties.id}`
      newFeatureMap.set(id, { feature: point, isCluster: false })
    })

    const newMarkerIds = new Set(newFeatureMap.keys())

    // Find markers to remove, update, and add
    const toRemove = Array.from(currentMarkerIds).filter(id => !newMarkerIds.has(id))
    const toUpdate = Array.from(currentMarkerIds).filter(id => newMarkerIds.has(id))
    const toAdd = Array.from(newMarkerIds).filter(id => !currentMarkerIds.has(id))

    // Remove markers that are no longer needed with fade out
    toRemove.forEach(markerId => {
      this.fadeOutAndRemoveMarker(markerId)
    })

    // Update existing markers (just position changes)
    toUpdate.forEach(markerId => {
      const { feature } = newFeatureMap.get(markerId)!
      this.updateExistingMarker(markerId, feature)
    })

    // Add new markers with staggered animation
    if (toAdd.length > 0) {
      this.addMarkersWithStaggeredAnimation(toAdd, newFeatureMap, zoomChanged)
    }
  }

  /**
   * Add new markers with staggered animation to prevent screen overrun
   */
  private addMarkersWithStaggeredAnimation(
    markerIds: string[], 
    featureMap: Map<string, { feature: any, isCluster: boolean }>,
    immediate: boolean = false
  ) {
    const markerCount = markerIds.length
    const currentZoom = this.map.getZoom()
    
    // Detect if we're in individual points mode (zoom 6+) with many markers
    const isIndividualPointsMode = currentZoom > 5 && markerCount > 15
    
    // Use much longer delays for zoom 6+ individual points mode
    let baseDelay: number
    let maxTotalDelay: number
    
    if (isIndividualPointsMode) {
      baseDelay = 150 // Much slower for individual points
      maxTotalDelay = 10000 // 10 seconds total for very smooth flow
    } else {
      baseDelay = 80 // Normal speed for clusters
      maxTotalDelay = 2500
    }
    
    // Calculate optimal delay to fit within max time
    const optimalDelay = markerCount > 0 ? Math.min(baseDelay, maxTotalDelay / markerCount) : baseDelay
    
    console.log('🎭 Staggered animation:', {
      markerCount,
      currentZoom: currentZoom.toFixed(1),
      isIndividualPointsMode,
      optimalDelay: optimalDelay.toFixed(1) + 'ms',
      totalDuration: (markerCount * optimalDelay).toFixed(0) + 'ms'
    })

    markerIds.forEach((markerId, index) => {
      const delay = index * optimalDelay
      
      setTimeout(() => {
        const featureData = featureMap.get(markerId)
        if (featureData && !this.markerElements.has(markerId)) {
          const { feature, isCluster } = featureData
          this.addMarker(feature, isCluster, 0) // No additional delay since setTimeout handles it
        }
      }, delay)
    })
  }

  /**
   * Set transition state to prevent marker flicker (simplified to avoid disappearing markers)
   */
  private setTransitionState(isTransitioning: boolean) {
    this.isTransitioning = isTransitioning
    // Removed logic that adds/removes classes that might cause markers to disappear
  }

  /**
   * Update existing marker position smoothly
   */
  private updateExistingMarker(markerId: string, feature: any) {
    const markerData = this.markerElements.get(markerId)
    if (markerData) {
      const [lng, lat] = feature.geometry.coordinates
      const oldFeature = markerData.feature
      const [oldLng, oldLat] = oldFeature.geometry.coordinates
      
      // Add persistent class to ensure marker stays visible
      const container = markerData.element.querySelector('.aqi-marker-container')
      if (container) {
        container.classList.add('persistent')
        container.classList.remove('fade-out', 'stable')
      }
      
      // Only update position if it has changed significantly
      if (Math.abs(lng - oldLng) > 0.0001 || Math.abs(lat - oldLat) > 0.0001) {
        markerData.marker.setLngLat([lng, lat])
        markerData.feature = feature
      }
    }
  }

  /**
   * Fade out and remove marker smoothly (simplified to prevent unintended disappearing)
   */
  private fadeOutAndRemoveMarker(markerId: string) {
    const markerData = this.markerElements.get(markerId)
    if (markerData) {
      // Immediate removal without fade animation to prevent touch-induced disappearing
      markerData.marker.remove()
      this.markerElements.delete(markerId)
    }
  }


  /**
   * Add a single marker (cluster or point) with optional animation delay
   */
  private addMarker(feature: any, isCluster: boolean, customDelay: number = 0) {
    const { geometry, properties } = feature
    const [lng, lat] = geometry.coordinates
    
    // Debug the properties to see what data we have
    console.log('🔍 Adding marker with properties:', {
      isCluster,
      properties,
      availableProps: Object.keys(properties)
    })
    
    // Create marker element
    const el = document.createElement('div')
    
    // Add click handlers
    if (isCluster) {
      // Cluster click handler - zoom to expand cluster
      el.addEventListener('click', (e) => {
        e.stopPropagation() // Prevent map click
        console.log('🔍 Cluster clicked with', properties.point_count, 'points')
        this.expandCluster(properties.cluster_id, [lng, lat])
      })
    } else if (properties.id && this.openStation) {
      // Individual station click handler
      el.addEventListener('click', (e) => {
        e.stopPropagation() // Prevent map click
        console.log('🔍 Marker clicked for station:', properties.id)
        this.openStation!(String(properties.id))
      })
    }
    
    // Create React root and render AqiMarker
    const root = createRoot(el)
    root.render(
      React.createElement(AqiMarker, {
        aqi: properties.aqi || properties.aqi_raw,
        avg_aqi: properties.avg_aqi,
        point_count: properties.point_count,
        isCluster,
        animationDelay: customDelay
      })
    )

    // Create Mapbox marker
    const marker = new this.mapboxgl.Marker(el)
      .setLngLat([lng, lat])
      .addTo(this.map)

    // Store marker for cleanup with feature data
    const markerId = isCluster ? `cluster-${properties.cluster_id}` : `point-${properties.id}`
    this.markerElements.set(markerId, { element: el, marker, feature })
  }

  /**
   * Clear all markers
   */
  private clearMarkers() {
    this.markerElements.forEach(({ marker }) => {
      marker.remove()
    })
    this.markerElements.clear()
  }

  /**
   * Expand a cluster by zooming in
   */
  private expandCluster(clusterId: number, coordinates: [number, number]) {
    if (!this.supercluster) {
      console.warn('🗺️ No supercluster instance available for cluster expansion')
      return
    }

    try {
      // Get the expansion zoom level for this cluster
      const expansionZoom = this.supercluster.getClusterExpansionZoom(clusterId)
      console.log('🗺️ Expanding cluster', clusterId, 'to zoom level', expansionZoom)
      
      // Zoom to the cluster location with the expansion zoom level
      this.map.easeTo({
        center: coordinates,
        zoom: expansionZoom,
        duration: 600
      })
    } catch (error) {
      console.error('🗺️ Error expanding cluster:', error)
      // Fallback: just zoom in by 2 levels
      this.map.easeTo({
        center: coordinates,
        zoom: Math.min(this.map.getZoom() + 2, 18),
        duration: 600
      })
    }
  }

  /**
   * Cleanup method
   */
  cleanup() {
    if (this.transitionTimeout) {
      clearTimeout(this.transitionTimeout)
      this.transitionTimeout = null
    }
    if (this.debounceTimeout) {
      clearTimeout(this.debounceTimeout)
      this.debounceTimeout = null
    }
    this.clearMarkers()
  }
}