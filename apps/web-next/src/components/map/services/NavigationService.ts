/**
 * Service for handling map navigation and routing
 */
export class NavigationService {
  /**
   * Navigate to city page based on city name
   */
  static navigateToCity(cityName: string): void {
    const citySlug = this.createCitySlug(cityName)
    window.location.href = `/city/${citySlug}`
  }

  /**
   * Navigate to station page based on station ID
   */
  static navigateToStation(stationId: string | number): void {
    window.location.href = `/station/${stationId}`
  }

  /**
   * Create URL-friendly slug from city name
   */
  static createCitySlug(cityName: string): string {
    return cityName
      .toLowerCase()
      .trim()
      .replace(/\s+/g, '-')           // Replace spaces with hyphens
      .replace(/[()]/g, '')           // Remove parentheses
      .replace(/-merged$/i, '')       // Remove "-merged" suffix
      .replace(/[^a-z0-9-]/g, '')     // Remove special characters
      .replace(/-+/g, '-')            // Replace multiple hyphens with single
      .replace(/^-|-$/g, '')          // Remove leading/trailing hyphens
  }

  /**
   * Parse city slug back to readable name
   */
  static parseCitySlug(slug: string): string {
    return slug
      .split('-')
      .map(word => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ')
  }

  /**
   * Handle boundary click navigation with fallback logic
   */
  static handleBoundaryClick(properties: Record<string, any>): boolean {
    // Primary: Use CITY_NAME if available
    if (properties?.CITY_NAME) {
      const cityName = properties.CITY_NAME.toLowerCase().trim()
      console.log('🗺️ Boundary clicked for city:', cityName)
      this.navigateToCity(cityName)
      return true
    }
    
    // Fallback: Infer from UC name
    if (properties?.UC) {
      const ucName = properties.UC.toLowerCase().trim()
      console.log('🗺️ UC boundary clicked (fallback):', ucName)
      
      // Simple fallback mapping - extract city name from UC
      const cityName = ucName
        .replace(/\s+/g, '-')
        .replace(/[()]/g, '')
        .replace(/-merged$/i, '')
      
      this.navigateToCity(cityName)
      return true
    }
    
    console.warn('🗺️ Boundary click: No valid city identifier found', properties)
    return false
  }

  /**
   * Check if click target should be handled as boundary navigation
   * Returns false if station/cluster is at the same location
   */
  static shouldHandleBoundaryClick(
    map: any, 
    clickPoint: { x: number; y: number }
  ): boolean {
    // Check if a station or cluster was also clicked at this point
    const stationFeatures = map.queryRenderedFeatures(clickPoint, {
      layers: ['unclustered-point', 'unclustered-point-text', 'clusters', 'cluster-count']
    })
    
    if (stationFeatures && stationFeatures.length > 0) {
      console.log('🗺️ Station/cluster found at click point, skipping boundary navigation')
      return false
    }
    
    return true
  }

  /**
   * Get appropriate zoom level for different view types
   */
  static getZoomLevel(viewType: 'country' | 'province' | 'city' | 'station'): number {
    switch (viewType) {
      case 'country': return 5
      case 'province': return 7
      case 'city': return 11
      case 'station': return 15
      default: return 5
    }
  }

  /**
   * Generate breadcrumb navigation items
   */
  static generateBreadcrumbs(
    currentPage: 'home' | 'city' | 'station',
    cityName?: string,
    stationName?: string
  ): Array<{ label: string; href?: string }> {
    const breadcrumbs = [
      { label: 'South Asia', href: '/' }
    ]

    if (currentPage === 'city' || currentPage === 'station') {
      if (cityName) {
        const citySlug = this.createCitySlug(cityName)
        breadcrumbs.push({
          label: cityName,
          href: currentPage === 'station' ? `/city/${citySlug}` : undefined
        })
      }
    }

    if (currentPage === 'station' && stationName) {
      breadcrumbs.push({
        label: stationName
      })
    }

    return breadcrumbs
  }
}