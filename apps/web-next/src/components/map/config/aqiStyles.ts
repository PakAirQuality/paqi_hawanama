/**
 * AQI color schemes and styling logic
 * Climate TRACE-style AQI colors (optimized for light relief backgrounds)
 */

export const AQI_COLORS = {
  good: 'rgba(110, 204, 57, 1)',             // Green from your cluster-small div
  moderate: 'rgba(240, 194, 12, 1)',         // Yellow from your cluster-medium div  
  unhealthy_sensitive: 'rgba(241, 128, 23, 1)', // Orange from your cluster-large div
  unhealthy: 'rgba(239, 120, 85, 1)',        // More red, slightly darker shade
  very_unhealthy: '#a070b5',                  // Purple for very unhealthy
  hazardous: '#991b1b',                       // Dark red for hazardous
  fallback: '#6b7280'                         // Gray
} as const

export type AQICategory = keyof typeof AQI_COLORS

/**
 * Get AQI color based on category
 */
export function getAQIColor(category?: string): string {
  if (!category || !(category in AQI_COLORS)) {
    return AQI_COLORS.fallback
  }
  return AQI_COLORS[category as AQICategory]
}

/**
 * Get AQI color based on numeric value (for charts and other components)
 */
export function getAQIColorByValue(aqi: number): string {
  if (aqi === 0) return '#FFFFFFE6' // Off-white for no reading
  if (aqi <= 50) return AQI_COLORS.good
  if (aqi <= 100) return AQI_COLORS.moderate
  if (aqi <= 150) return AQI_COLORS.unhealthy_sensitive
  if (aqi <= 200) return AQI_COLORS.unhealthy
  if (aqi <= 300) return AQI_COLORS.very_unhealthy
  return AQI_COLORS.hazardous
}

/**
 * Get AQI category from numeric value
 */
export function getAQICategory(aqi?: number): AQICategory {
  if (!aqi || aqi <= 0) return 'fallback'
  if (aqi <= 50) return 'good'
  if (aqi <= 100) return 'moderate'
  if (aqi <= 150) return 'unhealthy_sensitive'
  if (aqi <= 200) return 'unhealthy'
  if (aqi <= 300) return 'very_unhealthy'
  return 'hazardous'
}

/**
 * Get AQI category label with special handling for 0 values
 */
export function getAQICategoryLabel(aqi: number, categoryLabel: string): string {
  if (aqi === 0) return 'No Reading'
  return categoryLabel
}


