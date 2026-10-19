'use client'

import { useState, useEffect } from 'react'
import dynamic from 'next/dynamic'
import MapWrapper from '@/components/map/MapWrapper'
import { useStationSidebar } from '@/stores/stationSidebar'
import { useStationsData } from '@/components/map/hooks/useStationsData'
import { CitySearch } from '@/components/ui/CitySearch'
import ViewModeToggle from '@/components/map/ViewModeToggle'
import EstimatedDateRail from '@/components/map/EstimatedDateRail'
import EstimatedContextPanel from '@/components/map/EstimatedContextPanel'
import { fetchTileDates } from '@/lib/api'

// The popup (and its recharts chunk, ~370 KB) is loaded only when a station is opened.
const StationCard = dynamic(() => import('@/components/station/StationCard').then(m => m.StationCard), { ssr: false })

export default function Home() {
  const [showCitySearch, setShowCitySearch] = useState(false)
  const [viewMode, setViewMode] = useState<'live' | 'history'>('live')
  const [availableDates, setAvailableDates] = useState<string[]>([])
  const [selectedDate, setSelectedDate] = useState<string | null>(null)
  const stationOpen = useStationSidebar((s) => s.isOpen)

  // Start the shared station query here (static chunk) so it is in flight while the
  // dynamic map chunks download; MapRefactored reads the same ['stations'] cache entry.
  useStationsData(viewMode === 'live')

  // Prevent body scrolling on map page only
  useEffect(() => {
    const originalStyle = window.getComputedStyle(document.body).overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = originalStyle
    }
  }, [])

  // Fetch available prediction dates the first time ESTIMATED mode is opened, not on
  // every homepage load (LIVE mode never needs them, and no raster source is mounted
  // until a date exists). Once fetched, the dates and selectedDate persist across
  // mode switches so the tile source keeps its cache.
  useEffect(() => {
    if (viewMode !== 'history' || availableDates.length > 0) return
    fetchTileDates()
      .then((dates) => {
        const today = new Date().toISOString().slice(0, 10)
        const filtered = dates.filter((d) => d < today)
        setAvailableDates(filtered)
        if (filtered.length > 0) setSelectedDate(filtered[filtered.length - 1])
      })
      .catch(() => {}) // silent — ESTIMATED mode just won't show dates
  }, [viewMode, availableDates.length])

  return (
    <div className="map-page relative w-full h-full overflow-hidden" style={{
      height: '100vh',
      width: '100vw',
      maxWidth: '100vw'
    }}>
      {/* Page heading for search engines and screen readers; the map itself is the content. */}
      <h1 className="sr-only">Hawanama: real-time air quality map of Pakistan and South Asia</h1>

      {/* Full Screen Map */}
      <MapWrapper
        className="absolute inset-0 w-full h-full"
        windVisible={true}
        viewMode={viewMode}
        selectedDate={selectedDate}
        availableDates={availableDates}
      />

      {/* LIVE / ESTIMATED toggle — Upper Left */}
      <div className="absolute left-4 sm:left-8 z-50" style={{ top: 'max(env(safe-area-inset-top), 1rem)' }}>
        <ViewModeToggle mode={viewMode} onChange={setViewMode} />
      </div>

      {/* Date rail — bottom-center, visible only in ESTIMATED mode */}
      {viewMode === 'history' && availableDates.length > 0 && (
        <div
          className="absolute left-1/2 -translate-x-1/2 z-50"
          style={{ bottom: 'max(env(safe-area-inset-bottom, 1.5rem), 1.5rem)' }}
        >
          <EstimatedDateRail
            dates={availableDates}
            selectedDate={selectedDate}
            onChange={setSelectedDate}
          />
        </div>
      )}

      {/* Logo - Lower Left (Floating) - Mobile Safe with safe area */}
      <div className="absolute left-4 sm:left-8 z-50" style={{ bottom: 'max(env(safe-area-inset-bottom, 1rem), 1rem)' }}>
        <div className="relative group">
          {/* Clean white button */}
          <button
            className="flex items-center justify-center cursor-pointer transform transition-all duration-200 hover:scale-105 active:scale-95"
            style={{
              background: '#FFFFFF',
              borderRadius: '16px',
              padding: '8px',
              boxShadow: '0 2px 8px rgba(0, 0, 0, 0.1), 0 4px 16px rgba(0, 0, 0, 0.05)',
              border: '1px solid rgba(0, 0, 0, 0.05)'
            }}
          >
            <img
              src="/hawanama-128.v1.png"
              alt="Hawanama Logo"
              width={128}
              height={128}
              className="w-12 h-12 sm:w-16 sm:h-16 object-contain"
            />
          </button>
          {/* About link: same white-pill treatment as the logo, kept small */}
          <a
            href="/about/"
            className="absolute left-full ml-2 bottom-1 text-xs font-medium text-gray-700 hover:text-black whitespace-nowrap"
            style={{
              background: '#FFFFFF',
              borderRadius: '10px',
              padding: '4px 8px',
              boxShadow: '0 2px 8px rgba(0, 0, 0, 0.1)',
              border: '1px solid rgba(0, 0, 0, 0.05)'
            }}
          >
            About
          </a>
        </div>
      </div>

      {/* Context Panel - ESTIMATED mode only, desktop only */}
      {viewMode === 'history' && selectedDate && (
        <div
          className="absolute right-4 sm:right-20 z-40 hidden md:block"
          style={{ top: 'max(env(safe-area-inset-top), 5rem)' }}
        >
          <EstimatedContextPanel selectedDate={selectedDate} />
        </div>
      )}

      {/* Cities Button - Mobile: Same level as logo, Desktop: Top Right */}
      <div className="absolute right-4 sm:right-8 sm:top-8 z-50" style={{ bottom: 'max(env(safe-area-inset-bottom, 1rem), 1rem)' }}>
        <button
          onClick={() => setShowCitySearch(!showCitySearch)}
          className="group flex items-center justify-center w-12 h-12 sm:w-14 sm:h-14 bg-black/20 backdrop-blur-md rounded-2xl border border-white/10 shadow-2xl hover:bg-black/30 transition-all duration-300 hover:scale-105"
          title="Search Cities"
        >
          <svg
            className="w-5 h-5 sm:w-6 sm:h-6 text-white group-hover:text-blue-300 transition-colors"
            fill="currentColor"
            viewBox="0 0 24 24"
          >
            <path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z"/>
          </svg>
        </button>
      </div>

      {/* Floating City Search - Mobile: Top right level with LIVE button, Desktop: Right of Cities Button */}
      {showCitySearch && (
        <div
          className="absolute right-4 sm:right-24 z-[60] animate-in slide-in-from-right-2 duration-300"
          style={{
            top: 'max(env(safe-area-inset-top), 1rem)',
          }}
        >
          <div className="sm:mt-6"> {/* Align with cities button - moved up slightly */}
            <CitySearch
              className="w-48 sm:w-80"
              onSelect={() => setShowCitySearch(false)}
            />
          </div>
        </div>
      )}

      {/* Station Card Popup — mounted only while a station is open */}
      {stationOpen && <StationCard />}
    </div>
  )
}
