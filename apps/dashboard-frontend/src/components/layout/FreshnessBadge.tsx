'use client'

import { useQuery } from '@tanstack/react-query'
import { useOptionalSelection } from '@/lib/selection'
import { formatPkt, relativeAge } from '@/lib/time'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'https://hawanama-152782825429.asia-south1.run.app'

interface FreshnessSource {
  source: string
  scope_type: string
  latest_ts: string | null
  latest_ingested_at?: string | null
  age_min: number | null
  threshold_min: number | null
  status: string
  last_run_status?: string | null
  last_run_error?: string | null
}

async function fetchFreshness(): Promise<{ status: string; sources: FreshnessSource[] }> {
  // 503 is a legitimate "degraded" answer that still carries the per-source detail
  const res = await fetch(`${API_BASE}/api/v1/health/freshness`, { cache: 'no-store' })
  if (!res.ok && res.status !== 503) throw new Error(`freshness ${res.status}`)
  return res.json()
}

/**
 * Replaces the static "Live Monitoring" dot: the dot colour follows the real age of the
 * newest station observation, and historical browsing is labelled as such.
 */
export function FreshnessBadge() {
  const selection = useOptionalSelection()
  const { data, isError } = useQuery({ queryKey: ['health-freshness'], queryFn: fetchFreshness, refetchInterval: 5 * 60 * 1000, staleTime: 60 * 1000 })

  const stations = data?.sources?.find(s => s.source === 'airvisual' && s.scope_type === 'station')
  const age = stations?.age_min ?? null
  const ok = age != null && age <= (stations?.threshold_min ?? 180)
  const dot = isError || age == null ? 'bg-slate-400' : ok ? 'bg-emerald-500' : 'bg-amber-500'
  const label = isError ? 'Status unavailable'
    : age == null ? 'Checking data age…'
    : `Observations ${relativeAge(stations?.latest_ts)}`
  const title = stations?.latest_ts ? `Latest station observation ${formatPkt(stations.latest_ts)}` : undefined

  const historical = selection && selection.date && !selection.isLatest

  // Satellite fires: judged by the API from the last ingest run (3-hourly)
  const fires = data?.sources?.find(s => s.source === 'fires')
  const firesOk = fires?.status === 'ok'
  const firesText = !fires ? null
    : fires.last_run_error === 'invalid_key' ? 'Fires: feed key rejected'
    : fires.latest_ingested_at ? `Fires ${relativeAge(fires.latest_ingested_at)}`
    : 'Fires: no recent update'
  const firesTitle = fires
    ? `Satellite fire feed ${firesOk ? 'up to date' : 'delayed'}; last successful fetch ${fires.latest_ingested_at ? formatPkt(fires.latest_ingested_at) : 'unknown'}${fires.last_run_status && fires.last_run_status !== 'success' ? ` (last run ${fires.last_run_status}${fires.last_run_error ? `: ${fires.last_run_error}` : ''})` : ''}`
    : undefined

  return (
    <div className="flex items-center gap-2 text-slate-600" title={title}>
      <div className={`w-2 h-2 rounded-full ${dot} ${ok ? 'animate-pulse' : ''}`} />
      <span>{label}</span>
      {firesText && (
        <span className={`ml-1 hidden sm:inline-flex items-center gap-1 text-[11px] ${firesOk ? 'text-slate-500' : 'text-amber-700'}`} title={firesTitle}>
          <span className={`w-1.5 h-1.5 rounded-full ${firesOk ? 'bg-orange-400' : 'bg-amber-500'}`} />
          {firesText}
        </span>
      )}
      {historical && (
        <span className="ml-1 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600">Historical view · {selection.date}</span>
      )}
    </div>
  )
}
