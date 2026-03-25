'use client'

import { useState, useEffect, useCallback } from 'react'
import MapWrapper from '@/components/map/MapWrapper'
import { StationCard } from '@/components/station/StationCard'
import { CitySearch } from '@/components/ui/CitySearch'
import { ModelToggle } from '@/components/map/ModelToggle'

export default function Home() {
  const [showCitySearch, setShowCitySearch] = useState(false)
  const [modelVariant, setModelVariant] = useState<'backbone' | 'support_aware'>('backbone')

  const handleModelToggle = useCallback((supportAware: boolean) => {
    setModelVariant(supportAware ? 'support_aware' : 'backbone')
  }, [])

  // Prevent body scrolling on map page only
  useEffect(() => {
    const originalStyle = window.getComputedStyle(document.body).overflow
    document.body.style.overflow = 'hidden'

    return () => {
      document.body.style.overflow = originalStyle
    }
  }, [])

  return (
    <div className="map-page relative w-full h-full overflow-hidden" style={{
      height: '100vh',
      height: '100dvh',
      width: '100vw',
      maxWidth: '100vw'
    }}>
      {/* Full Screen Map */}
      <MapWrapper className="absolute inset-0 w-full h-full" windVisible={true} modelVariant={modelVariant} />

      {/* Live Data + Model Toggle - Upper Left with safe area */}
      <div className="absolute top-safe-or-4 left-4 sm:top-8 sm:left-8 z-50 flex flex-col gap-2" style={{ top: 'max(env(safe-area-inset-top), 1rem)' }}>
        <div className="flex items-center space-x-2 bg-black/20 backdrop-blur-md rounded-full px-4 py-2 border border-white/10 shadow-2xl">
          <div className="w-2 h-2 bg-green-400 rounded-full animate-pulse shadow-lg shadow-green-400/50"></div>
          <span className="text-xs font-medium text-white/90 tracking-wide">LIVE</span>
        </div>
        <ModelToggle onToggle={handleModelToggle} />
      </div>

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
              src="/hawanama.png"
              alt="Hawanama Logo"
              className="w-12 h-12 sm:w-16 sm:h-16 object-contain"
            />
          </button>
        </div>
      </div>

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

      {/* Station Card Popup */}
      <StationCard />
    </div>
  )
}
