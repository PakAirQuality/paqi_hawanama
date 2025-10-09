'use client'

import { useState } from 'react'
import MapWrapper from '@/components/map/MapWrapper'
import { StationCard } from '@/components/station/StationCard'
import { CitySearch } from '@/components/ui/CitySearch'
import { Search, X } from 'lucide-react'

export default function Home() {
  const [showCitySearch, setShowCitySearch] = useState(false)

  return (
    <div className="relative w-full overflow-hidden touch-none" style={{ 
      height: '100vh', 
      height: '100dvh',
      width: '100vw',
      maxWidth: '100vw',
      position: 'fixed',
      top: 0,
      left: 0,
      right: 0,
      bottom: 0
    }}>
      {/* Full Screen Map */}
      <MapWrapper className="absolute inset-0 w-full h-full touch-pan-x touch-pan-y" />
      
      {/* Live Data - Upper Left with safe area */}
      <div className="absolute top-safe-or-4 left-4 sm:top-8 sm:left-8 z-50" style={{ top: 'max(env(safe-area-inset-top), 1rem)' }}>
        <div className="flex items-center space-x-2 bg-black/20 backdrop-blur-md rounded-full px-4 py-2 border border-white/10 shadow-2xl">
          <div className="w-2 h-2 bg-green-400 rounded-full animate-pulse shadow-lg shadow-green-400/50"></div>
          <span className="text-xs font-medium text-white/90 tracking-wide">LIVE</span>
        </div>
      </div>

      {/* Logo - Lower Left (Floating) - Mobile Safe with safe area */}
      <div className="absolute left-4 sm:left-8 z-50" style={{ bottom: 'max(env(safe-area-inset-bottom, 1rem), 1rem)' }}>
        <div className="relative group">
          {/* Main container with blue button styling */}
          <div 
            className="relative flex items-center justify-center cursor-pointer overflow-visible transform transition-all duration-200 hover:brightness-110 group-hover:scale-105"
            style={{
              background: 'linear-gradient(135deg, #1899D6 0%, #0EA5E9 50%, #0284C7 100%)',
              border: 'solid transparent',
              borderRadius: '20px',
              borderWidth: '0 0 3px',
              color: '#FFFFFF',
              padding: '4px',
              boxSizing: 'border-box',
              boxShadow: '0 4px 15px rgba(24, 153, 214, 0.3)'
            }}
          >
            {/* Blue gradient shadow layer */}
            <div 
              className="absolute inset-0 -z-10"
              style={{
                background: 'linear-gradient(135deg, #1CB0F6 0%, #0EA5E9 100%)',
                border: 'solid transparent',
                borderRadius: '20px',
                borderWidth: '0 0 3px',
                bottom: '-3px',
                left: '0',
                right: '0',
                top: '0',
                backgroundClip: 'padding-box'
              }}
            ></div>
            
            <img 
              src="/hawanama.png" 
              alt="Hawanama Logo" 
              className="w-12 h-12 sm:w-16 sm:h-16 object-contain relative z-10 drop-shadow-lg"
              style={{
                filter: 'brightness(0) invert(1)' // Makes the logo white
              }}
            />
          </div>
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
          className="absolute right-4 sm:right-24 sm:bottom-auto z-[60] animate-in slide-in-from-right-2 duration-300"
          style={{ 
            top: 'max(env(safe-area-inset-top), 1rem)',
            '@media (min-width: 640px)': {
              top: '2rem'
            }
          }}
        >
          <CitySearch 
            className="w-48 sm:w-80" 
            onSelect={() => setShowCitySearch(false)}
          />
        </div>
      )}
      
      {/* Station Card Popup */}
      <StationCard />
    </div>
  )
}