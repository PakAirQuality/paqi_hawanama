// Map actions requested by the copilot. They come from model output, so nothing reaches the map
// or charts until it has passed the checks here.

import type { CopilotAction } from '@/components/analyst-desk/types'

const ACTION_RE = /\{\{ACTION:(\{.*?\})\}\}/g
const PARTIAL_TAG_RE = /\{(\{(A(C(T(I(O(N(:[\s\S]*)?)?)?)?)?)?)?)?$/

const MAX_TEXT = 120
const MAX_HOURS = 2160 // the longest range the trend panel offers (90 days)
const MAX_HORIZON = 14

const text = (v: unknown) => (typeof v === 'string' && v.length > 0 && v.length <= MAX_TEXT ? v : undefined)
const num = (v: unknown, min: number, max: number) =>
  typeof v === 'number' && Number.isFinite(v) && v >= min && v <= max ? v : undefined

/** Returns a clean action with known fields only, or null when it should be ignored. */
export function parseAction(raw: unknown): CopilotAction | null {
  if (typeof raw !== 'object' || raw === null) return null
  const a = raw as Record<string, unknown>

  switch (a.type) {
    case 'zoom_to_city': {
      const city = text(a.city)
      return city ? { type: 'zoom_to_city', city } : null
    }
    case 'zoom_to_station': {
      const lat = num(a.lat, -90, 90)
      const lng = num(a.lng, -180, 180)
      const sensor_id = num(a.sensor_id, 0, Number.MAX_SAFE_INTEGER)
      const station_id = text(a.station_id)
      const station_name = text(a.station_name)
      const hasPlace = lat !== undefined && lng !== undefined
      if (!hasPlace && sensor_id === undefined && !station_id) return null
      return {
        type: 'zoom_to_station',
        ...(hasPlace ? { lat, lng } : {}),
        ...(sensor_id !== undefined ? { sensor_id } : {}),
        ...(station_id ? { station_id } : {}),
        ...(station_name ? { station_name } : {}),
      }
    }
    case 'set_horizon': {
      const horizon = num(a.horizon, 0, MAX_HORIZON)
      return horizon !== undefined && Number.isInteger(horizon) ? { type: 'set_horizon', horizon } : null
    }
    case 'filter_network': {
      if (a.network === null) return { type: 'filter_network', network: null }
      const network = text(a.network)
      return network ? { type: 'filter_network', network } : null
    }
    case 'show_station_trend': {
      const station_id = text(a.station_id)
      if (!station_id) return null
      const hours = num(a.hours, 1, MAX_HOURS)
      const station_name = text(a.station_name)
      return {
        type: 'show_station_trend',
        station_id,
        ...(station_name ? { station_name } : {}),
        ...(hours !== undefined ? { hours } : {}),
      }
    }
    case 'show_trajectory': {
      // Emitted by the server after the trajectory tool ran; the chat fetches the document and draws it
      const lat = num(a.lat, 5, 40)
      const lon = num(a.lon, 55, 95)
      const at = typeof a.at === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?(Z|[+-]\d{2}:\d{2})?$/.test(a.at) ? a.at : undefined
      const hours = num(a.hours, 6, 72)
      const direction = a.direction === 'forward' ? 'forward' : a.direction === 'backward' ? 'backward' : undefined
      if (lat === undefined || lon === undefined || !at || hours === undefined || !direction) return null
      const label = typeof a.label === 'string' && a.label.length > 0 && a.label.length <= 60 ? a.label : undefined
      const engine = typeof a.engine === 'string' && a.engine.length > 0 && a.engine.length <= 60 ? a.engine : undefined
      return {
        type: 'show_trajectory',
        lat, lon, at, hours, direction,
        ...(label ? { label } : {}),
        ...(engine ? { engine } : {}),
      }
    }
    default:
      return null
  }
}

/** Splits action tags out of streamed text, hiding a tag that has only partly arrived. */
export function extractActions(raw: string): { clean: string; actions: CopilotAction[] } {
  const actions: CopilotAction[] = []
  const clean = raw
    .replace(ACTION_RE, (_, json: string) => {
      try {
        const action = parseAction(JSON.parse(json))
        if (action) actions.push(action)
      } catch { /* malformed tag: drop it */ }
      return ''
    })
    .replace(PARTIAL_TAG_RE, '')
  return { clean, actions }
}

export const actionKey = (action: CopilotAction) => JSON.stringify(action)

export function actionLabel(action: CopilotAction): string {
  switch (action.type) {
    case 'zoom_to_city': return `Show ${action.city}`
    case 'zoom_to_station': return action.station_name ? `Show ${action.station_name}` : 'Show station'
    case 'set_horizon': return action.horizon === 0 ? 'Show today' : `Show +${action.horizon} days`
    case 'show_trajectory': return action.direction === 'forward' ? 'Air path ahead' : 'Where the air came from'
    case 'filter_network': return action.network ? `Show ${action.network}` : 'Show all networks'
    case 'show_station_trend': {
      const hours = action.hours ?? 24
      return `${hours <= 72 ? `${hours}h` : `${Math.round(hours / 24)}d`} trend`
    }
  }
}

/** Centre of a city's stations, or null when none of them have a position. */
export function cityCentre(
  stations: { city?: string | null; lat?: number | null; lon?: number | null }[],
  city: string,
): { lng: number; lat: number } | null {
  const wanted = city.trim().toLowerCase()
  let lat = 0, lng = 0, n = 0
  for (const s of stations) {
    if ((s.city ?? '').trim().toLowerCase() !== wanted || s.lat == null || s.lon == null) continue
    lat += s.lat
    lng += s.lon
    n += 1
  }
  return n ? { lng: lng / n, lat: lat / n } : null
}
