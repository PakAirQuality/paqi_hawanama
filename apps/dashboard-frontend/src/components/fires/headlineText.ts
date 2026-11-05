import { isCropBasis, isN20Basis, type SeasonsResponse } from './api'
import { dayLabel, fmtInt } from './format'

export interface HeadlineParts {
  lead: string        // "So far this season (16 Oct – 3 Nov, the 19 days with data)"
  count: string       // "12,726"
  unit: string        // "fire detections"
  vsLast: string | null
  vsRef: string | null
  rank: string | null
  basisNote: string | null   // "NOAA-20 only" when the comparison is on the consistent series
  subline: string
}

function compare(pct: number | null, what: string): string | null {
  if (pct == null) return null
  if (Math.abs(pct) < 1) return `about the same as ${what}`
  return `${Math.abs(pct)}% ${pct < 0 ? 'fewer' : 'more'} than ${what}`
}

/**
 * The sentence at the top of the page, built from /seasons only. The count is on the page's basis; the
 * year-on-year clauses come from the NOAA-20-only block when the store carries it, because the satellite
 * roster changed and the all-satellite ratio is not comparable across years.
 */
export function headlineParts(data: SeasonsResponse, regionLabel: string): HeadlineParts {
  const h = data.headline
  const w = h.window
  const seasonYear = data.season.year
  const dates = w.compared_dates ?? `${dayLabel(w.start)} – ${dayLabel(w.end)}`
  const gapNote = w.days_missing > 0 ? `, the ${w.days_with_data} days with data` : ''
  const lead = data.season.complete
    ? `In the ${seasonYear} season (${dayLabel(data.season.start)} – ${dayLabel(data.season.end)}${gapNote})`
    : `So far this season (${dates}${gapNote})`
  const cmp = h.comparison_n20 ?? h
  const basis = data.basis ?? 'all'
  const crop = isCropBasis(basis)
  const onN20 = h.comparison_n20 != null || isN20Basis(basis)
  const ref = cmp.reference
  const refYears = ref.used_years.length ? `${ref.used_years[0]}–${ref.used_years[ref.used_years.length - 1]}` : null
  const what = crop ? 'detections classified as likely crop-residue burning (cropland, harvest window, no listed kiln or industrial site within 1 km, not a persistent out-of-season cell; an unvalidated classification)' : 'deduplicated detection clusters'
  const basisSentence = isN20Basis(basis)
    ? `Counts are ${what} from NOAA-20 alone, the satellite flown every year since 2020, so the series is comparable across years.`
    : onN20
      ? `Counts are ${what} from every satellite flown that day; the year-on-year figures hold the satellite fixed (NOAA-20 only), because deduplication cannot remove the extra fires an added satellite sees.`
      : `Counts are ${what} from every satellite flown that day; the satellite roster changed over the years, so the year-on-year figures are indicative only.`
  const unitBase = crop ? 'likely crop-residue fire detection' : 'fire detection'
  return {
    lead,
    count: fmtInt(h.fires),
    unit: h.fires === 1 ? unitBase : `${unitBase}s`,
    vsLast: cmp.last_year ? compare(cmp.last_year.pct_change, `the same dates in ${cmp.last_year.year}`) : null,
    vsRef: refYears && ref.pct_change != null ? compare(ref.pct_change, `the ${refYears} average on those dates`) : null,
    rank: ref.rank_text,
    basisNote: onN20 && h.comparison_n20 ? 'NOAA-20 only' : null,
    subline: `${regionLabel}. ${basisSentence} A detection cluster is not a verified fire and does not say what burns; counts are a floor, not a census.`,
  }
}

export function headlineSentence(p: HeadlineParts, regionLabel: string): string {
  const parts = [`${p.lead} ${regionLabel} has seen ${p.count} ${p.unit}`]
  const tail: string[] = []
  if (p.vsLast) tail.push(p.vsLast)
  if (p.vsRef) tail.push(p.vsRef)
  let s = parts[0]
  if (tail.length) s += `, ${tail.join(' and ')}${p.basisNote ? ` (${p.basisNote})` : ''}`
  if (p.rank) s += ` (${p.rank})`
  return `${s}.`
}
