import { pktToday, shiftDateOnly } from '@/lib/time'
import type { Basis, SeasonId } from './api'
import { isPreset } from './regions'

export interface FiresParams {
  region: string
  season: SeasonId
  basis: Basis            // 'all' satellites, or 'n20' (NOAA-20 only) for year comparisons
  city: string | null     // null = first city from the list (Lahore when present)
  date: string            // YYYY-MM-DD, ≤ yesterday PKT
}

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/

export function defaultSeason(today: string = pktToday()): SeasonId {
  const mmdd = today.slice(5)
  return mmdd >= '04-15' && mmdd <= '05-31' ? 'wheat' : 'rice'
}

export function parseFiresParams(search: string, opts: { today?: string; districts?: { name: string }[] } = {}): FiresParams {
  const today = opts.today ?? pktToday()
  const yesterday = shiftDateOnly(today, -1)
  const q = new URLSearchParams(search)
  const region = q.get('region') ?? 'pakistan'
  const knownDistrict = opts.districts?.some(d => d.name.toLowerCase() === region.toLowerCase())
  const season = q.get('season')
  const date = q.get('date')
  return {
    region: isPreset(region) || knownDistrict || opts.districts == null ? region : 'pakistan',
    season: season === 'rice' || season === 'wheat' ? season : defaultSeason(today),
    basis: q.get('basis') === 'n20' ? 'n20' : 'all',
    city: q.get('city') || null,
    date: date && DATE_RE.test(date) && date >= '2020-01-01' && date <= yesterday ? date : yesterday,
  }
}

export function serializeFiresParams(p: FiresParams, today: string = pktToday()): string {
  const q = new URLSearchParams()
  if (p.region !== 'pakistan') q.set('region', p.region)
  if (p.season !== defaultSeason(today)) q.set('season', p.season)
  if (p.basis === 'n20') q.set('basis', 'n20')
  if (p.city) q.set('city', p.city)
  if (p.date !== shiftDateOnly(today, -1)) q.set('date', p.date)
  const s = q.toString()
  return s ? `?${s}` : ''
}
