import type mapboxglType from 'mapbox-gl'
import type Supercluster from 'supercluster'
import { CLUSTER_BEHAVIOR } from '../config/clusterConfig'

/**
 * Service for managing map event handlers
 */
export class MapEventService {
  private cleanupFunctions: (() => void)[] = []
  private supercluster: Supercluster | null = null
  private clusterLockRef: React.MutableRefObject<number>
  private mapboxgl: typeof mapboxglType
  private openStation: (stationId: string) => void

  constructor(
    private map: mapboxglType.Map, 
    openStation: (id: string) => void, 
    supercluster?: Supercluster | null, 
    clusterLockRef?: React.MutableRefObject<number>, 
    mapboxgl?: typeof mapboxglType
  ) {
    this.openStation = openStation
    this.supercluster = supercluster || null
    this.clusterLockRef = clusterLockRef || { current: CLUSTER_BEHAVIOR.lockZoom }
    this.mapboxgl = mapboxgl!
  }

  /**
   * Initialize all event handlers
   */
  initializeEventHandlers() {
    this.addNavigationControls()
    this.addStationClickHandlers()
    this.addClusterClickHandlers()
    this.addCursorHandlers()
    this.addProvincialBoundaryHandlers()
  }

  /**
   * Add navigation controls
   */
  private addNavigationControls() {
    this.map.addControl(new this.mapboxgl.NavigationControl(), 'top-right')
  }

  /**
   * Add station click handlers - disabled since we're using markers instead of layers
   */
  private addStationClickHandlers() {
    // Station clicks are now handled directly on marker elements
    // No layer-based event handlers needed
    console.log('🗺️ Station click handlers disabled - using marker-based clicks')
    
    this.cleanupFunctions.push(() => {
      // No cleanup needed since no events are registered
    })
  }

  /**
   * Add cluster click handlers (DISABLED - clusters are hidden, using heatmap instead)
   */
  private addClusterClickHandlers() {
    // Cluster click handlers disabled since cluster layers are hidden
    // This prevents unwanted zoom behavior when clicking on stations
    console.log('🗺️ Cluster click handlers disabled - using heatmap instead of clusters')
    
    // Keep empty cleanup function for consistency
    this.cleanupFunctions.push(() => {
      // No cleanup needed since no events are registered
    })
  }

  /**
   * Add cursor change handlers
   */
  private addCursorHandlers() {
    const setPointer = () => { this.map.getCanvas().style.cursor = 'pointer' }
    const resetCursor = () => { this.map.getCanvas().style.cursor = '' }

    // Only handle provincial boundaries since markers handle their own cursor changes
    const layers = ['provincial-boundaries-fill', 'provincial-boundaries-line', 'provincial-boundaries-glow']
    
    layers.forEach(layer => {
      // Use timeout for provincial boundary layers to ensure they're loaded
      setTimeout(() => {
        if (this.map.getLayer(layer)) {
          this.map.on('mouseenter', layer, setPointer)
          this.map.on('mouseleave', layer, resetCursor)
        }
      }, 2000)
    })

    this.cleanupFunctions.push(() => {
      if (this.map && !this.map._removed) {
        layers.forEach(layer => {
          if (this.map.getLayer(layer)) {
            this.map.off('mouseenter', layer, setPointer)
            this.map.off('mouseleave', layer, resetCursor)
          }
        })
      }
    })
  }


  /**
   * Add provincial boundary interaction handlers
   */
  private addProvincialBoundaryHandlers() {
    let hoveredProvinceId: string | null = null

    const handleProvinceClick = (e: mapboxglType.MapMouseEvent) => {
      // Check if click happened on a marker element - if so, don't handle province click
      const clickedElement = e.originalEvent.target as HTMLElement
      if (clickedElement?.closest('.aqi-marker-container')) {
        console.log('🗺️ Click was on station marker, skipping province zoom')
        return
      }
      
      const feature = e.features?.[0]
      if (!feature) return
      
      const geometry = feature.geometry as any
      const provinceName = feature.properties?.shapeName || feature.properties?.name || feature.properties?.NAME
      
      if (geometry && provinceName) {
        console.log('🗺️ Provincial boundary clicked:', provinceName)
        
        // Calculate bounds of the province
        let bounds = new this.mapboxgl.LngLatBounds()
        
        if (geometry.type === 'Polygon') {
          geometry.coordinates[0].forEach((coord: [number, number]) => {
            bounds.extend(coord)
          })
        } else if (geometry.type === 'MultiPolygon') {
          geometry.coordinates.forEach((polygon: [number, number][][]) => {
            polygon[0].forEach((coord: [number, number]) => {
              bounds.extend(coord)
            })
          })
        }
        
        // Fit map to province bounds with smooth animation
        this.map.fitBounds(bounds, {
          padding: { top: 80, bottom: 80, left: 80, right: 80 },
          duration: 1200,
          maxZoom: 9, // Good detail level for provinces
          easing: (t: number) => t * (2 - t) // Smooth easing
        })
      }
    }

    const handleProvinceHover = (e: mapboxglType.MapMouseEvent) => {
      this.map.getCanvas().style.cursor = 'pointer'
      
      const feature = e.features?.[0]
      if (feature?.id) {
        // Remove hover state from previous province
        if (hoveredProvinceId !== null) {
          this.map.setFeatureState(
            { source: 'provincial-boundaries', id: hoveredProvinceId },
            { hover: false }
          )
        }
        
        // Add hover state to current province
        hoveredProvinceId = feature.id as string
        this.map.setFeatureState(
          { source: 'provincial-boundaries', id: hoveredProvinceId },
          { hover: true }
        )
      }
    }

    const handleProvinceHoverOut = () => {
      this.map.getCanvas().style.cursor = ''
      
      // Remove hover state
      if (hoveredProvinceId !== null) {
        this.map.setFeatureState(
          { source: 'provincial-boundaries', id: hoveredProvinceId },
          { hover: false }
        )
        hoveredProvinceId = null
      }
    }
    
    // Add event listeners with timeout to ensure layers are loaded
    const layersToHandle = ['provincial-boundaries-fill', 'provincial-boundaries-line', 'provincial-boundaries-glow']
    
    setTimeout(() => {
      layersToHandle.forEach(layerName => {
        if (this.map.getLayer(layerName)) {
          this.map.on('click', layerName, handleProvinceClick)
          this.map.on('mouseenter', layerName, handleProvinceHover)
          this.map.on('mouseleave', layerName, handleProvinceHoverOut)
        }
      })
    }, 2000) // Wait for provincial layers to be initialized

    this.cleanupFunctions.push(() => {
      if (this.map && !this.map._removed) {
        layersToHandle.forEach(layerName => {
          if (this.map.getLayer(layerName)) {
            this.map.off('click', layerName, handleProvinceClick)
            this.map.off('mouseenter', layerName, handleProvinceHover)
            this.map.off('mouseleave', layerName, handleProvinceHoverOut)
          }
        })
      }
    })
  }

  /**
   * Update supercluster instance
   */
  updateSupercluster(sc: Supercluster | null) { 
    this.supercluster = sc 
  }

  /**
   * Clean up all event handlers
   */
  cleanup() { 
    this.cleanupFunctions.forEach(fn => fn())
    this.cleanupFunctions = [] 
  }
}