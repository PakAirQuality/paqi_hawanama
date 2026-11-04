import type { SeasonsResponse, SeasonYear } from './api'
import { dayLabel } from './format'

export interface ChartRow {
  d: number
  label: string
  [year: string]: number | string | null
}

export const yearKey = (y: number) => `y${y}`

/** One row per day of season; each year's 7-day mean under y<year> (null = gap). */
export function toChartRows(data: SeasonsResponse): ChartRow[] {
  return data.days.map((mmdd, i) => {
    const row: ChartRow = { d: i, label: dayLabel(mmdd) }
    for (const y of data.years) row[yearKey(y.year)] = y.r7[i] ?? null
    return row
  })
}

/** Indices for the x ticks: the 1st and 15th of each month in the window, plus the last day. */
export function axisTicks(days: string[]): number[] {
  const out: number[] = []
  days.forEach((mmdd, i) => {
    const d = Number(mmdd.slice(3))
    if (d === 1 || d === 15 || i === days.length - 1) out.push(i)
  })
  if (!out.includes(0)) out.unshift(0)
  return out
}

export function lastNonNullIndex(values: (number | null)[]): number {
  for (let i = values.length - 1; i >= 0; i--) if (values[i] != null) return i
  return -1
}

/** A pleasant axis maximum above the largest 7-day mean. */
export function niceMax(years: SeasonYear[]): number {
  let max = 0
  for (const y of years) for (const v of y.r7) if (v != null && v > max) max = v
  if (max <= 0) return 10
  const mag = 10 ** Math.floor(Math.log10(max))
  const steps = [1, 2, 2.5, 5, 10]
  for (const s of steps) if (max <= s * mag) return s * mag
  return 10 * mag
}

/**
 * Vertical offsets (in data units) that keep end-of-line labels at least `minPx` apart.
 * `plotPx` is the plot height in pixels; `yMax` the axis maximum. Labels keep their order.
 */
export function endLabelOffsets(ends: { key: string; value: number }[], yMax: number, plotPx: number, minPx = 11): Record<string, number> {
  const unit = (yMax / Math.max(plotPx, 1)) * minPx  // data units per minPx
  const sorted = [...ends].sort((a, b) => a.value - b.value)
  const placed: number[] = []
  for (let i = 0; i < sorted.length; i++) {
    let y = sorted[i].value
    if (i > 0 && y - placed[i - 1] < unit) y = placed[i - 1] + unit
    placed.push(y)
  }
  // pull everything down if the top label would leave the plot
  const over = placed.length ? placed[placed.length - 1] - yMax : 0
  if (over > 0) for (let i = 0; i < placed.length; i++) placed[i] -= over
  const out: Record<string, number> = {}
  sorted.forEach((e, i) => { out[e.key] = placed[i] - e.value })
  return out
}

/** Pixel positions for stacked labels: keeps the order, enforces a minimum gap, stays within [0, maxPx]. */
export function stackPx(items: { key: string; y: number }[], minPx = 12, maxPx = Infinity): Record<string, number> {
  const sorted = [...items].sort((a, b) => a.y - b.y)
  const placed: number[] = []
  for (let i = 0; i < sorted.length; i++) {
    let y = sorted[i].y
    if (i > 0 && y - placed[i - 1] < minPx) y = placed[i - 1] + minPx
    placed.push(y)
  }
  const over = placed.length ? placed[placed.length - 1] - maxPx : 0
  if (over > 0) for (let i = 0; i < placed.length; i++) placed[i] -= over
  const out: Record<string, number> = {}
  sorted.forEach((e, i) => { out[e.key] = placed[i] })
  return out
}
