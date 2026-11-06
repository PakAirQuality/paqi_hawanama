'use client'

import { useState, useMemo } from 'react'
import { AqiCard } from '@/components/shared/AqiCard'
import { StationHourlyChart, useStationHourly } from '@/components/shared/StationHourlyChart'
import { formatDateOnly, hourLabel, relativeAge } from '@/lib/time'
import { classifyPm25, pm25Color } from '@/lib/aqi'
import { useQuery } from '@tanstack/react-query'
import { ChevronRight, ChevronLeft, ChevronsLeft, Search, MapPin } from 'lucide-react'
import { useIsMobile } from '@/lib/useMediaQuery'
import { SatelliteImage } from '@/components/shared/SatelliteImage'
import { stationForecastDays, type StationForecastDay } from '@/lib/timeline'
import type { ForecastEntry, NowcastResponse } from '@/components/analyst-desk/types'

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
    <svg className="w-[18px] h-[18px]" viewBox="0 0 24 24" fill="currentColor">
      <path d="M4 4h16v3.5h-6v9h6V20H4v-3.5h6v-9H4z" />
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
  /** forecast readings: model | neighbours | prior */
  basis?: string
  obs_available?: boolean
}

export interface KilnItem {
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

export interface IndustryItem {
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

export interface IndustryCategory {
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
  /** Open this item's detail view (a map click). A new object each time, so a repeat click reopens it. */
  focus?: StructuresFocus | null
  /** When given, leaving the station detail closes the panel instead of returning to the list */
  onClose?: () => void
  /** What a station's number means in this view */
  stationCaption?: string
  /** Set on a forecast day: the run, today, and the day in view */
  stationForecast?: { forecasts: ForecastEntry[]; today: string; date: string | null }
  /** The latest hourly nowcast: the station chart gets a dashed +3/+6/+12 h tail */
  stationNowcast?: NowcastResponse
}

// Health classification: one implementation for the whole dashboard (lib/aqi)
function pm25ToBandColor(pm25: number): string {
  return pm25Color(pm25)
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? ""

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

export type StructuresFocus = Extract<View, { type: 'station-detail' | 'kiln-detail' | 'industry-detail' }>

export function StructuresTab({ stations, kilns, industryCategories, selectedDate, onFlyTo, initialView, focus, onClose, stationCaption, stationForecast, stationNowcast }: StructuresTabProps) {
  const [view, setView] = useState<View>(focus ?? (initialView === 'stations' ? { type: 'stations' } : { type: 'categories' }))
  // Follow a new focus from the map (state adjusted during render, not in an effect)
  const [prevFocus, setPrevFocus] = useState(focus)
  if (focus !== prevFocus) {
    setPrevFocus(focus)
    if (focus) setView(focus)
  }
  const [search, setSearch] = useState('')
  const [sortBy, setSortBy] = useState<'pm25' | 'name' | 'city' | 'network'>('pm25')
  const [kilnSort, setKilnSort] = useState<'province' | 'district' | 'id'>('province')
  const [kilnLimit, setKilnLimit] = useState(200)
  const [industrySort, setIndustrySort] = useState<'province' | 'district' | 'type' | 'name'>('province')
  const [industryLimit, setIndustryLimit] = useState(200)

  // ── Derived data ──
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
      className="flex items-center gap-1 px-4 py-3 text-[14px] font-medium text-slate-700 hover:text-slate-900 transition-colors w-full"
    >
      <ChevronLeft size={18} strokeWidth={2} /> {label}
    </button>
  )

  // ── Categories view (home) ──
  if (view.type === 'categories') {
    const CategoryRow = ({ onClick, color, icon, label, sub }: { onClick: () => void; color: string; icon: React.ReactNode; label: string; sub: string }) => (
      <button
        onClick={onClick}
        className="w-full flex items-center gap-3.5 px-3 py-3 rounded-2xl hover:bg-slate-900/[0.04] transition-colors text-left group"
      >
        <div className="w-11 h-11 rounded-full flex items-center justify-center shrink-0"
          style={{ background: color + '1f', color }}>
          {icon}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-[15px] font-medium text-slate-900">{label}</div>
          <div className="text-[13px] text-slate-600 mt-0.5">{sub}</div>
        </div>
        <ChevronRight size={18} className="text-slate-400 group-hover:text-slate-700 transition-colors" />
      </button>
    )

    return (
      <div className="flex flex-col h-full bg-white">
        <div className="px-5 pt-5 pb-3">
          <h3 className="text-[20px] font-semibold text-slate-900 tracking-tight">Emission sources</h3>
          <p className="text-[13px] text-slate-600 mt-0.5">Brick kilns and industrial sites on the map</p>
        </div>
        <div className="flex-1 overflow-y-auto scrollbar-hide px-2 pb-4 space-y-0.5">
          <CategoryRow
            onClick={() => setView({ type: 'kilns' })}
            color={CATEGORY_COLORS.kilns}
            icon={CATEGORY_ICONS.kilns}
            label="Brick Kilns"
            sub={`${kilns.length.toLocaleString()} kilns`}
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
      <div className="flex flex-col h-full bg-white">
        {initialView !== 'stations' && (
          <BackButton label="All Sources" onClick={() => { setView({ type: 'categories' }); setSearch(''); setSortBy('pm25') }} />
        )}
        {initialView === 'stations' && (
          <div className="px-5 pt-5 pb-1">
            <h3 className="text-[13px] font-semibold text-[#1e293b] tracking-[-0.01em]">Monitoring Stations</h3>
            <p className="text-[11px] text-[#94a3b8] mt-0.5">
              {stations.some(s => s.basis != null)
                ? `${stations.length} stations forecast, ${stations.filter(s => s.obs_available === true).length} with live readings`
                : `${stations.length} stations reporting`}
            </p>
          </div>
        )}
        {/* Search + sort */}
        <div className="px-4 pb-3 flex items-center gap-2">
          <div className="flex items-center gap-2.5 px-3.5 py-3 rounded-xl bg-slate-100 flex-1 min-w-0 focus-within:bg-slate-200/70 transition-colors">
            <Search size={17} className="text-slate-500 shrink-0" />
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search stations..."
              className="flex-1 text-[15px] bg-transparent outline-none text-slate-900 placeholder:text-slate-500"
            />
          </div>
          <select
            value={sortBy}
            onChange={e => setSortBy(e.target.value as 'pm25' | 'name' | 'city' | 'network')}
            className="text-[13px] text-slate-800 bg-slate-100 rounded-xl px-3 py-3 outline-none shrink-0 cursor-pointer"
          >
            <option value="pm25">PM2.5 (highest first)</option>
            <option value="city">City</option>
            <option value="network">Network</option>
            <option value="name">A → Z</option>
          </select>
        </div>
        <div className="px-5 pb-2 text-[11px] font-medium text-[#94a3b8]">
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
                  <div className="px-3 pt-2.5 pb-1 text-[11px] font-semibold text-slate-500 tracking-wide bg-slate-50/80 sticky top-0">
                    {s.city}
                  </div>
                )}
                {showNetworkHeader && (
                  <div className="px-4 pt-4 pb-1.5 bg-white/90 backdrop-blur sticky top-0 z-[1]">
                    <div className="text-[13px] font-semibold text-slate-900">{netGroup}</div>
                    <div className="text-[9.5px] text-slate-500 mt-0.5">{netCount} stations</div>
                  </div>
                )}
                <button
                  onClick={() => {
                    onFlyTo(s.lon, s.lat, 14)
                    setView({ type: 'station-detail', station: s })
                  }}
                  className="w-full flex items-center gap-3 px-3 py-2.5 hover:bg-slate-50 transition-colors text-left border-slate-100/80"
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
                    {sortBy !== 'city' && <div className="text-[10.5px] text-slate-500 truncate">{s.city}</div>}
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
        caption={stationCaption}
        forecast={stationForecast}
        nowcast={stationNowcast}
        onBack={() => (onClose ? onClose() : setView({ type: 'stations' }))}
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
        <div className="px-4 pb-3 pt-1 flex items-center gap-2">
          <select
            value={kilnSort}
            onChange={e => { setKilnSort(e.target.value as 'province' | 'district' | 'id'); setKilnLimit(200) }}
            className="w-full text-[13px] text-slate-800 bg-slate-100 rounded-xl px-3 py-3 outline-none shrink-0 cursor-pointer"
          >
            <option value="province">Province</option>
            <option value="district">District</option>
            <option value="id">A → Z</option>
          </select>
        </div>
        <div className="px-4 pb-1 text-[13px] text-slate-600">
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
              const groupVal = kilnSort === 'province' ? k.state : (k.district || 'Unknown')
              const group = searched.filter(x => (kilnSort === 'province' ? x.state : (x.district || 'Unknown')) === groupVal)
              const fuelCounts: Record<string, number> = {}
              for (const item of group) { fuelCounts[item.fuel] = (fuelCounts[item.fuel] || 0) + 1 }
              const parts = Object.entries(fuelCounts).sort((a, b) => b[1] - a[1]).map(([f, c]) => `${c} ${f}`)
              groupStats = `${group.length} kilns: ${parts.join(', ')}`
            }
            return (
              <div key={k.id}>
                {showHeader && (
                  <div className="px-4 pt-4 pb-1.5 bg-white/90 backdrop-blur sticky top-0 z-[1]">
                    <div className="text-[13px] font-semibold text-slate-900">{headerLabel}</div>
                    {groupStats && <div className="text-xs text-slate-600 mt-0.5">{groupStats}</div>}
                  </div>
                )}
                <button
                  onClick={() => {
                    onFlyTo(k.lon, k.lat, 16)
                    setView({ type: 'kiln-detail', kiln: k })
                  }}
                  className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-slate-900/[0.04] transition-colors text-left"
                >
                  {/* Chimney badge */}
                  <div className="shrink-0 flex items-center justify-center w-9 h-9 rounded-full bg-amber-600">
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
                    <div className="text-[14px] font-medium text-slate-900">{k.id}</div>
                    <div className="text-xs text-slate-600">{[k.district, k.state].filter(Boolean).join(', ')}</div>
                  </div>
                  <div className="text-[13px] text-slate-700 shrink-0 capitalize">{k.fuel}</div>
                </button>
              </div>
            )
          })}
          {searched.length > kilnLimit && (
            <button
              onClick={() => setKilnLimit(prev => prev + 200)}
              className="w-full px-4 py-4 text-[13px] font-medium text-slate-800 hover:bg-slate-900/[0.04] transition-colors text-center"
            >
              Load more ({(searched.length - kilnLimit).toLocaleString()} remaining)
            </button>
          )}
        </div>
        <KilnSource compact />
      </div>
    )
  }

  // ── Kiln Detail ──
  if (view.type === 'kiln-detail') {
    const k = view.kiln
    return (
      <div className="flex flex-col h-full bg-white">
        <button
          onClick={() => { setView({ type: 'kilns' }) }}
          className="flex items-center gap-1 px-4 py-3 text-[14px] font-medium text-slate-700 hover:text-slate-900 transition-colors w-full"
        >
          <ChevronLeft size={18} strokeWidth={2} /> All Kilns
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
            <span className="inline-flex items-center mt-2.5 text-[11px] font-semibold tracking-wide px-2.5 py-[3px] rounded-full bg-amber-50 text-amber-600">
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
              <div className="px-4 py-2.5 border-slate-100">
                <span className="text-[12px] font-bold text-slate-700">Kiln Details</span>
              </div>
              <div className="px-4 py-3 grid grid-cols-2 gap-x-6 gap-y-2.5 text-[11px]">
                <div><div className="text-slate-500 text-[11px]">Province</div><div className="text-slate-700 font-medium">{k.state}</div></div>
                {k.district && <div><div className="text-slate-500 text-[11px]">District</div><div className="text-slate-700 font-medium">{k.district}</div></div>}
                <div><div className="text-slate-500 text-[11px]">Fuel Type</div><div className="text-slate-700 font-medium">{k.fuel}</div></div>
                <div><div className="text-slate-500 text-[11px]">Capacity</div><div className="text-slate-700 font-medium">{k.capacity_tonnes} tonnes</div></div>
                <div><div className="text-slate-500 text-[11px]">Coordinates</div><div className="text-slate-700 font-medium">{k.lat.toFixed(4)}, {k.lon.toFixed(4)}</div></div>
              </div>
            </div>
          </div>
          <div className="px-4 pb-6"><KilnSource /></div>
        </div>
      </div>
    )
  }

  // ── Industry category ──
  if (view.type === 'industry') {
    const cat = industryCategories.find(c => c.key === view.categoryKey)
    if (!cat) return null

    // Check which group fields are available for this category
    const hasProvince = cat.items.some(x => x.province)
    const hasDistrict = cat.items.some(x => x.district)
    const hasType = cat.items.some(x => x.type)

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
          <path d="M4 4h16v3.5h-6v9h6V20H4v-3.5h6v-9H4z"/>
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
        <div className="px-4 pb-3 pt-1 flex items-center gap-2">
          <div className="flex items-center gap-2.5 px-3.5 py-3 rounded-xl bg-slate-100 flex-1 min-w-0 focus-within:bg-slate-200/70 transition-colors">
            <Search size={17} className="text-slate-500 shrink-0" />
            <input
              value={search}
              onChange={e => { setSearch(e.target.value); setIndustryLimit(200) }}
              placeholder={`Search ${cat.label.toLowerCase()}...`}
              className="flex-1 text-[15px] bg-transparent outline-none text-slate-900 placeholder:text-slate-500"
            />
          </div>
          <select
            value={effectiveSort}
            onChange={e => { setIndustrySort(e.target.value as 'province' | 'district' | 'type' | 'name'); setIndustryLimit(200) }}
            className="text-[13px] text-slate-800 bg-slate-100 rounded-xl px-3 py-3 outline-none shrink-0 cursor-pointer"
          >
            {hasProvince && <option value="province">Province</option>}
            {hasDistrict && <option value="district">District</option>}
            {hasType && <option value="type">Type</option>}
            <option value="name">A &rarr; Z</option>
          </select>
        </div>
        <div className="px-4 pb-1 text-[13px] text-slate-600">
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
                  <div className="px-4 pt-4 pb-1.5 bg-white/90 backdrop-blur sticky top-0 z-[1]">
                    <div className="text-[13px] font-semibold text-slate-900">{headerLabel}</div>
                    {groupStats && <div className="text-xs text-slate-600 mt-0.5">{groupStats}</div>}
                  </div>
                )}
                <button
                  onClick={() => {
                    onFlyTo(item.lon, item.lat, 14)
                    setView({ type: 'industry-detail', item, categoryKey: cat.key })
                  }}
                  className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-slate-900/[0.04] transition-colors text-left"
                >
                  <div className="shrink-0 flex items-center justify-center w-9 h-9 rounded-full" style={{ background: catColor }}>
                    {rowIcon}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-[14px] font-medium text-slate-900 truncate">{item.name || 'Unnamed'}</div>
                    <div className="text-xs text-slate-600 truncate">{[item.district, item.province].filter(Boolean).join(', ') || itemSub(item)}</div>
                  </div>
                  {itemTag(item) && <div className="text-[13px] text-slate-700 shrink-0">{itemTag(item)}</div>}
                </button>
              </div>
            )
          })}
          {filtered.length > industryLimit && (
            <button
              onClick={() => setIndustryLimit(prev => prev + 200)}
              className="w-full px-4 py-4 text-[13px] font-medium text-slate-800 hover:bg-slate-900/[0.04] transition-colors text-center"
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
      <div className="flex flex-col h-full bg-white">
        <button
          onClick={() => setView({ type: 'industry', categoryKey: view.categoryKey })}
          className="flex items-center gap-1 px-4 py-3 text-[14px] font-medium text-slate-700 hover:text-slate-900 transition-colors w-full"
        >
          <ChevronLeft size={18} strokeWidth={2} /> {catLabel}
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
              className="inline-flex items-center mt-2.5 text-[11px] font-semibold tracking-wide px-2.5 py-[3px] rounded-full"
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
              <div className="px-4 py-2.5 border-slate-100">
                <span className="text-[12px] font-bold text-slate-700">Site Details</span>
              </div>
              <div className="px-4 py-3 grid grid-cols-2 gap-x-6 gap-y-2.5 text-[11px]">
                {item.province && <div><div className="text-slate-500 text-[11px]">Province</div><div className="text-slate-700 font-medium">{item.province}</div></div>}
                {item.district && <div><div className="text-slate-500 text-[11px]">District</div><div className="text-slate-700 font-medium">{item.district}</div></div>}
                {item.fuel && <div><div className="text-slate-500 text-[11px]">Fuel Type</div><div className="text-slate-700 font-medium">{item.fuel}</div></div>}
                {item.capacity_mw != null && <div><div className="text-slate-500 text-[11px]">Capacity</div><div className="text-slate-700 font-medium">{item.capacity_mw} MW</div></div>}
                {item.capacity_mtpa != null && <div><div className="text-slate-500 text-[11px]">Capacity</div><div className="text-slate-700 font-medium">{item.capacity_mtpa} Mt/yr</div></div>}
                <div><div className="text-slate-500 text-[11px]">Coordinates</div><div className="text-slate-700 font-medium">{item.lat.toFixed(4)}, {item.lon.toFixed(4)}</div></div>
                {item.type && <div><div className="text-slate-500 text-[11px]">Type</div><div className="text-slate-700 font-medium">{item.type}</div></div>}
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
  caption?: string
  forecast?: StructuresTabProps['stationForecast']
  nowcast?: NowcastResponse
  onBack: () => void
  onFlyTo: (lng: number, lat: number, zoom?: number) => void
}

function StationDetailView({ station, selectedDate, caption, forecast, nowcast, onBack }: StationDetailProps) {
  const isMobile = useIsMobile()
  const { observed: chartData } = useStationHourly(station, selectedDate, nowcast)

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

  const forecastDays = useMemo(
    () => (forecast ? stationForecastDays(forecast.forecasts, forecast.today, station.name, station.city) : []),
    [forecast, station.name, station.city],
  )

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

  const peak = (() => {
    if (!stats24h) return null
    let best: { hour: string; pm25: number } | null = null
    for (const d of chartData) if (d.pm25 != null && (!best || d.pm25 > best.pm25)) best = { hour: d.hour, pm25: d.pm25 }
    return best
  })()

  const dateLabel = selectedDate
    ? new Date(selectedDate).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
    : ''

  const statusColor = statusLabel.text === 'Online' ? 'text-emerald-700' : statusLabel.text === 'Delayed' ? 'text-amber-700' : statusLabel.text === 'Offline' ? 'text-red-700' : 'text-slate-500'

  // One short reading of the day, instead of a paragraph of narrative
  const insight = (() => {
    if (!stats24h || !peak) return null
    const parts = [`Peaked at ${Math.round(peak.pm25)} µg/m³ around ${hourLabel(peak.hour)}.`]
    if (rolling7d != null) {
      const diff = stats24h.mean - rolling7d
      const pct = Math.round((Math.abs(diff) / rolling7d) * 100)
      parts.push(Math.abs(diff) < 3 ? 'In line with the 7-day average.' : `${pct}% ${diff > 0 ? 'above' : 'below'} the 7-day average.`)
    }
    return parts.join(' ')
  })()

  return (
    <div className="flex flex-col h-full bg-white">
      {/* Phones: the sheet's own down arrow closes it. Desktop: the panel collapses back into the left rail. */}
      <div className={`flex-1 overflow-y-auto scrollbar-hide px-4 pb-6 ${isMobile ? 'pt-1' : 'pt-4'}`}>
        {/* Identity */}
        <div className="flex items-start gap-2">
          <h2 className="min-w-0 flex-1 text-[20px] font-semibold text-slate-900 leading-snug tracking-tight">{station.name}</h2>
          {!isMobile && (
            <button
              onClick={onBack}
              aria-label="Collapse station panel"
              title="Collapse"
              className="-mr-1.5 mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-slate-500 transition-[background-color,color,transform] duration-150 hover:bg-slate-900/[0.06] hover:text-slate-900 active:scale-90"
            >
              <ChevronsLeft size={18} strokeWidth={2} />
            </button>
          )}
        </div>
        <p className="mt-0.5 text-[13px] text-slate-600">
          {station.city}{provider ? `, ${provider}` : ''}
        </p>
        <p className={`mt-0.5 text-xs font-medium ${statusColor}`}>
          {statusLabel.text}{avail?.last_obs ? `, last reading ${relativeAge(avail.last_obs)}` : ''}
        </p>

        {/* Headline reading */}
        <AqiCard
          className="mt-4 shadow-none"
          pm25={station.pm25}
          caption={caption ?? (selectedDate ? 'PM2.5 daily mean' : 'PM2.5')}
        />

        {forecastDays.length > 0 && <ForecastDays days={forecastDays} current={forecast?.date ?? null} />}

        {/* Key numbers */}
        <div className="mt-5 grid grid-cols-3 gap-3">
          <Figure label="24-hour average" value={stats24h ? stats24h.mean : null} />
          <Figure label="24-hour peak" value={stats24h ? stats24h.max : null} />
          <Figure label="7-day average" value={rolling7d != null ? Math.round(rolling7d) : null} />
        </div>

        {/* 24-hour trend */}
        <div className="mt-6 flex items-baseline justify-between">
          <h3 className="text-[13px] font-semibold text-slate-900">Last 24 hours</h3>
          <span className="text-xs text-slate-600">{dateLabel}</span>
        </div>
        <div className="mt-2 -mx-1">
          <StationHourlyChart station={station} date={selectedDate} nowcast={nowcast} />
        </div>
        {insight && <p className="mt-2 text-[13px] leading-relaxed text-slate-700">{insight}</p>}

        {/* Location */}
        <h3 className="mt-6 mb-2 text-[13px] font-semibold text-slate-900">Location</h3>
        <SatelliteImage lat={station.lat} lon={station.lon} name={station.name} markerColor={pm25ToBandColor(station.pm25)} markerType="aqi" aqiValue={station.pm25} />

        {/* About this station */}
        {overview?.station && (
          <>
            <h3 className="mt-6 mb-1 text-[13px] font-semibold text-slate-900">About this station</h3>
            <dl className="text-[13px]">
              <DetailRow label="Provider" value={overview.station.provider || '—'} />
              <DetailRow label="Coordinates" value={`${station.lat.toFixed(4)}, ${station.lon.toFixed(4)}`} />
              {overview.station.site_type && <DetailRow label="Site type" value={overview.station.site_type} />}
              {avail?.first_obs && <DetailRow label="Reporting since" value={new Date(avail.first_obs).toLocaleDateString('en-US', { month: 'short', year: 'numeric' })} />}
            </dl>
          </>
        )}
      </div>
    </div>
  )
}

// ── Subcomponents ──

function ForecastDays({ days, current }: { days: StationForecastDay[]; current: string | null }) {
  return (
    <>
      <h3 className="mt-5 text-[13px] font-semibold text-slate-900">Forecast</h3>
      <ul className="mt-1.5 -mx-2">
        {days.map(d => {
          const band = classifyPm25(d.pm25)
          return (
            <li
              key={d.date}
              aria-current={d.date === current ? 'date' : undefined}
              className={`flex items-center gap-2.5 rounded-lg px-2 py-1.5 text-[13px] ${d.date === current ? 'bg-slate-100' : ''}`}
            >
              <span className="w-[86px] shrink-0 text-slate-700">{formatDateOnly(d.date, { weekday: 'short', month: 'short', day: 'numeric' })}</span>
              <span className="w-10 shrink-0 rounded-md py-0.5 text-center font-semibold tabular-nums" style={{ background: band.color, color: band.textColor }}>{Math.round(d.pm25)}</span>
              <span className="min-w-0 flex-1 truncate text-slate-700">{band.label}</span>
              {d.high != null && d.high > d.pm25 && <span className="shrink-0 text-xs tabular-nums text-slate-600">up to {Math.round(d.high)}</span>}
            </li>
          )
        })}
      </ul>
      <p className="mt-1.5 text-xs leading-relaxed text-slate-600">Daily average PM2.5 in µg/m³. &ldquo;Up to&rdquo; is the 90th percentile of the forecast.</p>
      {days.some(d => d.basis === 'neighbours') && (
        <p className="mt-1 text-xs leading-relaxed text-amber-700">This station had no live readings when the forecast was made; its values are estimated from nearby reporting stations.</p>
      )}
      {days.some(d => d.basis === 'prior') && (
        <p className="mt-1 text-xs leading-relaxed text-amber-700">No live readings here or nearby when the forecast was made; these are model estimates only.</p>
      )}
    </>
  )
}

function Figure({ label, value }: { label: string; value: number | null }) {
  return (
    <div>
      <div className="text-[22px] font-semibold leading-none tabular-nums tracking-tight text-slate-900">{value ?? '—'}</div>
      <div className="mt-1 text-xs text-slate-600">{label}</div>
    </div>
  )
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1.5">
      <dt className="text-slate-600">{label}</dt>
      <dd className="text-right font-medium text-slate-900">{value}</dd>
    </div>
  )
}

