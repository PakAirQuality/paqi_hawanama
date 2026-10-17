'use client'

import { useState, useMemo, useRef, useEffect } from 'react'
import { classifyPm25, pm25Color } from '@/lib/aqi'
import { useQuery } from '@tanstack/react-query'
import { ChevronRight, ChevronLeft, Search, MapPin } from 'lucide-react'
import { SatelliteImage } from '@/components/shared/SatelliteImage'

// ── Category icons (Google Material Symbols, weight 300, filled) ──
const CATEGORY_ICONS: Record<string, React.ReactNode> = {
  stations: (
    <svg className="w-[18px] h-[18px]" viewBox="0 -960 960 960" fill="currentColor">
      <path d="M80-160v-80h800v80H80Zm80-160v-320h80v320H160Zm200 0v-480h80v480H360Zm200 0v-240h80v240H560Zm200 0v-400h80v400H760Z" />
    </svg>
  ),
  kilns: (
    <svg className="w-[18px] h-[18px]" viewBox="0 -960 960 960" fill="currentColor">
      <path d="M80-80v-80h80v-560q0-33 23.5-56.5T240-800h200v-80h80v80h200q33 0 56.5 23.5T800-720v560h80v80H80Zm240-240h80v-240h-80v240Zm200 0h80v-240h-80v240Z" />
    </svg>
  ),
  power_plants: (
    <svg className="w-[18px] h-[18px]" viewBox="0 -960 960 960" fill="currentColor">
      <path d="M280-80v-200H80l200-280v200h200L280-80Zm222-280 58-120H440l200-400v280h120L560-360Z" />
    </svg>
  ),
  cement_plants: (
    <svg className="w-[18px] h-[18px]" viewBox="0 -960 960 960" fill="currentColor">
      <path d="M80-80v-400l280-120v-280h240v160h280v640H80Zm80-80h640v-480H520v-160H440v280L160-400v240Zm160-80h80v-160h-80v160Zm160 0h80v-160h-80v160Zm160 0h80v-160h-80v160ZM160-160h640-640Z" />
    </svg>
  ),
  steel_sites: (
    <svg className="w-[18px] h-[18px]" viewBox="0 -960 960 960" fill="currentColor">
      <path d="M40-120v-80h880v80H40Zm120-120v-280l200-200 200 200v280H160Zm80-80h80v-120h-80v120Zm0-200h240L400-600l-80 80h-80Zm320 280v-440l200-200 200 200v440H560Zm80-80h80v-120h-80v120Zm0-200h240L800-600l-80 80h-80Z" />
    </svg>
  ),
  sugar_mills: (
    <svg className="w-[18px] h-[18px]" viewBox="0 -960 960 960" fill="currentColor">
      <path d="M480-80q-82 0-155-31.5t-127.5-86Q143-252 111.5-325T80-480q0-83 31.5-155.5t86-127Q252-817 325-848.5T480-880q83 0 155.5 31.5t127 86q54.5 54.5 86 127T880-480q0 82-31.5 155t-86 127.5q-54.5 54.5-127 86T480-80Zm0-80q134 0 227-93t93-227q0-134-93-227t-227-93q-134 0-227 93t-93 227q0 134 93 227t227 93Zm0-120q-100 0-170-70t-70-170q0-100 70-170t170-70q100 0 170 70t70 170q0 100-70 170t-170 70Zm0-80q66 0 113-47t47-113q0-66-47-113t-113-47q-66 0-113 47t-47 113q0 66 47 113t113 47Z" />
    </svg>
  ),
  industrial_sites: (
    <svg className="w-[18px] h-[18px]" viewBox="0 -960 960 960" fill="currentColor">
      <path d="M80-160v-320l240-160v80l160-120v80l160-120v560H80Zm560 0v-560h240v560H640Zm-480-80h80v-80h-80v80Zm0-160h80v-80h-80v80Zm160 160h80v-80h-80v80Zm0-160h80v-80h-80v80Zm160 160h80v-80h-80v80Zm0-160h80v-80h-80v80Zm160 160h80v-80h-80v80Zm0-160h80v-80h-80v80Z" />
    </svg>
  ),
  mines_quarries: (
    <svg className="w-[18px] h-[18px]" viewBox="0 -960 960 960" fill="currentColor">
      <path d="m80-80 200-560 160 160-320 400Zm534-134L440-388l76-218 240 240-142 112ZM440-600l-80-80 200-200h240v240L600-440l-80-80 120-120h-80L440-600Z" />
    </svg>
  ),
}

const CATEGORY_COLORS: Record<string, string> = {
  stations: '#059669',
  kilns: '#d97706',
  power_plants: '#ef4444',
  cement_plants: '#8b5cf6',
  steel_sites: '#6366f1',
  sugar_mills: '#10b981',
  industrial_sites: '#64748b',
  mines_quarries: '#78716c',
}

interface StationItem {
  name: string
  city: string
  pm25: number
  lat: number
  lon: number
  station_id?: string
  network?: string
}

interface KilnItem {
  id: string
  state: string
  district?: string
  fuel: string
  pm25_t_yr: number
  pm10_t_yr?: number
  so2_t_yr?: number
  capacity_tonnes: string
  lat: number
  lon: number
}

interface IndustryItem {
  name: string
  type?: string
  fuel?: string
  capacity_mw?: number
  capacity_mtpa?: number
  province?: string
  district?: string
  lat: number
  lon: number
}

interface IndustryCategory {
  key: string
  label: string
  color: string
  items: IndustryItem[]
}

export interface StructuresTabProps {
  stations: StationItem[]
  kilns: KilnItem[]
  industryCategories: IndustryCategory[]
  selectedDate: string | null
  onFlyTo: (lng: number, lat: number, zoom?: number) => void
  initialView?: 'stations' | 'sources'
}

// Health classification: one implementation for the whole dashboard (lib/aqi)
function pm25ToBandColor(pm25: number): string {
  return pm25Color(pm25)
}

const API_BASE = "https://hawanama-152782825429.asia-south1.run.app"

// ── PM2.5 bar color (same categories as the markers) ──
function pm25BarColor(v: number): string {
  return pm25Color(v)
}

