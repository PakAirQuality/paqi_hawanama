import type { SeasonsResponse } from './api'
import { dayLabel, fmtInt } from './format'

export interface HeadlineParts {
  lead: string        // "So far this season (16 Oct – 3 Nov, the 19 days with data)"
  count: string       // "12,726"
  unit: string        // "fires"
  vsLast: string | null
  vsRef: string | null
  rank: string | null
  subline: string
}

function compare(pct: number | null, what: string): string | null {
  if (pct == null) return null
  if (Math.abs(pct) < 1) return `about the same as ${what}`
  return `${Math.abs(pct)}% ${pct < 0 ? 'fewer' : 'more'} than ${what}`
}

/** The sentence at the top of the page, built from /seasons only. */
export function headlineParts(data: SeasonsResponse, regionLabel: string): HeadlineParts {
  const h = data.headline
  const w = h.window
  const seasonYear = data.season.year
  const dates = w.compared_dates ?? `${dayLabel(w.start)} – ${dayLabel(w.end)}`
  const gapNote = w.days_missing > 0 ? `, the ${w.days_with_data} days with data` : ''
  const lead = data.season.complete
    ? `In the ${seasonYear} season (${dayLabel(data.season.start)} – ${dayLabel(data.season.end)}${gapNote})`
    : `So far this season (${dates}${gapNote})`
  const ref = h.reference
  const refYears = ref.used_years.length ? `${ref.used_years[0]}–${ref.used_years[ref.used_years.length - 1]}` : null
  return {
    lead,
    count: fmtInt(h.fires),
    unit: h.fires === 1 ? 'fire' : 'fires',
    vsLast: h.last_year ? compare(h.last_year.pct_change, `the same dates in ${h.last_year.year}`) : null,
    vsRef: refYears && ref.pct_change != null ? compare(ref.pct_change, `the ${refYears} average on those dates`) : null,
    rank: ref.rank_text,
    subline: `${regionLabel}. Counts are deduplicated fires with a high- or nominal-confidence detection, the measure that stays comparable as satellites change; they are a floor, not a census.`,
  }
}

export function headlineSentence(p: HeadlineParts, regionLabel: string): string {
  const parts = [`${p.lead} ${regionLabel} has seen ${p.count} ${p.unit}`]
  const tail: string[] = []
  if (p.vsLast) tail.push(p.vsLast)
  if (p.vsRef) tail.push(p.vsRef)
  let s = parts[0]
  if (tail.length) s += `, ${tail.join(' and ')}`
  if (p.rank) s += ` (${p.rank})`
  return `${s}.`
}
