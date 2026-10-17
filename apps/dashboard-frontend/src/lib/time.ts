/**
 * Pakistan-time helpers. Timestamps are stored in UTC; Pakistan views display in
 * Asia/Karachi (UTC+5, no DST). Calendar dates ("YYYY-MM-DD") are Pakistan days unless a
 * caller says otherwise, and must never be parsed with `new Date('YYYY-MM-DD')` (UTC
 * midnight shifted by the browser's zone) or compared with the browser's UTC "today".
 */

export const PK_TZ = 'Asia/Karachi'
export const PK_OFFSET_MINUTES = 5 * 60

const ymd = new Intl.DateTimeFormat('en-CA', { timeZone: PK_TZ, year: 'numeric', month: '2-digit', day: '2-digit' })

/** Today's calendar date in Pakistan, as YYYY-MM-DD. */
export function pktToday(now: Date = new Date()): string {
  return ymd.format(now)
}

/** Calendar date in Pakistan of a UTC instant. */
export function pktDateOf(instant: Date | string): string {
  const d = typeof instant === 'string' ? new Date(instant) : instant
  return ymd.format(d)
}

/** Parse a YYYY-MM-DD as local-noon of that day, so formatting never slips a day. */
export function parseDateOnly(dateStr: string): Date {
  const [y, m, d] = dateStr.split('-').map(Number)
  return new Date(y, (m || 1) - 1, d || 1, 12, 0, 0)
}

/** "Oct 17, 2026" for a YYYY-MM-DD, zone-safe. */
export function formatDateOnly(dateStr: string, opts: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric', year: 'numeric' }): string {
  return parseDateOnly(dateStr).toLocaleDateString('en-US', opts)
}

/** "17 Oct 2026, 14:00 PKT" for a UTC timestamp. */
export function formatPkt(instant: Date | string | null | undefined, withSeconds = false): string {
  if (!instant) return '—'
  const d = typeof instant === 'string' ? new Date(instant) : instant
  if (Number.isNaN(d.getTime())) return '—'
  const s = d.toLocaleString('en-GB', {
    timeZone: PK_TZ, day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
    ...(withSeconds ? { second: '2-digit' } : {}), hour12: false,
  })
  return `${s} PKT`
}

/** Hour (0-23) of a UTC timestamp in Pakistan time, for hourly charts. */
export function pktHour(instant: Date | string): number {
  const d = typeof instant === 'string' ? new Date(instant) : instant
  return Number(new Intl.DateTimeFormat('en-GB', { timeZone: PK_TZ, hour: '2-digit', hour12: false }).format(d))
}

/** A YYYY-MM-DD + HH:MM wall-clock time in Pakistan as an ISO UTC string. */
export function pktLocalToIso(dateStr: string, hhmm: string): string {
  const [y, m, d] = dateStr.split('-').map(Number)
  const [hh, mm] = hhmm.split(':').map(Number)
  const utcMs = Date.UTC(y, m - 1, d, hh, mm) - PK_OFFSET_MINUTES * 60_000
  return new Date(utcMs).toISOString()
}

/** Age in minutes between a UTC timestamp and now (null when missing). */
export function ageMinutes(instant: string | null | undefined, now: Date = new Date()): number | null {
  if (!instant) return null
  const t = new Date(instant).getTime()
  if (Number.isNaN(t)) return null
  return Math.round((now.getTime() - t) / 60_000)
}

/** "12 min ago" / "3 h ago" / "2 d ago". */
export function relativeAge(instant: string | null | undefined, now: Date = new Date()): string {
  const m = ageMinutes(instant, now)
  if (m == null) return 'unknown'
  if (m < 1) return 'just now'
  if (m < 60) return `${m} min ago`
  const h = Math.round(m / 60)
  if (h < 48) return `${h} h ago`
  return `${Math.round(h / 24)} d ago`
}
