/** A Tracker link that opens the fire layer on a day and flies to a point. */
export function trackerFireLink(opts: { date?: string | null; lat: number; lon: number; zoom?: number }): string {
  const q = new URLSearchParams()
  if (opts.date) q.set('date', opts.date)
  q.set('layers', 'fires')
  q.set('focus', `${opts.lat.toFixed(4)},${opts.lon.toFixed(4)},${opts.zoom ?? 9}`)
  return `/?${q.toString()}`
}
