'use client'

import { ChartWidget } from '@/components/charts/ChartWidget'
import { TimeSeriesChart } from '@/components/charts/TimeSeriesChart'
import { useState, useEffect } from 'react'

export function RealtimeChart() {
  const [isLoading, setIsLoading] = useState(true)
  
  useEffect(() => {
    // Simulate loading
    const timer = setTimeout(() => setIsLoading(false), 1500)
    return () => clearTimeout(timer)
  }, [])
  
  const headerActions = (
    <div className="flex items-center space-x-2">
      <button className="px-3 py-1 text-xs bg-blue-100 text-blue-700 rounded-full hover:bg-blue-200 transition-colors">
        Live
      </button>
      <button className="px-3 py-1 text-xs text-gray-600 hover:text-gray-800 transition-colors">
        ⚙️
      </button>
    </div>
  )
  
  return (
    <ChartWidget 
      title="Real-time PM₂.₅ Trends"
      subtitle="Network-wide average over last 24 hours"
      headerActions={headerActions}
      minHeight="400px"
    >
      <TimeSeriesChart
        height={320}
        loading={isLoading}
      />
    </ChartWidget>
  )
}