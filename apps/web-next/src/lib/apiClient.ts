const BASE_URL = process.env.NEXT_PUBLIC_API_BASE || 'https://hawanama-152782825429.asia-south1.run.app/api'

export interface StationCurrent {
  station_id: string
  name: string
  aqi_us: number
  main_pollutant: string
  main_value: number
  main_units: string
  temp_c: number
  humidity: number
  wind_speed_kmh: number
  wind_direction: number
  pressure_mbar: number
  last_update: string
}

export interface StationHistory {
  timestamp_utc: string
  timestamp_pk: string
  timestamp: string  // Keep for backward compatibility
  aqi_us: number | null
  p2_conc?: number
}

export interface StationPM25History {
  timestamp_utc: string
  timestamp_pk: string
  timestamp: string  // Keep for backward compatibility
  pm25: number | null
}

export interface AQICategory {
  min: number
  max: number
  label: string
  color: string
  text_color: string
}

export const apiClient = {
  async getStationCurrent(stationId: string, signal?: AbortSignal): Promise<StationCurrent> {
    const url = `${BASE_URL}/v1/dashboard/stations/${stationId}/current`
    console.log('[apiClient] Fetching station current from:', url)
    
    try {
      const response = await fetch(url, { signal })
      console.log('[apiClient] Station current response status:', response.status)
      
      if (!response.ok) {
        const errorText = await response.text()
        console.error('[apiClient] Station current error response:', errorText)
        throw new Error(`Failed to fetch station current data: ${response.status} ${response.statusText}`)
      }
      
      const data = await response.json()
      console.log('[apiClient] Station current data received:', data)
      return data
    } catch (error) {
      console.error('[apiClient] Failed to fetch station current data:', error)
      throw error
    }
  },

  async getStationHistory(stationId: string, hours = 24, signal?: AbortSignal): Promise<StationHistory[]> {
    const url = `${BASE_URL}/v1/dashboard/stations/${stationId}/history?hours=${hours}`
    console.log('[apiClient] Fetching station history from:', url)
    
    try {
      const response = await fetch(url, { signal })
      console.log('[apiClient] Station history response status:', response.status)
      
      if (!response.ok) {
        const errorText = await response.text()
        console.error('[apiClient] Station history error response:', errorText)
        throw new Error(`Failed to fetch station history: ${response.status} ${response.statusText}`)
      }
      
      const data = await response.json()
      console.log('[apiClient] Station history data received:', data?.length, 'points')
      return Array.isArray(data) ? data : []
    } catch (error) {
      console.error('[apiClient] Failed to fetch station history:', error)
      throw error
    }
  },

  async getStationPM25History(stationId: string, hours = 24, signal?: AbortSignal): Promise<StationPM25History[]> {
    const url = `${BASE_URL}/v1/dashboard/stations/${stationId}/history/pm25?hours=${hours}`
    console.log('[apiClient] Fetching station PM2.5 history from:', url)
    
    try {
      const response = await fetch(url, { signal })
      console.log('[apiClient] Station PM2.5 history response status:', response.status)
      
      if (!response.ok) {
        const errorText = await response.text()
        console.error('[apiClient] Station PM2.5 history error response:', errorText)
        throw new Error(`Failed to fetch station PM2.5 history: ${response.status} ${response.statusText}`)
      }
      
      const data = await response.json()
      console.log('[apiClient] Station PM2.5 history data received:', data?.length, 'points')
      return Array.isArray(data) ? data : []
    } catch (error) {
      console.error('[apiClient] Failed to fetch station PM2.5 history:', error)
      throw error
    }
  },

  async getAQICategories(signal?: AbortSignal): Promise<AQICategory[]> {
    const response = await fetch(`${BASE_URL}/v1/meta/aqi-categories`, { signal })
    if (!response.ok) {
      throw new Error(`Failed to fetch AQI categories: ${response.status} ${response.statusText}`)
    }
    
    const data = await response.json()
    // Convert backend format to frontend format
    const categories = data.us_epa
    return [
      { min: categories.good.range[0], max: categories.good.range[1], label: 'Good', color: categories.good.color, text_color: '#000000' },
      { min: categories.moderate.range[0], max: categories.moderate.range[1], label: 'Moderate', color: categories.moderate.color, text_color: '#000000' },
      { min: categories.unhealthy_for_sensitive_groups.range[0], max: categories.unhealthy_for_sensitive_groups.range[1], label: 'Unhealthy for Sensitive Groups', color: categories.unhealthy_for_sensitive_groups.color, text_color: '#ffffff' },
      { min: categories.unhealthy.range[0], max: categories.unhealthy.range[1], label: 'Unhealthy', color: categories.unhealthy.color, text_color: '#ffffff' },
      { min: categories.very_unhealthy.range[0], max: categories.very_unhealthy.range[1], label: 'Very Unhealthy', color: categories.very_unhealthy.color, text_color: '#ffffff' },
      { min: categories.hazardous.range[0], max: categories.hazardous.range[1], label: 'Hazardous', color: categories.hazardous.color, text_color: '#ffffff' },
      { min: 501, max: 999999, label: 'Beyond Index', color: categories.hazardous.color, text_color: '#ffffff' },
    ]
  },
}