'use client'

import { useState } from 'react'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'

const cities = ['Lahore', 'Karachi', 'Islamabad', 'Faisalabad', 'Rawalpindi', 'Multan', 'Peshawar', 'Quetta']
const providers = ['IQAir', 'Punjab EPA', 'Urban Unit', 'AirGradient', 'US Embassy']
const stationStates = ['Active', 'Offline', 'Maintenance', 'Unknown']

export function GlobalFilters() {
  const [isOpen, setIsOpen] = useState(false)
  const [selectedCities, setSelectedCities] = useState<string[]>([])
  const [selectedProviders, setSelectedProviders] = useState<string[]>([])
  const [selectedStates, setSelectedStates] = useState<string[]>(['Active'])
  
  const activeFiltersCount = selectedCities.length + selectedProviders.length + (selectedStates.length > 0 ? 1 : 0)
  
  const toggleFilter = (value: string, current: string[], setter: (values: string[]) => void) => {
    if (current.includes(value)) {
      setter(current.filter(v => v !== value))
    } else {
      setter([...current, value])
    }
  }
  
  return (
    <div className="relative">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="inline-flex items-center px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
      >
        <span className="mr-2">🔍</span>
        Filters
        {activeFiltersCount > 0 && (
          <Badge className="ml-2 bg-blue-500 text-white text-xs">
            {activeFiltersCount}
          </Badge>
        )}
        <svg className="ml-2 h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      
      {isOpen && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setIsOpen(false)} />
          <Card className="absolute right-0 z-20 mt-2 w-80 bg-white shadow-lg border border-gray-200 rounded-md">
            <div className="p-4">
              <div className="text-sm font-medium text-gray-900 mb-4">
                Global Filters
              </div>
              
              {/* Cities */}
              <div className="mb-4">
                <div className="text-sm font-medium text-gray-700 mb-2">Cities</div>
                <div className="flex flex-wrap gap-2">
                  {cities.map((city) => (
                    <button
                      key={city}
                      onClick={() => toggleFilter(city, selectedCities, setSelectedCities)}
                      className={`px-3 py-1 text-xs rounded-full border transition-colors ${
                        selectedCities.includes(city)
                          ? 'bg-blue-100 text-blue-700 border-blue-300'
                          : 'bg-gray-50 text-gray-600 border-gray-200 hover:bg-gray-100'
                      }`}
                    >
                      {city}
                    </button>
                  ))}
                </div>
              </div>
              
              {/* Providers */}
              <div className="mb-4">
                <div className="text-sm font-medium text-gray-700 mb-2">Providers</div>
                <div className="flex flex-wrap gap-2">
                  {providers.map((provider) => (
                    <button
                      key={provider}
                      onClick={() => toggleFilter(provider, selectedProviders, setSelectedProviders)}
                      className={`px-3 py-1 text-xs rounded-full border transition-colors ${
                        selectedProviders.includes(provider)
                          ? 'bg-green-100 text-green-700 border-green-300'
                          : 'bg-gray-50 text-gray-600 border-gray-200 hover:bg-gray-100'
                      }`}
                    >
                      {provider}
                    </button>
                  ))}
                </div>
              </div>
              
              {/* Station States */}
              <div className="mb-4">
                <div className="text-sm font-medium text-gray-700 mb-2">Station Status</div>
                <div className="flex flex-wrap gap-2">
                  {stationStates.map((state) => (
                    <button
                      key={state}
                      onClick={() => toggleFilter(state, selectedStates, setSelectedStates)}
                      className={`px-3 py-1 text-xs rounded-full border transition-colors ${
                        selectedStates.includes(state)
                          ? 'bg-orange-100 text-orange-700 border-orange-300'
                          : 'bg-gray-50 text-gray-600 border-gray-200 hover:bg-gray-100'
                      }`}
                    >
                      {state}
                    </button>
                  ))}
                </div>
              </div>
              
              <div className="flex justify-between pt-2 border-t border-gray-100">
                <button
                  onClick={() => {
                    setSelectedCities([])
                    setSelectedProviders([])
                    setSelectedStates(['Active'])
                  }}
                  className="text-sm text-gray-600 hover:text-gray-900 transition-colors"
                >
                  Clear All
                </button>
                <button
                  onClick={() => setIsOpen(false)}
                  className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 transition-colors"
                >
                  Apply
                </button>
              </div>
            </div>
          </Card>
        </>
      )}
    </div>
  )
}