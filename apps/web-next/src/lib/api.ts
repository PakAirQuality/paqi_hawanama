const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE || 'https://hawanama-152782825429.asia-south1.run.app/api'

export interface Station {
  id: string  // Now hash-based station ID (primary identifier)
  station_id?: string  // Deprecated: kept for backward compatibility
  name: string
  city_id?: number
  city?: string  // Add city name for boundary filtering
  external_id?: string
  source_id: number
  latitude: number
  longitude: number
  meta_json?: Record<string, unknown>
  source_name?: string
  source_type?: string
  // New AQI and reading fields from stations_vt view
  aqi_raw?: number
  pm25?: number
  pm10?: number
  temp?: number
  hum?: number
  qc_state?: 'OK' | 'SUSPECT' | 'BAD' | 'BACKFILLED'
  last_reading?: string
  aqi_category?: 'good' | 'moderate' | 'unhealthy_sensitive' | 'unhealthy' | 'very_unhealthy' | 'hazardous'
  qc_flag?: 'good' | 'suspect' | 'bad' | 'unknown'
  hours_since_update?: number
}

export interface Reading {
  station_id: number
  ts: string
  pm25?: number
  pm10?: number
  o3?: number
  no2?: number
  so2?: number
  co?: number
  temp?: number
  hum?: number
  aqi_raw?: number
  qc_state?: 'OK' | 'SUSPECT' | 'BAD' | 'BACKFILLED'
  origin?: 'minute' | 'hour' | 'backfill'
  // New meteorological fields
  pressure?: number
  wind_speed?: number
  wind_direction?: number
  weather_icon?: string
  heat_index?: number
}

export interface WeatherData {
  station_id: number
  timestamp: string
  temperature?: number
  humidity?: number
  pressure?: number
  wind_speed?: number
  wind_direction?: number
  weather_icon?: string
  heat_index?: number
}

export interface CombinedData {
  station_id: number
  timestamp: string
  air_quality: {
    aqi?: number
    pm25?: number
    pm10?: number
    o3?: number
    no2?: number
    so2?: number
    co?: number
  }
  weather: {
    temperature?: number
    humidity?: number
    pressure?: number
    wind_speed?: number
    wind_direction?: number
    weather_icon?: string
    heat_index?: number
  }
  metadata: {
    qc_state?: string
    origin?: string
  }
}

