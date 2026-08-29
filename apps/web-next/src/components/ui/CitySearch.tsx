'use client'

import { useState, useEffect, useRef, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { Search, MapPin } from 'lucide-react'

interface City {
  id: number
  name: string
  state: string
  slug: string
  station_count: number
  avg_aqi?: number
}

interface CitySearchProps {
  className?: string
  onSelect?: () => void
}

export function CitySearch({ className = '', onSelect }: CitySearchProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [searchTerm, setSearchTerm] = useState('')
  const [filteredCities, setFilteredCities] = useState<City[]>([])
  const searchRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const router = useRouter()

  // Fetch cities data
  const { data: citiesData, isLoading } = useQuery({
    queryKey: ['cities'],
    queryFn: () => api.getCities(),
    staleTime: 5 * 60 * 1000, // 5 minutes
  })

  // Memoize cities array to prevent unnecessary re-renders
  const cities = useMemo(() => citiesData?.cities || [], [citiesData?.cities])

  // Filter cities based on search term
  useEffect(() => {
    if (!searchTerm.trim()) {
      setFilteredCities(cities.slice(0, 8)) // Show top 8 cities when no search
    } else {
      const filtered = cities
        .filter((city: City) => 
          city.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
          city.state.toLowerCase().includes(searchTerm.toLowerCase())
        )
        .slice(0, 8) // Limit to 8 results
      setFilteredCities(filtered)
    }
  }, [searchTerm, cities])

  // Handle click outside to close dropdown
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (searchRef.current && !searchRef.current.contains(event.target as Node)) {
        setIsOpen(false)
      }
    }

    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const handleCitySelect = (city: City) => {
    setSearchTerm('')
    setIsOpen(false)
    router.push(`/city/${city.slug}`)
    onSelect?.() // Call the onSelect callback if provided
  }

  const handleInputFocus = () => {
    setIsOpen(true)
  }

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setSearchTerm(e.target.value)
    setIsOpen(true)
  }

  const getAqiColor = (aqi?: number) => {
    if (!aqi) return 'text-gray-500'
    if (aqi <= 50) return 'text-green-600'
    if (aqi <= 100) return 'text-yellow-600'
    if (aqi <= 150) return 'text-orange-600'
    if (aqi <= 200) return 'text-red-600'
    return 'text-purple-600'
  }

  return (
    <div ref={searchRef} className={`relative ${className}`}>
      <div className="relative">
        <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-white/70 h-4 w-4" />
        <input
          ref={inputRef}
          type="text"
          placeholder="Search cities..."
          value={searchTerm}
          onChange={handleInputChange}
          onFocus={handleInputFocus}
          className="w-full pl-10 pr-4 py-3 text-sm border border-white/30 rounded-2xl focus:outline-none focus:ring-2 focus:ring-blue-400/50 focus:border-blue-400/50 bg-white/20 backdrop-blur-sm placeholder-black/70 text-black min-w-0"
        />
      </div>

      {isOpen && (
        <div className="absolute top-full left-0 right-0 mt-2 bg-white/90 backdrop-blur-2xl border border-white/40 rounded-2xl shadow-2xl z-50 max-h-80 overflow-y-auto overflow-x-hidden">
          {isLoading ? (
            <div className="p-3 text-center text-gray-600 text-sm">
              Loading cities...
            </div>
          ) : filteredCities.length > 0 ? (
            <div className="py-1">
              {filteredCities.map((city) => (
                <button
                  key={city.id}
                  onClick={() => handleCitySelect(city)}
                  className="w-full px-3 py-2 text-left hover:bg-black/10 flex items-center justify-between group transition-colors overflow-hidden"
                >
                  <div className="flex items-center space-x-2 min-w-0 flex-1 overflow-hidden">
                    <MapPin className="h-3 w-3 text-gray-600 group-hover:text-blue-600 flex-shrink-0" />
                    <div className="min-w-0 flex-1 overflow-hidden">
                      <div className="text-sm font-medium text-black truncate">
                        {city.name}
                      </div>
                      <div className="text-xs text-gray-600 truncate">
                        {city.state} • {city.station_count} stations
                      </div>
                    </div>
                  </div>
                  {city.avg_aqi && (
                    <div className="text-right flex-shrink-0 ml-2">
                      <div className={`text-xs font-semibold ${getAqiColor(city.avg_aqi)}`}>
                        {Math.round(city.avg_aqi)}
                      </div>
                    </div>
                  )}
                </button>
              ))}
            </div>
          ) : searchTerm.trim() ? (
            <div className="p-3 text-center text-gray-600 text-sm">
              No cities found matching "{searchTerm}"
            </div>
          ) : (
            <div className="p-3 text-center text-gray-600 text-sm">
              Start typing to search cities
            </div>
          )}
        </div>
      )}
    </div>
  )
}