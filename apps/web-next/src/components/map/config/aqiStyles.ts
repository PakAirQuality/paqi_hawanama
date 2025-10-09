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

/**
 * Convert PM2.5 concentration to AQI value for color coding
 * Based on EPA AQI breakpoints for PM2.5 (24-hour average)
 */
export function pm25ToAQI(pm25: number): number {
  if (pm25 <= 0) return 0
  if (pm25 <= 12.0) return Math.round((50 / 12.0) * pm25)
  if (pm25 <= 35.4) return Math.round(((100 - 51) / (35.4 - 12.1)) * (pm25 - 12.1) + 51)
  if (pm25 <= 55.4) return Math.round(((150 - 101) / (55.4 - 35.5)) * (pm25 - 35.5) + 101)
  if (pm25 <= 150.4) return Math.round(((200 - 151) / (150.4 - 55.5)) * (pm25 - 55.5) + 151)
  if (pm25 <= 250.4) return Math.round(((300 - 201) / (250.4 - 150.5)) * (pm25 - 150.5) + 201)
  return Math.round(((500 - 301) / (500.4 - 250.5)) * (pm25 - 250.5) + 301)
}

/**
 * Get AQI color based on PM2.5 value
 */
export function getAQIColorByPM25(pm25: number): string {
  const aqi = pm25ToAQI(pm25)
  return getAQIColorByValue(aqi)
}