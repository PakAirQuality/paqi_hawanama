'use client'

import { useEffect, useMemo, useState } from 'react'
import { Download, Info } from 'lucide-react'
import { LineChart, Line, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer, CartesianGrid } from 'recharts'
import {
  LIMITS, POLLUTANTS, type CityOption, type ProvinceOption, type Report, type ReportRequest, type StationOption,
  downloadCsv, getCities, getProvinces, getStations, reportToCsv, runReport, seriesStats, validateRequest,
} from '@/lib/reports'
import { formatPkt, pktToday, pktDateOf } from '@/lib/time'
import { classifyPm25 } from '@/lib/aqi'

const SERIES_COLORS = ['#0f766e', '#b45309', '#6d28d9', '#be123c', '#1d4ed8', '#4d7c0f', '#9333ea', '#c2410c', '#0369a1', '#a16207']

export default function ReportsPage() {
  const [provinces, setProvinces] = useState<ProvinceOption[]>([])
  const [cities, setCities] = useState<CityOption[]>([])
  const [stations, setStations] = useState<StationOption[]>([])

  const [provinceLabel, setProvinceLabel] = useState('')
  const [city, setCity] = useState('')
  const [mode, setMode] = useState<'stations' | 'city'>('stations')
  const [stationIds, setStationIds] = useState<string[]>([])
  const [parameters, setParameters] = useState<string[]>(['pm25'])

  // Defaults: the last 24 hours in Pakistan time
  const today = pktToday()
  const [startDate, setStartDate] = useState(pktDateOf(new Date(Date.now() - 86_400_000)))
  const [startTime, setStartTime] = useState(new Date(Date.now() - 86_400_000).toLocaleTimeString('en-GB', { timeZone: 'Asia/Karachi', hour: '2-digit', minute: '2-digit', hour12: false }))
  const [endDate, setEndDate] = useState(today)
  const [endTime, setEndTime] = useState(new Date().toLocaleTimeString('en-GB', { timeZone: 'Asia/Karachi', hour: '2-digit', minute: '2-digit', hour12: false }))

  const [view, setView] = useState<'table' | 'chart'>('table')
  const [loadingMeta, setLoadingMeta] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [report, setReport] = useState<Report | null>(null)

  const selectedProvince = useMemo(() => provinces.find((p) => p.label === provinceLabel) ?? null, [provinces, provinceLabel])

  useEffect(() => {
    setLoadingMeta(true)
    getProvinces().then(setProvinces).catch((e) => setError(e.message)).finally(() => setLoadingMeta(false))
  }, [])

  useEffect(() => {
    setCities([]); setCity(''); setStations([]); setStationIds([])
    if (!selectedProvince) return
    getCities(selectedProvince.province, selectedProvince.country).then(setCities).catch((e) => setError(e.message))
  }, [selectedProvince])

  useEffect(() => {
    setStations([]); setStationIds([])
    if (!selectedProvince || !city) return
    getStations(city, selectedProvince.province, selectedProvince.country).then(setStations).catch((e) => setError(e.message))
  }, [selectedProvince, city])

  const request: ReportRequest | null = selectedProvince ? {
    province: selectedProvince.province, country: selectedProvince.country, city, mode, stationIds, parameters,
    startDate, startTime, endDate, endTime,
  } : null
  const validation = request ? validateRequest(request) : 'Choose a province and a city.'

  async function submit() {
    if (!request || validation) return
    setLoading(true); setError(null); setReport(null)
    try {
      setReport(await runReport(request))
    } catch (e: any) {
      setError(e?.message || 'The report request failed.')
    } finally {
      setLoading(false)
    }
  }

  function toggleStation(id: string) {
    setStationIds((prev) => prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id])
  }

  return (
    <div className="p-6 max-w-6xl">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-slate-900">Reports</h1>
        <p className="text-sm text-slate-500 mt-1">
          Hourly readings for chosen stations, or the hourly reporting-station mean of a city, over an explicit interval in Pakistan time.
          Limits: {LIMITS.maxStations} stations and {LIMITS.maxDays} days per report. Downloads reproduce exactly what is shown.
        </p>
      </div>

      {error && <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}

      <div className="rounded-xl border bg-white p-5 shadow-sm">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Province</label>
            <select className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2" value={provinceLabel} onChange={(e) => setProvinceLabel(e.target.value)} disabled={loadingMeta}>
              <option value="">{loadingMeta ? 'Loading…' : 'Select…'}</option>
              {provinces.map((p) => <option key={p.label} value={p.label}>{p.label}</option>)}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">City</label>
            <select className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 disabled:bg-slate-50 disabled:text-slate-400" value={city} onChange={(e) => setCity(e.target.value)} disabled={!selectedProvince || cities.length === 0}>
              <option value="">{!selectedProvince ? 'Select a province first' : cities.length ? 'Select…' : 'No cities with active stations'}</option>
              {cities.map((c) => <option key={c.city} value={c.city}>{c.city} ({c.station_count} station{c.station_count === 1 ? '' : 's'})</option>)}
            </select>
          </div>

          <div className="md:col-span-2">
            <div className="flex items-center justify-between mb-1">
              <label className="block text-sm font-medium text-slate-700">What to report</label>
              <div className="flex gap-1 text-xs">
                <button type="button" onClick={() => setMode('stations')} className={`px-3 py-1 rounded-full border ${mode === 'stations' ? 'bg-slate-800 text-white border-slate-800' : 'hover:bg-slate-50'}`}>Individual stations</button>
                <button type="button" onClick={() => setMode('city')} className={`px-3 py-1 rounded-full border ${mode === 'city' ? 'bg-slate-800 text-white border-slate-800' : 'hover:bg-slate-50'}`}>City summary (mean of stations)</button>
              </div>
            </div>
            {mode === 'stations' ? (
              <div className="rounded-lg border max-h-56 overflow-y-auto divide-y">
                {!city && <div className="p-3 text-sm text-slate-400">Select a city to list its stations.</div>}
                {city && stations.length === 0 && <div className="p-3 text-sm text-slate-400">No active stations with recent data in {city}.</div>}
                {stations.map((s) => (
                  <label key={s.station_id} className="flex items-center gap-3 px-3 py-2 text-sm hover:bg-slate-50 cursor-pointer">
                    <input type="checkbox" checked={stationIds.includes(s.station_id)} onChange={() => toggleStation(s.station_id)} disabled={!stationIds.includes(s.station_id) && stationIds.length >= LIMITS.maxStations} />
                    <span className="flex-1 min-w-0">
                      <span className="text-slate-800">{s.station_name}</span>
                      {s.duplicate_name && <span className="ml-1 text-[10px] text-amber-600">(same name as another station)</span>}
                      <span className="block text-[11px] text-slate-400">
                        {s.provider || 'unknown provider'} · id {s.station_id} · last reading {s.last_observation ? formatPkt(s.last_observation) : 'none in 30 days'}
                        {s.last_pm25 != null && <> · {Math.round(s.last_pm25)} µg/m³ ({classifyPm25(s.last_pm25).shortLabel})</>}
                      </span>
                    </span>
                  </label>
                ))}
                {stations.length > 0 && (
                  <div className="px-3 py-1.5 text-[11px] text-slate-400 flex justify-between">
                    <span>{stationIds.length} of {stations.length} selected (max {LIMITS.maxStations})</span>
                    <button type="button" className="underline" onClick={() => setStationIds(stations.slice(0, LIMITS.maxStations).map((s) => s.station_id))}>Select first {Math.min(LIMITS.maxStations, stations.length)}</button>
                  </div>
                )}
              </div>
            ) : (
              <div className="rounded-lg border p-3 text-sm text-slate-600">
                One row per hour: the unweighted mean of PM2.5 across the stations in {city || 'the city'} that reported that hour, with the count of stations used. Not an area or population average.
              </div>
            )}
          </div>

          {mode === 'stations' && (
            <div className="md:col-span-2">
              <label className="block text-sm font-medium text-slate-700 mb-1">Parameters</label>
              <div className="flex flex-wrap gap-3 rounded-lg border p-3 text-sm">
                {POLLUTANTS.map((p) => (
                  <label key={p.key} className="flex items-center gap-1.5">
                    <input type="checkbox" checked={parameters.includes(p.key)} onChange={(e) => setParameters((prev) => e.target.checked ? [...prev, p.key] : prev.filter((x) => x !== p.key))} />
                    {p.label} <span className="text-slate-400 text-xs">{p.unit}</span>
                  </label>
                ))}
              </div>
              <p className="text-[11px] text-slate-400 mt-1">Most stations report PM2.5 only; other columns are empty where the monitor does not measure them.</p>
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">From (Pakistan time)</label>
            <div className="flex gap-2">
              <input type="date" className="flex-1 rounded-lg border px-3 py-2" value={startDate} max={today} onChange={(e) => setStartDate(e.target.value)} />
              <input type="time" className="w-28 rounded-lg border px-3 py-2" value={startTime} onChange={(e) => setStartTime(e.target.value)} />
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">To (Pakistan time, exclusive)</label>
            <div className="flex gap-2">
              <input type="date" className="flex-1 rounded-lg border px-3 py-2" value={endDate} max={today} onChange={(e) => setEndDate(e.target.value)} />
              <input type="time" className="w-28 rounded-lg border px-3 py-2" value={endTime} onChange={(e) => setEndTime(e.target.value)} />
            </div>
          </div>
        </div>

        <div className="mt-5 flex items-center gap-4">
          <button type="button" className="px-6 py-2 rounded-lg bg-slate-800 text-white font-medium disabled:opacity-50" disabled={!!validation || loading} onClick={submit}>
            {loading ? 'Loading…' : 'Run report'}
          </button>
          {validation && <span className="text-sm text-slate-500 flex items-center gap-1"><Info size={14} /> {validation}</span>}
        </div>
      </div>

      {report && <ReportResults report={report} view={view} setView={setView} />}
    </div>
  )
}

function ReportResults({ report, view, setView }: { report: Report; view: 'table' | 'chart'; setView: (v: 'table' | 'chart') => void }) {
  const filename = report.kind === 'stations'
    ? `hawanama_stations_${report.meta.start_pk.slice(0, 10)}_${report.meta.end_pk.slice(0, 10)}.csv`
    : `hawanama_${report.meta.city.toLowerCase()}_mean_${report.meta.start_utc.slice(0, 10)}_${report.meta.end_utc.slice(0, 10)}.csv`

  // Series: one per station (first parameter), or the city mean
  const series = useMemo(() => {
    if (report.kind === 'city') return [{ key: 'city', name: `${report.meta.city} reporting-station mean`, points: report.rows.map((r) => ({ t: r.timestamp_pk, v: r.pm25 })) }]
    const param = report.meta.parameters[0]
    return report.meta.stations.map((s) => ({
      key: s.station_id,
      name: s.name,
      points: report.rows.filter((r) => r.station_id === s.station_id).map((r) => ({ t: r.timestamp_pk, v: r[param] as number | null })),
    }))
  }, [report])

  const expected = report.kind === 'stations' ? report.meta.expected_hours_per_station : Math.max(1, Math.round((new Date(report.meta.end_utc).getTime() - new Date(report.meta.start_utc).getTime()) / 3_600_000))

  const chartData = useMemo(() => {
    const byT = new Map<string, Record<string, number | string | null>>()
    for (const s of series) for (const p of s.points) {
      const row = byT.get(p.t) ?? { t: p.t }
      row[s.key] = p.v
      byT.set(p.t, row)
    }
    return Array.from(byT.values()).sort((a, b) => String(a.t).localeCompare(String(b.t)))
  }, [series])

  const unit = report.kind === 'stations' ? report.meta.units[report.meta.parameters[0]] : 'µg/m³'
  const paramLabel = report.kind === 'stations' ? (POLLUTANTS.find((p) => p.key === report.meta.parameters[0])?.label ?? report.meta.parameters[0]) : 'PM2.5'

  return (
    <div className="mt-6">
      <div className="flex flex-wrap items-center gap-3 mb-3">
        <h2 className="text-lg font-semibold text-slate-900">Results</h2>
        <div className="flex gap-1 text-xs">
          <button type="button" onClick={() => setView('table')} className={`px-3 py-1 rounded-full border ${view === 'table' ? 'bg-slate-800 text-white border-slate-800' : 'hover:bg-slate-50'}`}>Table</button>
          <button type="button" onClick={() => setView('chart')} className={`px-3 py-1 rounded-full border ${view === 'chart' ? 'bg-slate-800 text-white border-slate-800' : 'hover:bg-slate-50'}`}>Chart</button>
        </div>
        <button type="button" onClick={() => downloadCsv(filename, reportToCsv(report))} className="ml-auto flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-sm hover:bg-slate-50">
          <Download size={14} /> Download CSV
        </button>
      </div>

      <div className="text-xs text-slate-500 mb-3">
        {report.kind === 'stations' ? (
          <>Interval {report.meta.start_pk.replace('T', ' ').slice(0, 16)} to {report.meta.end_pk.replace('T', ' ').slice(0, 16)} PKT · {report.meta.aggregation} · {report.meta.row_count} rows{report.meta.truncated ? ' (truncated by the server limit)' : ''}</>
        ) : (
          <>Interval {formatPkt(report.meta.start_utc)} to {formatPkt(report.meta.end_utc)} · {report.meta.aggregation} · {report.meta.stations_in_scope} stations in scope</>
        )}
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2 mb-4">
        {series.map((s) => {
          const st = seriesStats(s.points.map((p) => p.v), expected)
          return (
            <div key={s.key} className="rounded-lg border bg-white px-3 py-2 text-xs">
              <div className="font-medium text-slate-800 truncate">{s.name}</div>
              <div className="text-slate-500 mt-0.5">
                mean {st.mean != null ? st.mean.toFixed(1) : '—'} · median {st.median != null ? st.median.toFixed(1) : '—'} · min {st.min ?? '—'} · max {st.max ?? '—'} {unit}
              </div>
              <div className="text-slate-400">{st.n} valid of {expected} hours ({Math.round(st.completeness * 100)}% complete){st.mean != null && <> · {classifyPm25(st.mean).label}</>}</div>
            </div>
          )
        })}
      </div>

      {view === 'chart' ? (
        <div className="rounded-xl border bg-white p-4 shadow-sm" style={{ height: 380 }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ top: 10, right: 20, left: 0, bottom: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="t" tickFormatter={(t: string) => t.slice(5, 16).replace('T', ' ')} fontSize={11} minTickGap={40} />
              <YAxis fontSize={11} label={{ value: `${paramLabel} (${unit})`, angle: -90, position: 'insideLeft', fontSize: 11 }} />
              <Tooltip labelFormatter={(t) => `${String(t).replace('T', ' ').slice(0, 16)} PKT`} formatter={(v) => [v == null ? '—' : `${Number(v).toFixed(1)} ${unit}`]} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              {series.map((s, i) => (
                <Line key={s.key} type="monotone" dataKey={s.key} name={s.name} stroke={SERIES_COLORS[i % SERIES_COLORS.length]} dot={false} strokeWidth={1.5} connectNulls={false} isAnimationActive={false} />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <div className="rounded-xl border bg-white shadow-sm overflow-auto max-h-[560px]">
          <table className="min-w-full text-xs">
            <thead className="bg-slate-50 sticky top-0">
              <tr className="text-left text-slate-500">
                {report.kind === 'stations' && <th className="px-3 py-2">Station</th>}
                <th className="px-3 py-2">Time (PKT)</th>
                {report.kind === 'stations'
                  ? report.meta.parameters.map((p) => <th key={p} className="px-3 py-2">{POLLUTANTS.find((x) => x.key === p)?.label ?? p} ({report.meta.units[p]})</th>)
                  : <><th className="px-3 py-2">PM2.5 mean (µg/m³)</th><th className="px-3 py-2">Stations used</th></>}
                {report.kind === 'stations' && <th className="px-3 py-2">QC</th>}
              </tr>
            </thead>
            <tbody>
              {report.rows.length === 0 && (
                <tr><td className="px-3 py-6 text-slate-400" colSpan={6}>No readings in this interval.</td></tr>
              )}
              {report.kind === 'stations'
                ? report.rows.map((r, i) => (
                  <tr key={i} className="border-t border-slate-100">
                    <td className="px-3 py-1.5 text-slate-700 whitespace-nowrap">{r.station_name}</td>
                    <td className="px-3 py-1.5 text-slate-500 whitespace-nowrap">{r.timestamp_pk.replace('T', ' ').slice(0, 16)}</td>
                    {report.meta.parameters.map((p) => <td key={p} className="px-3 py-1.5 tabular-nums">{r[p] == null ? '—' : Number(r[p]).toFixed(1)}</td>)}
                    <td className="px-3 py-1.5 text-slate-400">{r.qc_state}</td>
                  </tr>
                ))
                : report.rows.map((r, i) => (
                  <tr key={i} className="border-t border-slate-100">
                    <td className="px-3 py-1.5 text-slate-500 whitespace-nowrap">{r.timestamp_pk.replace('T', ' ').slice(0, 16)}</td>
                    <td className="px-3 py-1.5 tabular-nums">{r.pm25.toFixed(1)}</td>
                    <td className="px-3 py-1.5 text-slate-400">{r.stations_used}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
