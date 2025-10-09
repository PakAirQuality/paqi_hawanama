import type { Station } from '@/lib/api'
import type { LngLatBounds } from 'mapbox-gl'

/**
 * Service for filtering stations based on various criteria
 */
export class FilterService {
  /**
   * Filter stations based on zoom level
   * Hide grey stations (no AQI data) at low zoom levels
   */
  static filterByZoom(stations: Station[], zoom: number): Station[] {
    if (zoom >= 8) return stations // Show all stations at high zoom
    
    // At low zoom, hide stations without AQI data (grey stations)
    return stations.filter(station => 
      station.aqi_category && 
      station.aqi_category !== '' && 
      station.aqi_category !== null
    )
  }

  /**
   * Filter stations within map bounds
   */
  static filterByBounds(stations: Station[], bounds: LngLatBounds): Station[] {
    const west = bounds.getWest()
    const east = bounds.getEast()
    const south = bounds.getSouth()
    const north = bounds.getNorth()
    
    return stations.filter(station => {
      if (station.latitude == null || station.longitude == null) return false
      
      return station.latitude >= south && 
             station.latitude <= north &&
             station.longitude >= west && 
             station.longitude <= east
    })
  }

  /**
   * Filter stations by city
   */
  static filterByCity(stations: Station[], cityName: string): Station[] {
    const normalizedCity = cityName.toLowerCase().trim()
    
    return stations.filter(station => 
      station.city?.toLowerCase().trim() === normalizedCity
    )
  }

  /**
   * Filter stations by data quality
   */
  static filterByQuality(
    stations: Station[], 
    includeQualityLevels: ('good' | 'suspect' | 'bad' | 'unknown')[] = ['good']
  ): Station[] {
    return stations.filter(station => 
      station.qc_flag && includeQualityLevels.includes(station.qc_flag)
    )
  }

  /**
   * Filter stations with recent data (within specified hours)
   */
  static filterByRecency(stations: Station[], maxHoursOld: number = 24): Station[] {
    return stations.filter(station => {
      if (!station.hours_since_update) return false
      return station.hours_since_update <= maxHoursOld
    })
  }

  /**
   * Filter stations with valid coordinates
   */
  static filterValidCoordinates(stations: Station[]): Station[] {
    return stations.filter(station => 
      station.latitude != null && 
      station.longitude != null &&
      !Number.isNaN(station.latitude) && 
      !Number.isNaN(station.longitude) &&
      station.latitude >= -90 && 
      station.latitude <= 90 &&
      station.longitude >= -180 && 
      station.longitude <= 180
    )
  }

  /**
   * Apply multiple filters in sequence
   */
  static applyFilters(
    stations: Station[],
    filters: {
      zoom?: number
      bounds?: LngLatBounds
      city?: string
      quality?: ('good' | 'suspect' | 'bad' | 'unknown')[]
      maxHoursOld?: number
      requireValidCoordinates?: boolean
    }
  ): Station[] {
    let filtered = [...stations]
    
    if (filters.requireValidCoordinates !== false) {
      filtered = this.filterValidCoordinates(filtered)
    }
    
    if (filters.zoom !== undefined) {
      filtered = this.filterByZoom(filtered, filters.zoom)
    }
    
    if (filters.bounds) {
      filtered = this.filterByBounds(filtered, filters.bounds)
    }
    
    if (filters.city) {
      filtered = this.filterByCity(filtered, filters.city)
    }
    
    if (filters.quality) {
      filtered = this.filterByQuality(filtered, filters.quality)
    }
    
    if (filters.maxHoursOld !== undefined) {
      filtered = this.filterByRecency(filtered, filters.maxHoursOld)
    }
    
    return filtered
  }
}