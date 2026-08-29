/**
 * Geographic coordinate utility functions
 */

/**
 * Calculate distance between two coordinates in kilometers
 */
export function calculateDistance(
  lat1: number, lng1: number, 
  lat2: number, lng2: number
): number {
  const R = 6371 // Earth's radius in km
  const dLat = toRadians(lat2 - lat1)
  const dLng = toRadians(lng2 - lng1)
  
  const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos(toRadians(lat1)) * Math.cos(toRadians(lat2)) *
    Math.sin(dLng / 2) * Math.sin(dLng / 2)
  
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
  return R * c
}

/**
 * Convert degrees to radians
 */
function toRadians(degrees: number): number {
  return degrees * (Math.PI / 180)
}

/**
 * Calculate bounding box for a set of coordinates
 */
export function calculateBounds(coordinates: [number, number][]): {
  north: number
  south: number
  east: number
  west: number
} {
  if (coordinates.length === 0) {
    throw new Error('Cannot calculate bounds for empty coordinate array')
  }
  
  let north = coordinates[0][1]
  let south = coordinates[0][1]
  let east = coordinates[0][0]
  let west = coordinates[0][0]
  
  for (const [lng, lat] of coordinates) {
    north = Math.max(north, lat)
    south = Math.min(south, lat)
    east = Math.max(east, lng)
    west = Math.min(west, lng)
  }
  
  return { north, south, east, west }
}

/**
 * Check if a coordinate is within South Asia's approximate bounds
 */
export function isWithinSouthAsia(lat: number, lng: number): boolean {
  // Approximate bounds of South Asia (Pakistan, India, Bangladesh, Nepal, Sri Lanka)
  const bounds = {
    north: 37.1,
    south: 5.9,
    east: 92.7,
    west: 60.9
  }

  return lat >= bounds.south && lat <= bounds.north &&
         lng >= bounds.west && lng <= bounds.east
}

/** @deprecated Use isWithinSouthAsia instead */
export const isWithinPakistan = isWithinSouthAsia

/**
 * Normalize longitude to [-180, 180] range
 */
export function normalizeLongitude(lng: number): number {
  while (lng > 180) lng -= 360
  while (lng < -180) lng += 360
  return lng
}

/**
 * Normalize latitude to [-90, 90] range
 */
export function normalizeLatitude(lat: number): number {
  return Math.max(-90, Math.min(90, lat))
}