"use client"

import { useEffect, useMemo } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import {
  CheckCircle2,
  XCircle,
  MinusCircle,
  ChevronLeft,
  ChevronRight,
  Calendar,
  Loader2,
  ArrowDown,
  ShieldCheck,
  ShieldAlert,
} from 'lucide-react'
import type { RunsResponse, RunReport, DataQuality } from './types'

interface DailyStatusTabProps {
  runs: RunsResponse | undefined
  runsLoading: boolean
  selectedRunDate: string | null
  setSelectedRunDate: (date: string | null) => void
  selectedRun: RunReport | null | undefined
  selectedRunLoading: boolean
}

type StageStatus = 'success' | 'error' | 'unavailable'

function getStageStatus(ok: boolean | string | undefined | null): StageStatus {
  if (ok === true || ok === 'ok' || ok === 'success') return 'success'
  if (ok === false || ok === 'error' || ok === 'failed') return 'error'
  return 'unavailable'
}

function StatusIcon({ status }: { status: StageStatus }) {
  if (status === 'success') return <CheckCircle2 className="w-4 h-4 text-emerald-500 flex-shrink-0" />
  if (status === 'error') return <XCircle className="w-4 h-4 text-red-500 flex-shrink-0" />
  return <MinusCircle className="w-4 h-4 text-gray-300 flex-shrink-0" />
}

function Metric({ label, value }: { label: string; value: string | number | undefined | null }) {
  return (
    <div className="text-center px-2">
      <div className="text-[10px] text-gray-500 uppercase tracking-wide">{label}</div>
      <div className="text-xs font-semibold text-gray-900">{value ?? '-'}</div>
    </div>
  )
}

function Connector() {
  return (
    <div className="flex justify-center py-0.5">
      <ArrowDown className="w-3 h-3 text-gray-300" />
    </div>
  )
}

function fmt(n: number | undefined | null, digits = 1): string {
  if (n == null) return '-'
  return n.toFixed(digits)
}

function pct(n: number | undefined | null): string {
  if (n == null) return '-'
  return (n * 100).toFixed(1) + '%'
}

function NaNBar({ label, nanFrac, featureCount, threshold }: {
  label: string; nanFrac: number; featureCount?: number; threshold?: number
}) {
  // Bar shows "data present" (1 - nanFrac), so higher = greener
  const dataPresent = 1 - nanFrac
  const pctWidth = Math.max(0, Math.min(100, dataPresent * 100))
  const failed = threshold != null && nanFrac > threshold
  const barColor = failed
    ? 'bg-red-400'
    : dataPresent >= 0.8
    ? 'bg-emerald-400'
    : dataPresent >= 0.5
    ? 'bg-amber-400'
    : 'bg-red-400'

  return (
    <div className="space-y-0.5">
      <div className="flex justify-between items-baseline">
        <span className="text-[10px] font-medium text-gray-700 uppercase tracking-wide">
          {label}{featureCount != null && <span className="text-gray-400 ml-0.5">({featureCount}f)</span>}
        </span>
        <span className={`text-xs font-semibold ${failed ? 'text-red-600' : 'text-gray-900'}`}>
          {(nanFrac * 100).toFixed(0)}% NaN
        </span>
      </div>
      <div className="h-1.5 bg-gray-200 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${barColor}`}
          style={{ width: `${pctWidth}%` }}
        />
      </div>
    </div>
  )
}