export const api = {
  // Health check
  async health() {
    const response = await fetch(`${API_BASE_URL}/health`)
    return response.json()
  },

  // Get dashboard statistics
  async getDashboardStats() {
    const response = await fetch(`${API_BASE_URL}/v1/dashboard/stats`)
    return response.json()
  },

  // Debug endpoint to check database state
  async getDebugInfo() {
    const response = await fetch(`${API_BASE_URL}/v1/dashboard/debug`)
    return response.json()
  },

  // Get all stations
  async getStations(params?: {
    city?: string
    source?: string
    bbox?: string
  }) {
    const query = new URLSearchParams()
    if (params?.city) query.append('city', params.city)
    if (params?.source) query.append('source', params.source)
    if (params?.bbox) query.append('bbox', params.bbox)
    
    const url = `/api/v1/dashboard/stations${query.toString() ? '?' + query.toString() : ''}`
    const response = await fetch(url)
    const data = await response.json()
    
    // Extract stations array from the API response structure
    const stations = data.stations || []
    
    // Filter out stations with readings older than 2 hours
    const twoHoursAgo = new Date(Date.now() - 2 * 60 * 60 * 1000)
    
    return stations.filter((station: any) => {
      if (!station.last_reading) return false
      
      const lastReadingTime = new Date(station.last_reading)
      return lastReadingTime > twoHoursAgo
    })
  },

  // Get single station
  async getStation(id: string | number) {
    const response = await fetch(`${API_BASE_URL}/v1/stations/${id}`)
    return response.json()
  },

  // Get readings
  async getReadings(type: 'minute' | 'hour', params?: {
    station_id?: string | number
    from_time?: string
    to_time?: string
    limit?: number
  }) {
    const query = new URLSearchParams()
    if (params?.station_id) query.append('station_id', params.station_id.toString())
    if (params?.from_time) query.append('from_time', params.from_time)
    if (params?.to_time) query.append('to_time', params.to_time)
    if (params?.limit) query.append('limit', params.limit.toString())
    
    const url = `${API_BASE_URL}/v1/readings/${type}${query.toString() ? '?' + query.toString() : ''}`
    const response = await fetch(url)
    return response.json()
  },

  // Get all cities
  async getCities(limit?: number) {
    const query = new URLSearchParams()
    if (limit) query.append('limit', limit.toString())
    
    const url = `${API_BASE_URL}/v1/cities${query.toString() ? '?' + query.toString() : ''}`
    const response = await fetch(url)
    return response.json()
  },

  // Get single city details
  async getCity(citySlug: string) {
    const response = await fetch(`${API_BASE_URL}/v1/cities/${citySlug}`)
    return response.json()
  },

  // Get city historical data
  async getCityHistorical(citySlug: string, hours: number = 24) {
    const query = new URLSearchParams()
    query.append('hours', hours.toString())
    
    const url = `${API_BASE_URL}/v1/cities/${citySlug}/historical?${query.toString()}`
    const response = await fetch(url)
    return response.json()
  },

  // Get weather data
  async getWeatherData(params?: {
    station_id?: string | number
    from_time?: string
    to_time?: string
    limit?: number
  }) {
    const query = new URLSearchParams()
    if (params?.station_id) query.append('station_id', params.station_id.toString())
    if (params?.from_time) query.append('from_time', params.from_time)
    if (params?.to_time) query.append('to_time', params.to_time)
    if (params?.limit) query.append('limit', params.limit.toString())
    
    const url = `${API_BASE_URL}/v1/readings/weather${query.toString() ? '?' + query.toString() : ''}`
    
    const response = await fetch(url)
    
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`)
    }
    
    const data = await response.json()
    
    // Transform response to match expected format
    return {
      readings: data.weather_data || [],
      count: data.count || 0
    }
  },

  // Get combined air quality and weather data
  async getCombinedData(params?: {
    station_id?: number
    from_time?: string
    to_time?: string
    limit?: number
  }) {
    const query = new URLSearchParams()
    if (params?.station_id) query.append('station_id', params.station_id.toString())
    if (params?.from_time) query.append('from_time', params.from_time)
    if (params?.to_time) query.append('to_time', params.to_time)
    if (params?.limit) query.append('limit', params.limit.toString())

    const url = `${API_BASE_URL}/v1/readings/combined${query.toString() ? '?' + query.toString() : ''}`
    const response = await fetch(url)
    const data = await response.json()

    // Transform response to match expected format
    return {
      readings: data.combined_data || [],
      count: data.count || 0
    }
  }
}

// --- Estimation layer helpers ---

export async function fetchTileDates(limit = 365): Promise<string[]> {
  const res = await fetch(`${API_BASE_URL}/v1/ops/pipeline/tiles/dates?limit=${limit}`)
  if (!res.ok) throw new Error('Failed to fetch tile dates')
  const data = await res.json()
  return (data.dates ?? []) as string[]
}

export interface DailyStation {
  name: string
  city: string
  pm25: number
  lat: number
  lon: number
  valid_hours?: number | null
  complete?: boolean
}

export async function fetchDailyStations(date: string): Promise<DailyStation[]> {
  const res = await fetch(`${API_BASE_URL}/v1/ops/pipeline/stations/daily/${date}?country=Pakistan&min_hours=6`)
  if (!res.ok) throw new Error('Failed to fetch daily stations')
  const data = await res.json()
  return (data.stations ?? []) as DailyStation[]
}

export interface DailyBrief {
  date: string
  narrative: string
  station_count: number
  obs_mean: number | null
  data_sources: { stations: boolean; predictions: boolean; fires: boolean }
}

export async function fetchDailyBrief(date: string): Promise<DailyBrief | null> {
  const res = await fetch(`/api/v1/ops/pipeline/briefs/${date}`)
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`Failed to load brief for ${date}`)
  return res.json()
}