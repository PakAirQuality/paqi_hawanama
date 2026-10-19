/** Format a YYYY-MM-DD date string as "May 11, 2026" without timezone surprises. */
export function formatDateLabel(date: string | null | undefined): string {
  if (!date) return ''
  return new Date(date + 'T00:00:00').toLocaleDateString('en-US', {
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  })
}

const PKT = 'Asia/Karachi'

/** Hour of day (0-23) in Pakistan time, whatever timezone the browser runs in. */
export function pktHour(date: Date): number {
  return Number(date.toLocaleString('en-US', { timeZone: PKT, hour: '2-digit', hourCycle: 'h23' }))
}

/** "HH" label in Pakistan time for chart axes. */
export function pktHourLabel(date: Date): string {
  return date.toLocaleTimeString('en-US', { timeZone: PKT, hour: '2-digit', hourCycle: 'h23' })
}

/** "15 Oct, 20:00 PKT" for "updated" captions. */
export function formatPktDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString('en-GB', { timeZone: PKT, day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }) + ' PKT'
}
