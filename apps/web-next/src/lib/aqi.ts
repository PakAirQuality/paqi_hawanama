import type { AQICategory } from './apiClient'

export function getAQICategory(aqi: number, categories: AQICategory[]): AQICategory {
  if (!Array.isArray(categories)) {
    throw new Error('Categories must be an array')
  }
  const category = categories.find(cat => aqi >= cat.min && aqi <= cat.max)
  if (!category) {
    throw new Error(`No AQI category found for value ${aqi}`)
  }
  return category
}

export function formatPollutant(pollutant: string): string {
  const pollutantMap: Record<string, string> = {
    pm25: 'PM2.5',
    pm10: 'PM10',
    o3: 'O₃',
    no2: 'NO₂',
    so2: 'SO₂',
    co: 'CO',
  }
  return pollutantMap[pollutant.toLowerCase()] || pollutant.toUpperCase()
}

export function getWindDirection(degrees: number): string {
  const directions = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
  const index = Math.round(degrees / 22.5) % 16
  return directions[index]
}