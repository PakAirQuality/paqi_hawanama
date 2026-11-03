'use client'

import { useQuery } from '@tanstack/react-query'
import { formatPkt, updatedAgo } from '@/lib/time'

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? ''

interface FreshnessSource {
  source: string
  scope_type: string
  latest_ts: string | null
  age_min: number | null
  threshold_min: number | null
}

async function fetchFreshness(): Promise<{ status: string; sources: FreshnessSource[] }> {
  // 503 is a legitimate "degraded" answer that still carries the per-source detail
  const res = await fetch(`${API_BASE}/api/v1/health/freshness`, { cache: 'no-store' })
  if (!res.ok && res.status !== 503) throw new Error(`freshness ${res.status}`)
  return res.json()
}

/** How long ago the newest station observation arrived; amber once it is overdue. */
export function FreshnessBadge() {
  const { data } = useQuery({ queryKey: ['health-freshness'], queryFn: fetchFreshness, refetchInterval: 5 * 60 * 1000, staleTime: 60 * 1000 })

  const stations = data?.sources?.find(s => s.source === 'airvisual' && s.scope_type === 'station')
  if (stations?.age_min == null) return null

  const overdue = stations.age_min > (stations.threshold_min ?? 180)
  return (
    <span
      className={overdue ? 'text-amber-700' : 'text-slate-600'}
      title={stations.latest_ts ? `Latest station observation ${formatPkt(stations.latest_ts)}` : undefined}
    >
      {updatedAgo(stations.latest_ts)}
    </span>
  )
}
