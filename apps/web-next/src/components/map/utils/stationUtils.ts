import type { Station } from '@/lib/api'

/**
 * Transform stations to GeoJSON points, deduplicating by coordinates
 */
export function stationsToGeoJSONPoints(stations: Station[]) {
  console.log('🔍 stationsToGeoJSONPoints: Input', stations?.length || 0, 'stations')
  if (!stations?.length) return []
  
  const byCoord = new globalThis.Map<string, Station>()
  let validStations = 0
  let invalidStations = 0
  
  for (const station of stations) {
    if (station.latitude == null || station.longitude == null || 
        Number.isNaN(station.latitude) || Number.isNaN(station.longitude)) {
      invalidStations++
      console.log('🔍 Invalid station coordinates:', station.name, station.latitude, station.longitude)
      continue
    }
    
    validStations++
    const key = `${Math.round(station.longitude * 1e5)},${Math.round(station.latitude * 1e5)}`
    if (!byCoord.has(key)) {
      byCoord.set(key, station)
    }
  }
  
  const result = Array.from(byCoord.values()).map(station => ({
    type: 'Feature' as const,
    geometry: { 
      type: 'Point' as const, 
      coordinates: [station.longitude, station.latitude] 
    },
    properties: { ...station, stationId: station.id }
  }))
  
  console.log('🔍 stationsToGeoJSONPoints: Results -', {
    input: stations.length,
    valid: validStations,
    invalid: invalidStations,
    deduplicated: byCoord.size,
    output: result.length
  })
  
  return result
}

/**
 * Calculate centroid of stations
 */
export function calculateStationsCentroid(stations: Station[]): [number, number] | null {
  const validStations = stations.filter(s => 
    s.latitude != null && s.longitude != null && 
    !Number.isNaN(s.latitude) && !Number.isNaN(s.longitude)
  )
  
  if (validStations.length === 0) return null
  
  const avgLng = validStations.reduce((sum, s) => sum + s.longitude, 0) / validStations.length
  const avgLat = validStations.reduce((sum, s) => sum + s.latitude, 0) / validStations.length
  
  return [avgLng, avgLat]
}

/**
 * Filter stations by zoom level (hide grey stations at low zoom)
 */
export function filterStationsByZoom(stations: Station[], zoom: number): Station[] {
  if (zoom >= 8) return stations // Show all stations at high zoom
  
  // At low zoom, hide stations without AQI data (grey stations)
  return stations.filter(station => 
    station.aqi_category && 
    station.aqi_category !== '' && 
    station.aqi_category !== null
  )
}