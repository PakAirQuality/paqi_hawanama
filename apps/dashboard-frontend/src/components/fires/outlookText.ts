import type { OutlookBand, OutlookLead } from './api'
import { dayLabel, fmtInt, fmtMw } from './format'

export const BAND_LABEL: Record<OutlookBand, string> = { none: 'None', low: 'Low', elevated: 'Elevated', high: 'High', very_high: 'Very high' }
export const BAND_CLASS: Record<OutlookBand, string> = {
  none: 'bg-slate-100 text-slate-600', low: 'bg-amber-50 text-amber-800', elevated: 'bg-orange-100 text-orange-800',
  high: 'bg-red-100 text-red-800', very_high: 'bg-red-600 text-white',
}

export function leadTitle(lead: OutlookLead, today: string): string {
  if (lead.day === today) return 'Today'
  const i = Number(lead.lead.replace('D+', ''))
  if (i === 1) return 'Tomorrow'
  return dayLabel(lead.day)
}

/** One line per lead: "NW wind, 4.8 m/s; 1,534 MW upwind (255 fires in Pakistan)". */
export function leadSentence(lead: OutlookLead): string {
  if (lead.status !== 'ok' || !lead.wind_850) return 'No forecast wind for this day.'
  const w = lead.wind_850
  const countries = Object.entries(lead.by_country ?? {}).map(([c, n]) => `${fmtInt(n)} in ${shortCountry(c)}`).join(', ')
  const fires = lead.fires_reachable ?? 0
  return `${w.from_compass ?? '—'} wind, ${w.speed_ms ?? '—'} m/s; ${fmtMw(lead.upwind_load_mw)} upwind` +
    (fires ? ` (${countries || `${fmtInt(fires)} fires`})` : ' (no reachable fires in the cone)')
}

export function shortCountry(c: string): string {
  return { 'Pakistan': 'Pakistan', 'India (Punjab+Haryana)': 'India', 'other in bbox': 'other' }[c] ?? c
}
