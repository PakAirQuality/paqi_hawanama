const INT = new Intl.NumberFormat('en-US')

export const fmtInt = (v: number | null | undefined): string => (v == null ? '—' : INT.format(Math.round(v)))

export function fmtPct(v: number | null | undefined): string {
  if (v == null) return '—'
  if (v === 0) return '0%'
  return `${v > 0 ? '+' : '−'}${Math.abs(v)}%`
}

export const fmtMw = (v: number | null | undefined): string => (v == null ? '—' : `${INT.format(Math.round(v))} MW`)

export const fmtShare = (v: number | null | undefined): string => (v == null ? '—' : `${Math.round(v * 100)}%`)

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** "10-01" → "1 Oct"; "2026-10-01" → "1 Oct". */
export function dayLabel(mmdd: string): string {
  const parts = mmdd.split('-')
  const m = Number(parts[parts.length - 2])
  const d = Number(parts[parts.length - 1])
  return `${d} ${MONTHS[m - 1] ?? ''}`.trim()
}

/** "2026-11-03" → "3 Nov 2026". */
export function dateLabel(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number)
  return `${d} ${MONTHS[m - 1]} ${y}`
}

/** 12726 → "12.7k" for compact axes. */
export function fmtCompact(v: number): string {
  if (Math.abs(v) >= 1000) return `${(v / 1000).toFixed(v >= 10000 ? 0 : 1)}k`
  return `${Math.round(v)}`
}