// ── Canvas bar chart for 24h PM2.5 ──
function PM25BarChart({ data }: { data: { hour: string; pm25: number | null }[] }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const dpr = window.devicePixelRatio || 1
    const W = canvas.clientWidth
    const H = canvas.clientHeight
    canvas.width = W * dpr
    canvas.height = H * dpr
    ctx.scale(dpr, dpr)

    const pad = { top: 12, right: 32, bottom: 24, left: 4 }
    const w = W - pad.left - pad.right
    const h = H - pad.top - pad.bottom

    const validVals = data.filter(d => d.pm25 != null).map(d => d.pm25!)
    if (!validVals.length) {
      ctx.fillStyle = '#94a3b8'
      ctx.font = '11px system-ui'
      ctx.textAlign = 'center'
      ctx.fillText('No data', W / 2, H / 2)
      return
    }

    const maxVal = Math.ceil(Math.max(...validVals, 20) / 10) * 10
    const barW = Math.max(4, (w / data.length) - 2)
    const gap = (w - barW * data.length) / data.length

    // Grid lines
    ctx.strokeStyle = '#cbd5e1'
    ctx.lineWidth = 0.8
    ctx.setLineDash([4, 3])
    const gridSteps = [0, Math.round(maxVal * 0.33), Math.round(maxVal * 0.66), maxVal]
    for (const v of gridSteps) {
      const y = pad.top + h - (v / maxVal) * h
      ctx.beginPath()
      ctx.moveTo(pad.left, y)
      ctx.lineTo(pad.left + w, y)
      ctx.stroke()
      // Y-axis label
      ctx.fillStyle = '#94a3b8'
      ctx.font = '9px system-ui'
      ctx.textAlign = 'left'
      ctx.fillText(String(v), pad.left + w + 4, y + 3)
    }
    ctx.setLineDash([])

    // Bars
    for (let i = 0; i < data.length; i++) {
      const d = data[i]
      const x = pad.left + i * (barW + gap) + gap / 2
      if (d.pm25 == null) continue
      const barH = (d.pm25 / maxVal) * h
      const y = pad.top + h - barH

      ctx.fillStyle = pm25BarColor(d.pm25)
      const r = Math.min(2, barW / 2)
      ctx.beginPath()
      ctx.moveTo(x, y + r)
      ctx.quadraticCurveTo(x, y, x + r, y)
      ctx.lineTo(x + barW - r, y)
      ctx.quadraticCurveTo(x + barW, y, x + barW, y + r)
      ctx.lineTo(x + barW, pad.top + h)
      ctx.lineTo(x, pad.top + h)
      ctx.closePath()
      ctx.fill()
    }

    // X-axis labels (show every ~6 hours)
    ctx.fillStyle = '#94a3b8'
    ctx.font = '9px system-ui'
    ctx.textAlign = 'center'
    const step = Math.max(1, Math.floor(data.length / 5))
    for (let i = 0; i < data.length; i += step) {
      const x = pad.left + i * (barW + gap) + gap / 2 + barW / 2
      ctx.fillText(data[i].hour, x, pad.top + h + 14)
    }
  }, [data])

  return <canvas ref={canvasRef} className="w-full" style={{ height: 140 }} />
}

// ── Esri satellite image for station location ──
// SatelliteImage imported from @/components/shared/SatelliteImage

type View =
  | { type: 'categories' }
  | { type: 'stations' }
  | { type: 'station-detail'; station: StationItem }
  | { type: 'kilns' }
  | { type: 'kiln-detail'; kiln: KilnItem }
  | { type: 'industry'; categoryKey: string }
  | { type: 'industry-detail'; item: IndustryItem; categoryKey: string }

