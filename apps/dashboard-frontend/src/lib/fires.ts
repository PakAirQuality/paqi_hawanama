import type { FiresGeoJSON, FiresStatus } from '@/components/analyst-desk/api'
import { formatDateOnly } from '@/lib/time'

/** A fire file older than this (hours since the last successful fetch) is flagged as delayed.
 *  The ingest runs every 3 h, so 6 h means at least one run was missed or failed. */
export const FIRES_DELAYED_AFTER_HOURS = 6

export function firesStatus(data: FiresGeoJSON | null | undefined): FiresStatus | null {
  if (!data) return null
  return data.status ?? (data.features.length ? 'ok' : 'empty')
}

export function firesDelayed(data: FiresGeoJSON | null | undefined): boolean {
  return (data?.fetched_age_hours ?? 0) > FIRES_DELAYED_AFTER_HOURS
}

/**
 * Short label for compact places (map badge, stat card) that cannot show the full panel text.
 * `count` is the number actually drawn (e.g. after the Pakistan filter).
 */
export function firesShortLabel(data: FiresGeoJSON | null | undefined, count: number): { text: string; warn: boolean } {
  const status = firesStatus(data)
  if (!data || !status) return { text: 'Loading fires…', warn: false }
  const delayed = firesDelayed(data)
  switch (status) {
    case 'ok':
      return { text: `${count} detections${delayed ? ' · delayed' : ''}`, warn: delayed }
    case 'empty':
      return { text: `No detections${delayed ? ' · delayed' : ''}`, warn: delayed }
    case 'partial':
      return { text: `${count} detections · partial`, warn: true }
    case 'stale':
      return { text: `${count} from ${formatDateOnly(data.date)}`, warn: true }
    default:
      return { text: 'Fire data unavailable', warn: true }
  }
}