/** The brick-kiln inventory's source (Scientific Data 2025, CC BY 4.0), cited wherever its kilns are listed. */
const KILN_PAPER_URL = 'https://www.nature.com/articles/s41597-025-05148-9'
function KilnSource({ compact = false }: { compact?: boolean }) {
  if (compact) {
    return (
      <div className="shrink-0 border-t border-slate-900/[0.06] px-4 py-2 text-[11px] leading-snug text-slate-500">
        Source:{' '}
        <a href={KILN_PAPER_URL} target="_blank" rel="noopener noreferrer" className="font-medium text-slate-700 underline-offset-2 hover:underline">
          Hamdani et al. (2025), Scientific Data
        </a>
        , CC BY 4.0
      </div>
    )
  }
  return (
    <p className="text-[11px] leading-relaxed text-slate-500">
      Kiln locations: Hamdani, M. S. A., Zakir, K., Kushwaha, N., Fatima, S. E. and Sheikh, H. A. (2025).{' '}
      <a href={KILN_PAPER_URL} target="_blank" rel="noopener noreferrer" className="font-medium text-slate-700 underline-offset-2 hover:underline">
        Brick Kiln Dataset for Pakistan&apos;s IGP Region Using AI
      </a>
      . Scientific Data 12, 830. doi:10.1038/s41597-025-05148-9. Licensed CC BY 4.0.
    </p>
  )
}