export function StructuresTab({ stations, kilns, industryCategories, selectedDate, onFlyTo, initialView }: StructuresTabProps) {
  const [view, setView] = useState<View>(initialView === 'stations' ? { type: 'stations' } : initialView === 'sources' ? { type: 'categories' } : { type: 'categories' })
  const [search, setSearch] = useState('')
  const [sortBy, setSortBy] = useState<'pm25' | 'name' | 'city' | 'network'>('pm25')
  const [kilnSort, setKilnSort] = useState<'province' | 'district' | 'id'>('province')
  const [kilnLimit, setKilnLimit] = useState(200)
  const [industrySort, setIndustrySort] = useState<'province' | 'district' | 'type' | 'name'>('province')
  const [industryLimit, setIndustryLimit] = useState(200)

  // ── Derived data ──
  const kilnsByProvince = useMemo(() => {
    const map: Record<string, KilnItem[]> = {}
    for (const k of kilns) {
      ;(map[k.state] ??= []).push(k)
    }
    return Object.entries(map)
      .map(([province, items]) => ({ province, items, count: items.length }))
      .sort((a, b) => b.count - a.count)
  }, [kilns])

  const sortedKilns = useMemo(() => {
    const list = [...kilns]
    const majorProvinces = ['Punjab', 'Sindh', 'Khyber-Pakhtunkhwa', 'Balochistan', 'Islamabad', 'Azad Kashmir']
    const provRank = (s: string) => { const idx = majorProvinces.indexOf(s); return idx >= 0 ? idx : 999 }
    if (kilnSort === 'province') list.sort((a, b) => provRank(a.state) - provRank(b.state) || a.state.localeCompare(b.state) || a.id.localeCompare(b.id))
    else if (kilnSort === 'district') {
      const majorDistricts = ['Lahore', 'Kasur', 'Sheikhupura', 'Faisalabad', 'Multan', 'Rawalpindi', 'Gujranwala', 'Sargodha']
      const distRank = (d: string) => { const idx = majorDistricts.indexOf(d); return idx >= 0 ? idx : 999 }
      list.sort((a, b) => distRank(a.district || '') - distRank(b.district || '') || (a.district || 'zzz').localeCompare(b.district || 'zzz') || a.id.localeCompare(b.id))
    }
    else list.sort((a, b) => a.id.localeCompare(b.id))
    return list
  }, [kilns, kilnSort])

  const networkGroup = (n?: string) => n === 'Punjab EPA' ? 'Punjab AQMS' : 'Low-cost Sensors'

  const sortedStations = useMemo(() => {
    const list = [...stations]
    if (sortBy === 'pm25') list.sort((a, b) => b.pm25 - a.pm25)
    else if (sortBy === 'name') list.sort((a, b) => a.name.localeCompare(b.name))
    else if (sortBy === 'city') {
      const majorCities = ['Lahore', 'Karachi', 'Islamabad', 'Rawalpindi', 'Faisalabad', 'Peshawar', 'Multan', 'Quetta']
      const cityRank = (c: string) => { const idx = majorCities.indexOf(c); return idx >= 0 ? idx : 999 }
      list.sort((a, b) => cityRank(a.city) - cityRank(b.city) || a.city.localeCompare(b.city) || b.pm25 - a.pm25)
    } else if (sortBy === 'network') {
      // Punjab AQMS first, then low-cost
      list.sort((a, b) => {
        const ga = networkGroup(a.network)
        const gb = networkGroup(b.network)
        if (ga !== gb) return ga === 'Punjab AQMS' ? -1 : 1
        return (a.network || '').localeCompare(b.network || '') || b.pm25 - a.pm25
      })
    }
    return list
  }, [stations, sortBy])

  // ── Search filter ──
  const filterBySearch = <T extends { name?: string; city?: string; id?: string; state?: string }>(items: T[]) => {
    if (!search.trim()) return items
    const q = search.toLowerCase()
    return items.filter(item =>
      (item.name?.toLowerCase().includes(q)) ||
      (item.city?.toLowerCase().includes(q)) ||
      (item.id?.toLowerCase().includes(q)) ||
      (item.state?.toLowerCase().includes(q))
    )
  }

  // ── Back button ──
  const BackButton = ({ label, onClick }: { label: string; onClick: () => void }) => (
    <button
      onClick={onClick}
      className="flex items-center gap-1 px-5 py-3 text-[12px] font-medium text-slate-400 hover:text-slate-600 transition-colors w-full"
    >
      <ChevronLeft size={14} strokeWidth={2} /> {label}
    </button>
  )

  // ── Categories view (home) ──
  if (view.type === 'categories') {
    const CategoryRow = ({ onClick, color, icon, label, sub }: { onClick: () => void; color: string; icon: React.ReactNode; label: string; sub: string }) => (
      <button
        onClick={onClick}
        className="w-full flex items-center gap-3.5 px-4 py-3.5 rounded-xl border border-slate-100 bg-white hover:border-slate-200 hover:shadow-sm transition-all text-left group"
      >
        <div className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0"
          style={{ background: color + '14', color }}>
          {icon}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-[13px] font-semibold text-[#1e293b]">{label}</div>
          <div className="text-[11px] text-[#94a3b8] mt-0.5">{sub}</div>
        </div>
        <ChevronRight size={15} className="text-slate-200 group-hover:text-slate-400 transition-colors" />
      </button>
    )

    return (
      <div className="flex flex-col h-full bg-[#fafbfc]">
        <div className="px-5 pt-5 pb-3">
          <h3 className="text-[13px] font-semibold text-[#1e293b] tracking-[-0.01em]">
            Emission Sources
          </h3>
          <p className="text-[11px] text-[#94a3b8] mt-0.5">Browse kilns & industry</p>
        </div>
        <div className="flex-1 overflow-y-auto scrollbar-hide px-3 pb-4 space-y-2">
          <CategoryRow
            onClick={() => setView({ type: 'kilns' })}
            color={CATEGORY_COLORS.kilns}
            icon={CATEGORY_ICONS.kilns}
            label="Brick Kilns"
            sub={`${kilns.length.toLocaleString()} geolocated kilns`}
          />
          {industryCategories.map(cat => (
            <CategoryRow
              key={cat.key}
              onClick={() => setView({ type: 'industry', categoryKey: cat.key })}
              color={CATEGORY_COLORS[cat.key] || cat.color}
              icon={CATEGORY_ICONS[cat.key] || (
                <svg className="w-[18px] h-[18px]" viewBox="0 -960 960 960" fill="currentColor">
                  <path d="M480-480q-66 0-113-47t-47-113q0-66 47-113t113-47q66 0 113 47t47 113q0 66-47 113t-113 47ZM160-160v-112q0-34 17.5-62.5T224-378q62-31 126-46.5T480-440q66 0 130 15.5T736-378q29 15 46.5 43.5T800-272v112H160Z" />
                </svg>
              )}
              label={cat.label}
              sub={`${cat.items.length} sites`}
            />
          ))}
        </div>
      </div>
    )
  }

  // ── Stations list ──
  if (view.type === 'stations') {
    const filtered = filterBySearch(sortedStations)
    return (
      <div className="flex flex-col h-full bg-[#fafbfc]">
        {initialView !== 'stations' && (
          <BackButton label="All Sources" onClick={() => { setView({ type: 'categories' }); setSearch(''); setSortBy('pm25') }} />
        )}
        {initialView === 'stations' && (
          <div className="px-5 pt-5 pb-1">
            <h3 className="text-[13px] font-semibold text-[#1e293b] tracking-[-0.01em]">Monitoring Stations</h3>
            <p className="text-[11px] text-[#94a3b8] mt-0.5">{stations.length} stations reporting</p>
          </div>
        )}
        {/* Search + sort */}
        <div className="px-4 pb-3 flex items-center gap-2">
          <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-white border border-slate-200/80 flex-1 min-w-0">
            <Search size={14} className="text-slate-300 shrink-0" />
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search stations..."
              className="flex-1 text-[12px] bg-transparent outline-none text-slate-700 placeholder:text-slate-400"
            />
          </div>
          <select
            value={sortBy}
            onChange={e => setSortBy(e.target.value as 'pm25' | 'name' | 'city' | 'network')}
            className="text-[11px] text-slate-500 bg-white border border-slate-200/80 rounded-xl px-2.5 py-2 outline-none shrink-0"
          >
            <option value="pm25">PM2.5 (highest first)</option>
            <option value="city">City</option>
            <option value="network">Network</option>
            <option value="name">A → Z</option>
          </select>
        </div>
        <div className="px-5 pb-2 text-[10px] font-medium text-[#94a3b8]">
          {filtered.length} stations
        </div>
        <div className="flex-1 overflow-y-auto scrollbar-hide">
          {filtered.map((s, i) => {
            const showCityHeader = sortBy === 'city' && (i === 0 || filtered[i - 1].city !== s.city)
            const showNetworkHeader = sortBy === 'network' && (i === 0 || networkGroup(filtered[i - 1].network) !== networkGroup(s.network))
            const netGroup = networkGroup(s.network)
            const netCount = sortBy === 'network' && showNetworkHeader ? filtered.filter(x => networkGroup(x.network) === netGroup).length : 0
            return (
              <div key={`${s.name}-${i}`}>
                {showCityHeader && (
                  <div className="px-3 pt-2.5 pb-1 text-[10px] font-semibold text-slate-500 uppercase tracking-wide bg-slate-50/80 sticky top-0">
                    {s.city}
                  </div>
                )}
                {showNetworkHeader && (
                  <div className="px-3 pt-3 pb-1.5 bg-slate-50/80 sticky top-0 border-b border-slate-100">
                    <div className="text-[10px] font-bold text-slate-600 uppercase tracking-wide">{netGroup}</div>
                    <div className="text-[9.5px] text-slate-400 mt-0.5">{netCount} stations</div>
                  </div>
                )}
                <button
                  onClick={() => {
                    onFlyTo(s.lon, s.lat, 14)
                    setView({ type: 'station-detail', station: s })
                  }}
                  className="w-full flex items-center gap-3 px-3 py-2.5 hover:bg-slate-50 transition-colors text-left border-b border-slate-100/80"
                >
                  {/* AQI badge */}
                  <div
                    className="shrink-0 flex items-center justify-center rounded-full"
                    style={{
                      width: 32,
                      height: 32,
                      background: pm25ToBandColor(s.pm25),
                      border: '2px solid rgba(255,255,255,0.9)',
                      boxShadow: `0 0 0 1px ${pm25ToBandColor(s.pm25)}30, 0 1px 3px rgba(0,0,0,0.1)`,
                    }}
                  >
                    <span className="text-[11px] font-bold text-white leading-none">{Math.round(s.pm25)}</span>
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-[12px] font-semibold text-slate-800 truncate">{s.name}</div>
                    {sortBy !== 'city' && <div className="text-[10.5px] text-slate-400 truncate">{s.city}</div>}
                  </div>
                  <svg className="w-4 h-4 text-slate-300 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="9 18 15 12 9 6" />
                  </svg>
                </button>
              </div>
            )
          })}
        </div>
      </div>
    )
  }

  // ── Station Detail ──
  if (view.type === 'station-detail') {
    return (
      <StationDetailView
        station={view.station}
        selectedDate={selectedDate}
        onBack={() => setView({ type: 'stations' })}
        onFlyTo={onFlyTo}
      />
    )
  }

  // ── Brick Kilns ──
  if (view.type === 'kilns') {
    const searched = filterBySearch(sortedKilns)
    return (
      <div className="flex flex-col h-full">
        <BackButton label="All Sources" onClick={() => { setView({ type: 'categories' }); setSearch(''); setKilnSort('province') }} />
        <div className="px-3 py-2 border-b border-slate-100 flex items-center gap-2">
          <div className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-slate-50 border border-slate-200 flex-1 min-w-0">
            <Search size={13} className="text-slate-400 shrink-0" />
            <input
              value={search}
              onChange={e => { setSearch(e.target.value); setKilnLimit(200) }}
              placeholder="Search kilns..."
              className="flex-1 text-xs bg-transparent outline-none text-slate-700 placeholder:text-slate-400"
            />
          </div>
          <select
            value={kilnSort}
            onChange={e => { setKilnSort(e.target.value as 'province' | 'district' | 'id'); setKilnLimit(200) }}
            className="text-[10px] text-slate-600 bg-slate-50 border border-slate-200 rounded-lg px-2 py-1.5 outline-none shrink-0"
          >
            <option value="province">Province</option>
            <option value="district">District</option>
            <option value="id">A → Z</option>
          </select>
        </div>
        <div className="px-3 py-1 text-[10px] text-slate-400 border-b border-slate-50">
          {searched.length.toLocaleString()} kilns
        </div>
        <div className="flex-1 overflow-y-auto scrollbar-hide">
          {searched.slice(0, kilnLimit).map((k, i) => {
            const prev = i > 0 ? searched[i - 1] : null
            const showHeader = kilnSort === 'province'
              ? (i === 0 || prev?.state !== k.state)
              : kilnSort === 'district'
                ? (i === 0 || prev?.district !== k.district)
                : false
            const headerLabel = kilnSort === 'province' ? k.state : kilnSort === 'district' ? (k.district || 'Unknown') : ''
            // Compute group stats for subheading
            let groupStats = ''
            if (showHeader && (kilnSort === 'province' || kilnSort === 'district')) {
              const groupKey = kilnSort === 'province' ? 'state' : 'district'
              const groupVal = kilnSort === 'province' ? k.state : (k.district || 'Unknown')
              const group = searched.filter(x => (kilnSort === 'province' ? x.state : (x.district || 'Unknown')) === groupVal)
              const fuelCounts: Record<string, number> = {}
              for (const item of group) { fuelCounts[item.fuel] = (fuelCounts[item.fuel] || 0) + 1 }
              const parts = Object.entries(fuelCounts).sort((a, b) => b[1] - a[1]).map(([f, c]) => `${c} ${f}`)
              groupStats = `${group.length} kilns · ${parts.join(' · ')}`
            }
            return (
              <div key={k.id}>
                {showHeader && (
                  <div className="px-3 pt-3 pb-1.5 bg-slate-50/80 sticky top-0 border-b border-slate-100">
                    <div className="text-[10px] font-bold text-slate-600 uppercase tracking-wide">{headerLabel}</div>
                    {groupStats && <div className="text-[9.5px] text-slate-400 mt-0.5">{groupStats}</div>}
                  </div>
                )}
                <button
                  onClick={() => {
                    onFlyTo(k.lon, k.lat, 16)
                    setView({ type: 'kiln-detail', kiln: k })
                  }}
                  className="w-full flex items-center gap-3 px-3 py-2.5 hover:bg-slate-50 transition-colors text-left border-b border-slate-100/80"
                >
                  {/* Chimney badge */}
                  <div className="shrink-0 flex items-center justify-center w-8 h-8 rounded-lg bg-amber-600 shadow-sm">
                    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="18" viewBox="0 0 24 28">
                      <rect x="8" y="6" width="8" height="16" rx="1" fill="white" opacity="0.9"/>
                      <rect x="6.5" y="4" width="11" height="3" rx="1" fill="white"/>
                      <rect x="5" y="22" width="14" height="4" rx="1" fill="white" opacity="0.7"/>
                      <circle cx="12" cy="2.5" r="2" fill="white" opacity="0.5"/>
                      <circle cx="15" cy="1.5" r="1.5" fill="white" opacity="0.35"/>
                      <circle cx="9.5" cy="1" r="1.2" fill="white" opacity="0.25"/>
                    </svg>
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-[12px] font-semibold text-slate-800">{k.id}</div>
                    <div className="text-[10.5px] text-slate-400 capitalize">{k.fuel}</div>
                  </div>
                  <div className="text-[11px] text-slate-400 shrink-0 capitalize">{k.fuel}</div>
                </button>
              </div>
            )
          })}
          {searched.length > kilnLimit && (
            <button
              onClick={() => setKilnLimit(prev => prev + 200)}
              className="w-full px-3 py-3 text-[11px] font-medium text-amber-600 hover:bg-amber-50 transition-colors text-center border-t border-slate-100"
            >
              Load more ({(searched.length - kilnLimit).toLocaleString()} remaining)
            </button>
          )}
        </div>
      </div>
    )
  }

  // ── Kiln Detail ──
  if (view.type === 'kiln-detail') {
    const k = view.kiln
    return (
      <div className="flex flex-col h-full bg-[#fafbfc]">
        <button
          onClick={() => { setView({ type: 'kilns' }) }}
          className="flex items-center gap-1 px-5 py-3 text-[12px] font-medium text-slate-400 hover:text-slate-600 transition-colors w-full"
        >
          <ChevronLeft size={14} strokeWidth={2} /> All Kilns
        </button>
        <div className="flex-1 overflow-y-auto scrollbar-hide">
          {/* Header */}
          <div className="px-5 pb-4">
            <h2 className="text-[20px] font-semibold text-[#1e293b] leading-snug tracking-[-0.01em]">
              {k.id}
            </h2>
            <p className="text-[12px] text-[#94a3b8] mt-1 leading-relaxed">
              {k.district ? `${k.district}, ` : ''}{k.state} &middot; {k.fuel} fuel
            </p>
            <span className="inline-flex items-center mt-2.5 text-[10px] font-semibold uppercase tracking-wide px-2.5 py-[3px] rounded-full bg-amber-50 text-amber-600">
              Brick Kiln
            </span>
          </div>

          {/* Satellite image */}
          <div className="px-4 pb-3">
            <SatelliteImage lat={k.lat} lon={k.lon} name={k.id} zoom="close" label="Kiln location" markerType="chimney" />
          </div>

          {/* Details card */}
          <div className="px-4 pb-4">
            <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
              <div className="px-4 py-2.5 border-b border-slate-100">
                <span className="text-[12px] font-bold text-slate-700">Kiln Details</span>
              </div>
              <div className="px-4 py-3 grid grid-cols-2 gap-x-6 gap-y-2.5 text-[11px]">
                <div><div className="text-slate-400 text-[10px]">Province</div><div className="text-slate-700 font-medium">{k.state}</div></div>
                {k.district && <div><div className="text-slate-400 text-[10px]">District</div><div className="text-slate-700 font-medium">{k.district}</div></div>}
                <div><div className="text-slate-400 text-[10px]">Fuel Type</div><div className="text-slate-700 font-medium">{k.fuel}</div></div>
                <div><div className="text-slate-400 text-[10px]">Capacity</div><div className="text-slate-700 font-medium">{k.capacity_tonnes} tonnes</div></div>
                <div><div className="text-slate-400 text-[10px]">Coordinates</div><div className="text-slate-700 font-medium">{k.lat.toFixed(4)}, {k.lon.toFixed(4)}</div></div>
              </div>
            </div>
          </div>
        </div>
      </div>
    )
  }

  // ── Industry category ──
  if (view.type === 'industry') {
    const cat = industryCategories.find(c => c.key === view.categoryKey)
    if (!cat) return null

    // Effective sort — fall back to 'name' if current sort field doesn't exist
    const effectiveSort = (!hasProvince && industrySort === 'province') || (!hasDistrict && industrySort === 'district') || (!hasType && industrySort === 'type') ? 'name' : industrySort

    // Sort items
    const sortedItems = (() => {
      const list = [...cat.items]
      const majorProvinces = ['Punjab', 'Sindh', 'Khyber Pakhtunkhwa', 'Balochistan', 'Islamabad']
      const provRank = (s: string) => { const idx = majorProvinces.indexOf(s); return idx >= 0 ? idx : 999 }
      if (effectiveSort === 'province') list.sort((a, b) => provRank(a.province || '') - provRank(b.province || '') || (a.province || 'zzz').localeCompare(b.province || 'zzz') || (a.name || '').localeCompare(b.name || ''))
      else if (effectiveSort === 'district') list.sort((a, b) => (a.district || 'zzz').localeCompare(b.district || 'zzz') || (a.name || '').localeCompare(b.name || ''))
      else if (effectiveSort === 'type') list.sort((a, b) => (a.type || 'zzz').localeCompare(b.type || 'zzz') || (a.name || '').localeCompare(b.name || ''))
      else list.sort((a, b) => (a.name || '').localeCompare(b.name || ''))
      return list
    })()

    const filtered = filterBySearch(sortedItems)

    // Category-specific SVG icons (white on colored background)
    const INDUSTRY_ROW_ICONS: Record<string, React.ReactNode> = {
      power_plants: (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
        </svg>
      ),
      cement_plants: (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M2 20h20"/><path d="M5 20V8l4-4v16"/><path d="M9 20V4l5 4v12"/><path d="M14 20V8l5 4v8"/>
        </svg>
      ),
      steel_sites: (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 2v8"/><path d="m4.93 10.93 1.41 1.41"/><path d="M2 18h2"/><path d="M20 18h2"/><path d="m19.07 10.93-1.41 1.41"/><path d="M22 22H2"/><path d="m8 6 4-4 4 4"/><path d="M16 18a4 4 0 0 0-8 0"/>
        </svg>
      ),
      sugar_mills: (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M7 20h10"/><path d="M10 20c5.5-2.5.8-6.4 3-10"/><path d="M9.5 9.4c1.1.8 1.8 2.2 2.3 3.7-2 .4-3.5.4-4.8-.3-1.2-.6-2.3-1.9-3-4.2 2.8-.5 4.4 0 5.5.8z"/><path d="M14.1 6a7 7 0 0 0-1.1 4c1.9-.1 3.3-.6 4.3-1.4 1-1 1.6-2.3 1.7-4.6-2.7.1-4 1-4.9 2z"/>
        </svg>
      ),
      industrial_sites: (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M2 20a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8l-7 5V8l-7 5V4a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2Z"/>
        </svg>
      ),
    }

    const rowIcon = INDUSTRY_ROW_ICONS[cat.key] || INDUSTRY_ROW_ICONS.industrial_sites
    const catColor = CATEGORY_COLORS[cat.key] || cat.color

    // Check which group fields are available for this category
    const hasProvince = cat.items.some(x => x.province)
    const hasDistrict = cat.items.some(x => x.district)
    const hasType = cat.items.some(x => x.type)

    // Subtitle for each item
    const itemSub = (item: IndustryItem) => {
      if (item.fuel) return item.fuel
      if (item.capacity_mw) return `${item.capacity_mw} MW`
      if (item.capacity_mtpa) return `${item.capacity_mtpa} Mt/yr`
      return item.type || ''
    }

    // Right-side tag
    const itemTag = (item: IndustryItem) => {
      if (item.fuel) return item.fuel
      if (item.capacity_mw) return `${item.capacity_mw} MW`
      if (item.capacity_mtpa) return `${item.capacity_mtpa} Mt/yr`
      return ''
    }

    return (
      <div className="flex flex-col h-full">
        <BackButton label="All Sources" onClick={() => { setView({ type: 'categories' }); setSearch(''); setIndustrySort('province') }} />
        <div className="px-3 py-2 border-b border-slate-100 flex items-center gap-2">
          <div className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-slate-50 border border-slate-200 flex-1 min-w-0">
            <Search size={13} className="text-slate-400 shrink-0" />
            <input
              value={search}
              onChange={e => { setSearch(e.target.value); setIndustryLimit(200) }}
              placeholder={`Search ${cat.label.toLowerCase()}...`}
              className="flex-1 text-xs bg-transparent outline-none text-slate-700 placeholder:text-slate-400"
            />
          </div>
          <select
            value={(!hasProvince && industrySort === 'province') || (!hasDistrict && industrySort === 'district') || (!hasType && industrySort === 'type') ? 'name' : industrySort}
            onChange={e => { setIndustrySort(e.target.value as 'province' | 'district' | 'type' | 'name'); setIndustryLimit(200) }}
            className="text-[10px] text-slate-600 bg-slate-50 border border-slate-200 rounded-lg px-2 py-1.5 outline-none shrink-0"
          >
            {hasProvince && <option value="province">Province</option>}
            {hasDistrict && <option value="district">District</option>}
            {hasType && <option value="type">Type</option>}
            <option value="name">A &rarr; Z</option>
          </select>
        </div>
        <div className="px-3 py-1 text-[10px] border-b border-slate-50" style={{ color: catColor }}>
          {filtered.length.toLocaleString()} {cat.label.toLowerCase()}
        </div>
        <div className="flex-1 overflow-y-auto scrollbar-hide">
          {filtered.slice(0, industryLimit).map((item, i) => {
            const prev = i > 0 ? filtered[i - 1] : null
            const showHeader = effectiveSort === 'province'
              ? (i === 0 || prev?.province !== item.province)
              : effectiveSort === 'district'
                ? (i === 0 || prev?.district !== item.district)
                : effectiveSort === 'type'
                  ? (i === 0 || prev?.type !== item.type)
                  : false
            const headerLabel = effectiveSort === 'province'
              ? (item.province || 'Unknown')
              : effectiveSort === 'district'
                ? (item.district || 'Unknown')
                : effectiveSort === 'type'
                  ? (item.type || 'Unknown')
                  : ''
            let groupStats = ''
            if (showHeader && effectiveSort !== 'name') {
              const groupField = effectiveSort as 'province' | 'district' | 'type'
              const groupVal = (item[groupField] || 'Unknown')
              const group = filtered.filter(x => (x[groupField] || 'Unknown') === groupVal)
              groupStats = `${group.length} sites`
            }
            return (
              <div key={`${item.name}-${i}`}>
                {showHeader && (
                  <div className="px-3 pt-3 pb-1.5 bg-slate-50/80 sticky top-0 border-b border-slate-100">
                    <div className="text-[10px] font-bold text-slate-600 uppercase tracking-wide">{headerLabel}</div>
                    {groupStats && <div className="text-[9.5px] text-slate-400 mt-0.5">{groupStats}</div>}
                  </div>
                )}
                <button
                  onClick={() => {
                    onFlyTo(item.lon, item.lat, 14)
                    setView({ type: 'industry-detail', item, categoryKey: cat.key })
                  }}
                  className="w-full flex items-center gap-3 px-3 py-2.5 hover:bg-slate-50 transition-colors text-left border-b border-slate-100/80"
                >
                  <div className="shrink-0 flex items-center justify-center w-8 h-8 rounded-lg shadow-sm" style={{ background: catColor }}>
                    {rowIcon}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-[12px] font-semibold text-slate-800 truncate">{item.name || 'Unnamed'}</div>
                    <div className="text-[10.5px] text-slate-400 truncate">{itemSub(item)}</div>
                  </div>
                  {itemTag(item) && <div className="text-[11px] text-slate-400 shrink-0">{itemTag(item)}</div>}
                </button>
              </div>
            )
          })}
          {filtered.length > industryLimit && (
            <button
              onClick={() => setIndustryLimit(prev => prev + 200)}
              className="w-full px-3 py-3 text-[11px] font-medium hover:bg-slate-50 transition-colors text-center border-t border-slate-100"
              style={{ color: catColor }}
            >
              Load more ({(filtered.length - industryLimit).toLocaleString()} remaining)
            </button>
          )}
        </div>
      </div>
    )
  }

  // ── Industry detail ──
  if (view.type === 'industry-detail') {
    const cat = industryCategories.find(c => c.key === view.categoryKey)
    const item = view.item
    const catLabel = cat?.label || view.categoryKey
    const catColor = cat?.color || CATEGORY_COLORS[view.categoryKey] || '#64748b'

    // Category-specific badge labels
    const BADGE_LABELS: Record<string, string> = {
      power_plants: 'Power Plant',
      cement_plants: 'Cement Plant',
      steel_sites: 'Steel Site',
      sugar_mills: 'Sugar Mill',
      mines_quarries: 'Mine / Quarry',
      industrial_sites: 'Industrial Site',
    }

    return (
      <div className="flex flex-col h-full bg-[#fafbfc]">
        <button
          onClick={() => setView({ type: 'industry', categoryKey: view.categoryKey })}
          className="flex items-center gap-1 px-5 py-3 text-[12px] font-medium text-slate-400 hover:text-slate-600 transition-colors w-full"
        >
          <ChevronLeft size={14} strokeWidth={2} /> {catLabel}
        </button>
        <div className="flex-1 overflow-y-auto scrollbar-hide">
          {/* Header */}
          <div className="px-5 pb-4">
            <h2 className="text-[20px] font-semibold text-[#1e293b] leading-snug tracking-[-0.01em]">
              {item.name || 'Unnamed Site'}
            </h2>
            <p className="text-[12px] text-[#94a3b8] mt-1 leading-relaxed">
              {[item.province, item.district].filter(Boolean).join(', ')}
              {item.fuel ? <> &middot; {item.fuel}</> : ''}
            </p>
            <span
              className="inline-flex items-center mt-2.5 text-[10px] font-semibold uppercase tracking-wide px-2.5 py-[3px] rounded-full"
              style={{ background: `${catColor}15`, color: catColor }}
            >
              {BADGE_LABELS[view.categoryKey] || catLabel}
            </span>
          </div>

          {/* Satellite image */}
          <div className="px-4 pb-3">
            <SatelliteImage
              lat={item.lat}
              lon={item.lon}
              name={item.name || 'Site'}
              markerColor={catColor}
              zoom="close"
              label={BADGE_LABELS[view.categoryKey] || catLabel}
            />
          </div>

          {/* Details card */}
          <div className="px-4 pb-4">
            <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
              <div className="px-4 py-2.5 border-b border-slate-100">
                <span className="text-[12px] font-bold text-slate-700">Site Details</span>
              </div>
              <div className="px-4 py-3 grid grid-cols-2 gap-x-6 gap-y-2.5 text-[11px]">
                {item.province && <div><div className="text-slate-400 text-[10px]">Province</div><div className="text-slate-700 font-medium">{item.province}</div></div>}
                {item.district && <div><div className="text-slate-400 text-[10px]">District</div><div className="text-slate-700 font-medium">{item.district}</div></div>}
                {item.fuel && <div><div className="text-slate-400 text-[10px]">Fuel Type</div><div className="text-slate-700 font-medium">{item.fuel}</div></div>}
                {item.capacity_mw != null && <div><div className="text-slate-400 text-[10px]">Capacity</div><div className="text-slate-700 font-medium">{item.capacity_mw} MW</div></div>}
                {item.capacity_mtpa != null && <div><div className="text-slate-400 text-[10px]">Capacity</div><div className="text-slate-700 font-medium">{item.capacity_mtpa} Mt/yr</div></div>}
                <div><div className="text-slate-400 text-[10px]">Coordinates</div><div className="text-slate-700 font-medium">{item.lat.toFixed(4)}, {item.lon.toFixed(4)}</div></div>
                {item.type && <div><div className="text-slate-400 text-[10px]">Type</div><div className="text-slate-700 font-medium">{item.type}</div></div>}
              </div>
            </div>
          </div>

          {/* Fly-to button */}
          <div className="px-4 pb-4">
            <button
              onClick={() => onFlyTo(item.lon, item.lat, 16)}
              className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-[12px] font-medium text-white transition-colors"
              style={{ background: catColor }}
            >
              <MapPin size={13} /> View on Map
            </button>
          </div>
        </div>
      </div>
    )
  }

  return null
}

// ── Station Detail View (sidebar inline) ──

interface StationDetailProps {
  station: StationItem
  selectedDate: string | null
  onBack: () => void
  onFlyTo: (lng: number, lat: number, zoom?: number) => void
}

function StationDetailView({ station, selectedDate, onBack, onFlyTo }: StationDetailProps) {
  const { data: hourlyData, isLoading: hourlyLoading } = useQuery({
    queryKey: ['station-hourly', station.station_id, selectedDate],
    queryFn: async () => {
      if (!station.station_id) return null
      const dateParam = selectedDate ? `&date=${selectedDate}` : ''
      const res = await fetch(`${API_BASE}/api/v1/dashboard/stations/${station.station_id}/history/pm25?hours=24${dateParam}&all_providers=true`)
      if (!res.ok) return null
      return res.json() as Promise<{ timestamp_pk: string; pm25: number | null }[]>
    },
    enabled: !!station.station_id,
    staleTime: 5 * 60 * 1000,
  })

  const { data: overview } = useQuery({
    queryKey: ['station-overview-mini', station.station_id],
    queryFn: async () => {
      if (!station.station_id) return null
      const res = await fetch(`${API_BASE}/api/v1/internal/stations/${station.station_id}/overview`)
      if (!res.ok) return null
      return res.json()
    },
    enabled: !!station.station_id,
    staleTime: 10 * 60 * 1000,
  })

  const chartData = useMemo(() => {
    if (!hourlyData?.length) return []
    return hourlyData.map(d => {
      const pk = new Date(d.timestamp_pk)
      return {
        hour: pk.toLocaleTimeString('en-US', { hour: '2-digit', hour12: false, timeZone: 'Asia/Karachi' }),
        pm25: d.pm25,
      }
    })
  }, [hourlyData])

  const poll = overview?.pollutant_summary
  const avail = overview?.data_availability
  const provider = overview?.station?.provider

  // Status badge
  const statusLabel = (() => {
    if (!avail?.last_obs) return { text: 'Unknown', bg: '#f1f5f9', color: '#94a3b8' }
    const hrs = (Date.now() - new Date(avail.last_obs).getTime()) / 3600000
    if (hrs < 3) return { text: 'Online', bg: '#ecfdf5', color: '#059669' }
    if (hrs < 24) return { text: 'Delayed', bg: '#fefce8', color: '#ca8a04' }
    return { text: 'Offline', bg: '#fef2f2', color: '#dc2626' }
  })()

  // Health category (US EPA 2024 PM2.5 breakpoints, lib/aqi)
  const aqiBand = (() => {
    const b = classifyPm25(station.pm25)
    return { label: b.shortLabel, color: b.color, bg: b.color + '1f' }
  })()

  const stats24h = useMemo(() => {
    if (!chartData.length) return null
    const vals = chartData.filter(d => d.pm25 != null).map(d => d.pm25!)
    if (!vals.length) return null
    return {
      mean: Math.round(vals.reduce((a, b) => a + b, 0) / vals.length),
      max: Math.round(Math.max(...vals)),
      min: Math.round(Math.min(...vals)),
      count: vals.length,
    }
  }, [chartData])

  const rolling7d = poll?.rolling_means?.['7d'] ?? null

  return (
    <div className="flex flex-col h-full bg-[#fafbfc]">
      {/* Back row */}
      <button
        onClick={onBack}
        className="flex items-center gap-1 px-5 py-3 text-[12px] font-medium text-slate-400 hover:text-slate-600 transition-colors w-full"
      >
        <ChevronLeft size={14} strokeWidth={2} /> All Stations
      </button>

      <div className="flex-1 overflow-y-auto scrollbar-hide">
        {/* ── Header ── */}
        <div className="px-5 pb-5">
          <div className="flex items-start justify-between gap-4">
            {/* Left: identity */}
            <div className="min-w-0 flex-1 pt-0.5">
              <h2 className="text-[20px] font-semibold text-[#1e293b] leading-snug tracking-[-0.01em]">
                {station.name}
              </h2>
              <p className="text-[12px] text-[#94a3b8] mt-1 leading-relaxed">
                {station.city}, Pakistan{provider ? <> &middot; {provider}</> : ''}
              </p>
              <span
                className="inline-flex items-center mt-2.5 text-[10px] font-semibold uppercase tracking-wide px-2.5 py-[3px] rounded-full"
                style={{ background: statusLabel.bg, color: statusLabel.color }}
              >
                {statusLabel.text}
              </span>
            </div>

            {/* Right: metric */}
            <div className="shrink-0 flex flex-col items-end pt-0.5">
              <div className="text-[28px] font-bold tabular-nums leading-none tracking-[-0.02em]" style={{ color: aqiBand.color }}>
                {Math.round(station.pm25)}
              </div>
              <div className="text-[11px] text-[#94a3b8] mt-1 font-medium">µg/m³</div>
              <span
                className="mt-2.5 text-[10px] font-semibold px-2.5 py-[3px] rounded-full"
                style={{ background: aqiBand.bg, color: aqiBand.color }}
              >
                {aqiBand.label}
              </span>
            </div>
          </div>
        </div>

        {/* ── Satellite image ── */}
        <div className="px-4 pb-3">
          <SatelliteImage lat={station.lat} lon={station.lon} name={station.name} markerColor={pm25ToBandColor(station.pm25)} markerType="aqi" aqiValue={station.pm25} />
        </div>

        {/* ── Stats cards ── */}
        <div className="px-4 pb-3">
          <div className="flex gap-2">
            <StatCard
              value={stats24h ? `${stats24h.mean}` : '—'}
              label="24h Avg"
              unit="µg/m³"
              barPct={stats24h ? Math.min(100, (stats24h.mean / 200) * 100) : 0}
              barColor={stats24h ? pm25ToBandColor(stats24h.mean) : '#e2e8f0'}
            />
            <StatCard
              value={stats24h ? `${stats24h.max}` : '—'}
              label="24h Max"
              unit="µg/m³"
              barPct={stats24h ? Math.min(100, (stats24h.max / 200) * 100) : 0}
              barColor={stats24h ? pm25ToBandColor(stats24h.max) : '#e2e8f0'}
            />
            <StatCard
              value={rolling7d != null ? `${Math.round(rolling7d)}` : '—'}
              label="7d Avg"
              unit="µg/m³"
              barPct={rolling7d != null ? Math.min(100, (rolling7d / 200) * 100) : 0}
              barColor={rolling7d != null ? pm25ToBandColor(rolling7d) : '#e2e8f0'}
            />
            <StatCard
              value={stats24h ? `${stats24h.count}` : '—'}
              unit="hours"
              label="/24 Coverage"
              barPct={stats24h ? (stats24h.count / 24) * 100 : 0}
              barColor={stats24h && stats24h.count >= 18 ? '#16a34a' : '#f59e0b'}
              barDashed={true}
            />
          </div>
        </div>

        {/* ── 24h Bar Chart ── */}
        <div className="px-4 pb-3">
          <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
            <div className="px-4 pt-3 pb-1 flex items-center justify-between">
              <span className="text-[13px] font-bold text-slate-700">24-Hour PM2.5 Trend</span>
              <span className="text-[10px] text-slate-400">
                {selectedDate && new Date(selectedDate).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
              </span>
            </div>
            <div className="px-2 pb-2">
              {hourlyLoading ? (
                <div className="h-[160px] flex items-center justify-center">
                  <div className="w-4 h-4 border-2 border-slate-300 border-t-slate-600 rounded-full animate-spin" />
                </div>
              ) : chartData.length ? (
                <PM25BarChart data={chartData} />
              ) : (
                <div className="h-[160px] flex items-center justify-center text-[11px] text-slate-400">
                  No hourly data available
                </div>
              )}
            </div>
          </div>
        </div>

        {/* ── Today's insight ── */}
        <div className="px-4 pb-3">
          <StationInsight station={station} stats={stats24h} rolling7d={rolling7d} selectedDate={selectedDate} />
        </div>

        {/* ── Station Details ── */}
        {overview?.station && (
          <div className="px-4 pb-4">
            <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
              <div className="px-4 py-2.5 border-b border-slate-100">
                <span className="text-[12px] font-bold text-slate-700">Station Details</span>
              </div>
              <div className="px-4 py-3 grid grid-cols-2 gap-x-6 gap-y-2.5 text-[11px]">
                <DetailRow label="Provider" value={overview.station.provider || '—'} />
                <DetailRow label="Coordinates" value={`${station.lat.toFixed(4)}, ${station.lon.toFixed(4)}`} />
                {overview.station.site_type && <DetailRow label="Site Type" value={overview.station.site_type} />}
                {overview.station.timezone && <DetailRow label="Timezone" value={overview.station.timezone} />}
                {avail?.first_obs && <DetailRow label="Since" value={new Date(avail.first_obs).toLocaleDateString('en-US', { month: 'short', year: 'numeric' })} />}
                {avail?.coverage_last_365d_pct != null && <DetailRow label="Annual Coverage" value={`${Math.round(avail.coverage_last_365d_pct)}%`} />}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Subcomponents ──

function StatCard({ value, label, unit, barPct, barColor, barDashed }: { value: string; label: string; unit?: string; barPct: number; barColor: string; barDashed?: boolean }) {
  return (
    <div className="flex-1 bg-white border border-slate-200 rounded-xl px-2 py-2.5 text-center min-w-0">
      <div className="text-[16px] font-bold text-slate-800 tabular-nums leading-none">
        {value}{unit && <span className="text-[8px] font-medium text-slate-300 ml-0.5">{unit}</span>}
      </div>
      <div className="text-[9px] text-slate-400 mt-1">{label}</div>
      <div className="mt-1.5 h-[3px] rounded-full bg-slate-100 overflow-hidden">
        <div
          className="h-full rounded-full transition-all"
          style={{
            width: `${Math.max(barPct, 4)}%`,
            background: barDashed
              ? `repeating-linear-gradient(90deg, ${barColor} 0px, ${barColor} 4px, transparent 4px, transparent 7px)`
              : barColor,
          }}
        />
      </div>
    </div>
  )
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-slate-400 text-[10px]">{label}</div>
      <div className="text-slate-700 font-medium">{value}</div>
    </div>
  )
}

function StationInsight({ station, stats, rolling7d, selectedDate }: { station: StationItem; stats: { mean: number; max: number; min: number; count: number } | null; rolling7d: number | null; selectedDate?: string }) {
  const dateLabel = selectedDate
    ? new Date(selectedDate).toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })
    : 'this date'

  if (!stats) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white px-4 py-3">
        <div className="flex items-center gap-1.5 mb-1">
          <svg className="w-3.5 h-3.5 text-slate-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="10" /><path d="M12 16v-4" /><path d="M12 8h.01" />
          </svg>
          <span className="text-[12px] font-semibold text-slate-700">Retrospective</span>
          <span className="text-[9px] text-slate-400 ml-auto">Based on observed data</span>
        </div>
        <div className="text-[11px] text-slate-500 leading-relaxed">No hourly data was recorded at {station.name} on {dateLabel}.</div>
      </div>
    )
  }

  const accentColor = pm25ToBandColor(stats.mean)
  const conditionLabel = classifyPm25(stats.mean).label.toLowerCase()

  // Build station-specific narrative
  const lines: string[] = []

  // Opening — station-specific with condition
  lines.push(`${station.name} recorded ${conditionLabel} air quality on ${dateLabel}, averaging ${stats.mean} µg/m³ across ${stats.count} hourly observations.`)

  // Peak analysis
  if (stats.max > stats.mean * 1.5) {
    lines.push(`PM2.5 peaked at ${stats.max} µg/m³, significantly above the daily mean — suggesting a transient pollution episode.`)
  } else if (stats.max > stats.mean * 1.2) {
    lines.push(`The peak reading of ${stats.max} µg/m³ indicates moderate variability throughout the day.`)
  } else {
    lines.push(`Concentrations remained relatively stable, peaking at ${stats.max} µg/m³.`)
  }

  // 7-day comparison
  if (rolling7d != null) {
    const diff = stats.mean - rolling7d
    const pct = Math.round((Math.abs(diff) / rolling7d) * 100)
    if (Math.abs(diff) < 3) {
      lines.push(`This is consistent with the 7-day rolling average of ${Math.round(rolling7d)} µg/m³.`)
    } else if (diff > 0) {
      lines.push(`This was ${pct}% above the 7-day rolling average of ${Math.round(rolling7d)} µg/m³, indicating a worse-than-usual day for this station.`)
    } else {
      lines.push(`This was ${pct}% below the 7-day rolling average of ${Math.round(rolling7d)} µg/m³, a relatively cleaner day for this location.`)
    }
  }

  // Coverage caveat
  if (stats.count < 18) {
    lines.push(`Note: Only ${stats.count} of 24 hours reported data, so the actual daily exposure may differ.`)
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-white overflow-hidden" style={{ borderLeft: `3px solid ${accentColor}` }}>
      <div className="px-4 py-3">
        <div className="flex items-center gap-1.5 mb-2">
          <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke={accentColor} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" />
          </svg>
          <span className="text-[12px] font-semibold text-slate-800">Retrospective</span>
          <span className="text-[9px] text-slate-400 ml-auto">Based on observed data</span>
        </div>
        <div className="text-[11px] text-slate-600 leading-[1.75] space-y-1">
          {lines.map((line, i) => <p key={i}>{line}</p>)}
        </div>
      </div>
    </div>
  )
}
