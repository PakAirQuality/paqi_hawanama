'use client'

import { useState } from 'react'
import { Card } from '@/components/ui/card'

const timePeriods = [
  { id: '5min', label: '5 Min', value: 5 },
  { id: '15min', label: '15 Min', value: 15 },
  { id: '1hour', label: '1 Hour', value: 60 },
  { id: '6hour', label: '6 Hours', value: 360 },
  { id: '24hour', label: '24 Hours', value: 1440 },
  { id: 'today', label: 'Today', value: 'today' },
  { id: 'yesterday', label: 'Yesterday', value: 'yesterday' },
  { id: '7days', label: '7 Days', value: 7 * 1440 },
  { id: '30days', label: '30 Days', value: 30 * 1440 },
]

export function TimePeriodSelector() {
  const [selectedPeriod, setSelectedPeriod] = useState('24hour')
  const [isOpen, setIsOpen] = useState(false)
  
  const currentPeriod = timePeriods.find(p => p.id === selectedPeriod)
  
  return (
    <div className="relative">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="inline-flex items-center px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
      >
        <span className="mr-2">🕐</span>
        {currentPeriod?.label}
        <svg className="ml-2 h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      
      {isOpen && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setIsOpen(false)} />
          <Card className="absolute right-0 z-20 mt-2 w-56 bg-white shadow-lg border border-gray-200 rounded-md">
            <div className="p-2">
              <div className="text-sm font-medium text-gray-900 px-2 py-1 border-b border-gray-100 mb-2">
                Time Period
              </div>
              <div className="grid grid-cols-2 gap-1">
                {timePeriods.map((period) => (
                  <button
                    key={period.id}
                    onClick={() => {
                      setSelectedPeriod(period.id)
                      setIsOpen(false)
                    }}
                    className={`px-3 py-2 text-sm rounded-md text-left hover:bg-gray-50 transition-colors ${
                      selectedPeriod === period.id 
                        ? 'bg-blue-50 text-blue-700 font-medium' 
                        : 'text-gray-700'
                    }`}
                  >
                    {period.label}
                  </button>
                ))}
              </div>
              <div className="border-t border-gray-100 mt-2 pt-2">
                <button
                  className="w-full px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 rounded-md text-left transition-colors"
                  onClick={() => {
                    // TODO: Open custom time range modal
                    setIsOpen(false)
                  }}
                >
                  Custom Range...
                </button>
              </div>
            </div>
          </Card>
        </>
      )}
    </div>
  )
}