function DataQualityGate({ quality }: { quality: DataQuality }) {
  const missingRatio = quality.missing_features / Math.max(quality.total_features, 1)
  const snf = quality.stage_nan_fraction ?? {}
  const sfc = quality.stage_feature_count ?? {}
  const metNan = snf.met ?? (1 - (quality.stage_coverage.met ?? 0))

  const featureGateOk = missingRatio <= 0.5
  const metGateOk = metNan <= 0.5
  const gatePass = featureGateOk && metGateOk

  return (
    <Card>
      <CardContent className="p-3">
        {/* Header */}
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            {gatePass
              ? <ShieldCheck className="w-4 h-4 text-emerald-500" />
              : <ShieldAlert className="w-4 h-4 text-red-500" />
            }
            <span className="text-sm font-semibold text-gray-900">Data Quality Gate</span>
          </div>
          <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full ${
            gatePass
              ? 'bg-emerald-100 text-emerald-700'
              : 'bg-red-100 text-red-700'
          }`}>
            {gatePass ? 'PASS' : 'FAIL'}
          </span>
        </div>

        {/* Metrics row */}
        <div className="grid grid-cols-4 gap-2 mb-3">
          <div className="p-2 bg-blue-50 rounded text-center">
            <div className="text-[10px] text-blue-600 font-medium uppercase">Features</div>
            <div className="text-sm font-bold text-blue-900">
              {quality.available_features}/{quality.total_features}
            </div>
          </div>
          <div className={`p-2 rounded text-center ${missingRatio > 0.5 ? 'bg-red-50' : 'bg-gray-50'}`}>
            <div className={`text-[10px] font-medium uppercase ${missingRatio > 0.5 ? 'text-red-600' : 'text-gray-600'}`}>Missing</div>
            <div className={`text-sm font-bold ${missingRatio > 0.5 ? 'text-red-900' : 'text-gray-900'}`}>
              {quality.missing_features}
            </div>
          </div>
          <div className="p-2 bg-amber-50 rounded text-center">
            <div className="text-[10px] text-amber-600 font-medium uppercase">Overall NaN</div>
            <div className="text-sm font-bold text-amber-900">
              {(quality.nan_fraction * 100).toFixed(1)}%
            </div>
          </div>
          <div className="p-2 bg-slate-50 rounded text-center">
            <div className="text-[10px] text-slate-600 font-medium uppercase">PK Cells</div>
            <div className="text-sm font-bold text-slate-900">
              {quality.pakistan_cells > 1000
                ? (quality.pakistan_cells / 1000).toFixed(1) + 'k'
                : quality.pakistan_cells}
            </div>
          </div>
        </div>

        {/* Per-stage NaN breakdown */}
        <div className="space-y-2">
          <div className="text-[10px] text-gray-500 uppercase tracking-wide font-medium">
            Per-Stage NaN (lower is better)
          </div>
          <div className="grid grid-cols-3 gap-3">
            <NaNBar label="MET" nanFrac={snf.met ?? 0} featureCount={sfc.met} threshold={0.5} />
            <NaNBar label="AOD" nanFrac={snf.aod ?? 0} featureCount={sfc.aod} />
            <NaNBar label="TROPOMI" nanFrac={snf.tropomi ?? 0} featureCount={sfc.tropomi} />
          </div>
          <div className="text-[10px] text-gray-400 italic">
            AOD/TROPOMI NaN is normal due to satellite orbit gaps and cloud masking
          </div>
        </div>

        {/* Gate failure reasons */}
        {!gatePass && (
          <div className="mt-2 space-y-1">
            {!featureGateOk && (
              <div className="text-xs text-red-600 bg-red-50 rounded px-2 py-1">
                Feature gate failed: {quality.missing_features}/{quality.total_features} features missing (&gt;50%)
              </div>
            )}
            {!metGateOk && (
              <div className="text-xs text-red-600 bg-red-50 rounded px-2 py-1">
                MET gate failed: NaN fraction {(metNan * 100).toFixed(0)}% &gt; 50%
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export function DailyStatusTab({
  runs,
  runsLoading,
  selectedRunDate,
  setSelectedRunDate,
  selectedRun,
  selectedRunLoading,
}: DailyStatusTabProps) {
  const dates = useMemo(() => runs?.dates ?? [], [runs])
  const currentIndex = selectedRunDate ? dates.indexOf(selectedRunDate) : -1

  useEffect(() => {
    if (dates.length > 0 && !selectedRunDate) {
      setSelectedRunDate(dates[dates.length - 1])
    }
  }, [dates, selectedRunDate, setSelectedRunDate])

  const formatDisplayDate = (dateStr: string) => {
    const d = new Date(dateStr)
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  }

  const details = selectedRun?.details

  const stages = useMemo(() => {
    if (!details) return null
    const sd = details.station_data
    const fp = details.feature_partitions
    const mp = details.master_partition
    const inf = details.inference

    return [
      {
        name: 'Station Data',
        status: getStageStatus(sd?.status),
        metrics: [
          { label: 'Stations', value: sd?.n_stations },
          { label: 'Obs', value: sd?.n_obs },
          { label: 'PM2.5 Mean', value: fmt(sd?.pm25_mean) },
          { label: 'PM2.5 Median', value: fmt(sd?.pm25_median) },
        ],
        error: sd?.error,
      },
      {
        name: 'ERA5 / MET',
        status: getStageStatus(fp?.met?.status),
        metrics: [
          { label: 'Status', value: fp?.met?.status ?? '-' },
          { label: 'Missing', value: pct(fp?.met?.missing_rate) },
        ],
        error: fp?.met?.error,
      },
      {
        name: 'AOD',
        status: getStageStatus(fp?.aod?.status),
        metrics: [
          { label: 'Status', value: fp?.aod?.status ?? '-' },
          { label: 'Missing', value: pct(fp?.aod?.missing_rate) },
        ],
        error: fp?.aod?.error,
      },
      {
        name: 'TROPOMI',
        status: getStageStatus(fp?.tropomi?.status),
        metrics: [
          { label: 'Status', value: fp?.tropomi?.status ?? '-' },
          { label: 'Missing', value: pct(fp?.tropomi?.missing_rate) },
        ],
        error: fp?.tropomi?.error,
      },
      {
        name: 'Master Join',
        status: getStageStatus(mp?.status),
        metrics: [
          { label: 'Features', value: mp?.n_features },
          { label: 'Missing', value: pct(mp?.total_missing_rate) },
          ...(mp?.missing_by_family ? [
            { label: 'MET', value: pct(mp.missing_by_family.met) },
            { label: 'AOD', value: pct(mp.missing_by_family.aod) },
            { label: 'TROP', value: pct(mp.missing_by_family.tropomi) },
          ] : []),
        ],
      },
      {
        name: 'Inference',
        status: getStageStatus(inf?.status),
        metrics: [
          { label: 'Mean', value: fmt(inf?.pred_mean) },
          { label: 'Median', value: fmt(inf?.pred_median) },
          { label: 'P95', value: fmt(inf?.pred_p95) },
          { label: '% Neg', value: inf?.pct_negative != null ? pct(inf.pct_negative) : '-' },
        ],
        error: inf?.error,
      },
    ]
  }, [details])

  return (
    <div className="space-y-3">
      {/* Date Scrubber */}
      <Card>
        <CardContent className="p-3">
          {runsLoading ? (
            <div className="h-10 bg-gray-100 rounded animate-pulse" />
          ) : dates.length === 0 ? (
            <div className="text-center py-3 text-gray-500">
              <Calendar className="w-5 h-5 mx-auto mb-1 opacity-50" />
              <p className="text-xs">No run reports available</p>
            </div>
          ) : (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-2">
                  <button
                    onClick={() => { if (currentIndex > 0) setSelectedRunDate(dates[currentIndex - 1]) }}
                    disabled={currentIndex <= 0}
                    className="p-1 rounded hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                  >
                    <ChevronLeft className="w-4 h-4" />
                  </button>
                  <div className="text-center min-w-[120px]">
                    <div className="text-base font-bold text-gray-900">
                      {selectedRunDate ? formatDisplayDate(selectedRunDate) : 'Select date'}
                    </div>
                    <div className="text-[10px] text-gray-500">{selectedRunDate}</div>
                  </div>
                  <button
                    onClick={() => { if (currentIndex < dates.length - 1) setSelectedRunDate(dates[currentIndex + 1]) }}
                    disabled={currentIndex >= dates.length - 1}
                    className="p-1 rounded hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                  >
                    <ChevronRight className="w-4 h-4" />
                  </button>
                </div>
                <div className="text-xs text-gray-500">
                  {currentIndex + 1} of {dates.length}
                </div>
              </div>
              <div className="relative px-1">
                <input
                  type="range"
                  min={0}
                  max={dates.length - 1}
                  value={currentIndex >= 0 ? currentIndex : 0}
                  onChange={(e) => {
                    const idx = parseInt(e.target.value, 10)
                    if (dates[idx]) setSelectedRunDate(dates[idx])
                  }}
                  className="w-full h-1 bg-gradient-to-r from-blue-200 via-blue-400 to-blue-600 rounded-full appearance-none cursor-pointer
                    [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3.5 [&::-webkit-slider-thumb]:h-3.5
                    [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-white [&::-webkit-slider-thumb]:border-2
                    [&::-webkit-slider-thumb]:border-blue-600 [&::-webkit-slider-thumb]:shadow [&::-webkit-slider-thumb]:cursor-grab
                    [&::-webkit-slider-thumb]:active:cursor-grabbing [&::-webkit-slider-thumb]:hover:scale-110
                    [&::-webkit-slider-thumb]:transition-transform"
                />
                <div className="flex justify-between text-[9px] text-gray-400 mt-0.5">
                  <span>{dates[0]}</span>
                  <span>{dates[dates.length - 1]}</span>
                </div>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Pipeline Flow */}
      {selectedRunLoading ? (
        <Card>
          <CardContent className="p-6 flex items-center justify-center">
            <Loader2 className="w-5 h-5 animate-spin text-blue-500 mr-2" />
            <span className="text-gray-500 text-sm">Loading run report...</span>
          </CardContent>
        </Card>
      ) : stages ? (
        <Card>
          <CardContent className="p-3">
            <div className="space-y-1">
              {stages.map((stage, i) => (
                <div key={stage.name}>
                  <div className={`flex items-start space-x-2.5 p-2.5 rounded-lg border transition-colors ${
                    stage.status === 'success'
                      ? 'bg-emerald-50/50 border-emerald-200 hover:bg-emerald-50'
                      : stage.status === 'error'
                      ? 'bg-red-50/50 border-red-200 hover:bg-red-50'
                      : 'bg-gray-50/50 border-gray-200 hover:bg-gray-100'
                  }`}>
                    <StatusIcon status={stage.status} />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-semibold text-gray-900">{stage.name}</div>
                      <div className="flex flex-wrap gap-3 mt-1">
                        {stage.metrics.map((m) => (
                          <Metric key={m.label} label={m.label} value={m.value} />
                        ))}
                      </div>
                      {stage.error && (
                        <div className="mt-1.5 text-xs text-red-600 bg-red-100 rounded px-1.5 py-0.5">
                          {stage.error}
                        </div>
                      )}
                    </div>
                  </div>
                  {i < stages.length - 1 && <Connector />}
                </div>
              ))}
            </div>

            {/* Footer */}
            {selectedRun && (
              <div className="mt-3 pt-2 border-t border-gray-200 flex flex-wrap gap-4 text-[10px] text-gray-500">
                {details?.runtime_seconds != null && (
                  <span>Runtime: {details.runtime_seconds.toFixed(1)}s</span>
                )}
                {selectedRun.git_commit && (
                  <span>Commit: <code className="bg-gray-100 px-1 rounded">{selectedRun.git_commit.slice(0, 7)}</code></span>
                )}
                {selectedRun.model_version && (
                  <span>Model: {selectedRun.model_version}</span>
                )}
                <span>
                  Overall: {selectedRun.success
                    ? <span className="text-green-600 font-medium">Success</span>
                    : <span className="text-red-600 font-medium">Failed</span>}
                </span>
              </div>
            )}
          </CardContent>
        </Card>
      ) : selectedRunDate && !selectedRunLoading ? (
        <Card>
          <CardContent className="p-6 text-center text-gray-500 text-sm">
            No details available for this run.
          </CardContent>
        </Card>
      ) : null}

      {/* Data Quality Gate */}
      {selectedRun?.data_quality && (
        <DataQualityGate quality={selectedRun.data_quality} />
      )}
    </div>
  )
}
