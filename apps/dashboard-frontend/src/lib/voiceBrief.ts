/**
 * The spoken "air near you" brief: which monitor it is about, what the server is sent, and how a reply is
 * checked. Kept free of React so every edge case can be tested (see voiceBrief.test.ts).
 */

import { haversineKm } from '@/lib/geo'
import { stationNowcastPoints } from '@/lib/timeline'
import type { NowcastResponse } from '@/components/analyst-desk/types'
import type { StationReading } from '@/components/ops-pipeline/types'

export type VoiceLang = 'en' | 'ur'

/** The reading the brief is about. */
export interface VoiceTarget {
  station: string
  city: string
  /** How far the monitor is (chooses it; not spoken) */
  distKm: number
  pm25: number
  /** The nowcast at the same monitor a few hours ahead, for the "next few hours" sentence */
  next?: { pm25: number; hours: number } | null
}

/**
 * Whether a brief can be made yet:
 * - no-location: the visitor's location is not known (a tap asks for it)
 * - outside: the visitor is outside Pakistan, which the brief does not cover (a tap does not ask again)
 * - waiting: the location is known but the live readings are still loading
 * - no-data: the live readings failed to load
 * - no-monitor: no usable monitor within the radius
 * - ready: `target` is set
 */
export type VoiceAvailability = 'no-location' | 'outside' | 'waiting' | 'no-data' | 'no-monitor' | 'ready'

export const VOICE_RADIUS_KM = 50
/** The outlook looks this far ahead, choosing the nowcast value nearest 6 hours. */
const OUTLOOK_MIN_H = 2
const OUTLOOK_MAX_H = 12
const OUTLOOK_IDEAL_H = 6

const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)

/**
 * The live reading at the visitor's nearest usable monitor, with its nowcast a few hours ahead.
 * Monitors with a broken value or position are skipped, as are nowcast points with a bad time or value.
 */
export function voiceTarget(opts: {
  location: { lat: number; lng: number } | null
  /** The visitor's location was found to be outside Pakistan */
  outside?: boolean
  /** Live readings; undefined while loading */
  stations: StationReading[] | undefined
  liveFailed: boolean
  nowcast: NowcastResponse | null | undefined
  now: number
  radiusKm?: number
}): { target: VoiceTarget | null; availability: VoiceAvailability } {
  const { location, outside = false, stations, liveFailed, nowcast, now, radiusKm = VOICE_RADIUS_KM } = opts
  if (!location || !finite(location.lat) || !finite(location.lng)) return { target: null, availability: outside ? 'outside' : 'no-location' }
  if (!stations) return { target: null, availability: liveFailed ? 'no-data' : 'waiting' }

  let best: { s: StationReading; d: number } | null = null
  for (const s of stations) {
    if (!finite(s.pm25) || s.pm25 < 0 || !finite(s.lat) || !finite(s.lon)) continue
    const d = haversineKm(location.lat, location.lng, s.lat, s.lon)
    if (!finite(d)) continue
    if (!best || d < best.d) best = { s, d }
  }
  if (!best || best.d > radiusKm) return { target: null, availability: 'no-monitor' }

  let next: { pm25: number; hours: number } | null = null
  if (finite(now)) {
    for (const p of stationNowcastPoints(nowcast, best.s)) {
      const hours = (Date.parse(p.valid_time) - now) / 3_600_000
      // A bad timestamp gives NaN, which would slip past a plain range test
      if (!finite(hours) || !finite(p.pm25) || p.pm25 < 0 || hours < OUTLOOK_MIN_H || hours > OUTLOOK_MAX_H) continue
      if (!next || Math.abs(hours - OUTLOOK_IDEAL_H) < Math.abs(next.hours - OUTLOOK_IDEAL_H)) next = { pm25: p.pm25, hours }
    }
  }
  return {
    target: { station: best.s.name ?? '', city: best.s.city ?? '', distKm: best.d, pm25: best.s.pm25, next },
    availability: 'ready',
  }
}

/** One recording per monitor, rounded reading and outlook. */
export function briefKey(t: VoiceTarget): string {
  const next = t.next ? `${Math.round(t.next.pm25)}@${Math.round(t.next.hours)}` : '-'
  return `${t.station}|${t.city}|${Math.round(t.pm25)}|${next}`
}

/** Characters the server refuses in a name (markup, template and control characters). */
// eslint-disable-next-line no-control-regex
const BAD_NAME_CHARS = /[<>{}[\]\\`$\u0000-\u001f\u007f]/g
const cleanName = (s: unknown, max: number) =>
  (typeof s === 'string' ? s : '').replace(BAD_NAME_CHARS, ' ').replace(/\s+/g, ' ').trim().slice(0, max).trim()
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

/** What the server is sent: names cleaned, numbers kept inside the ranges it accepts, a broken outlook dropped. */
export function requestBody(t: VoiceTarget, l: VoiceLang) {
  const station = cleanName(t.station, 80) || cleanName(t.city, 80) || 'the nearest monitor'
  const next = t.next && finite(t.next.pm25) && finite(t.next.hours) ? t.next : null
  return {
    lang: l,
    station,
    city: cleanName(t.city, 60),
    pm25: clamp(finite(t.pm25) ? t.pm25 : 0, 0, 1000),
    ...(next ? { next_pm25: clamp(next.pm25, 0, 1000), next_hours: clamp(next.hours, 1, 24) } : {}),
  }
}

/** A reply from POST /voice/brief that can be played. */
export function isBriefResponse(v: unknown): v is { text: string; mime: string; audio: string } {
  if (!v || typeof v !== 'object') return false
  const o = v as Record<string, unknown>
  return typeof o.audio === 'string' && o.audio.length > 0 && typeof o.text === 'string' && typeof o.mime === 'string'
}
