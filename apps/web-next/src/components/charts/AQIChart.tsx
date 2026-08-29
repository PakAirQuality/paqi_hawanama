'use client'

import { useEffect, useRef } from 'react'
import * as Plot from '@observablehq/plot'
import { getAQIColorByValue, AQI_COLORS } from '@/components/map/config/aqiStyles'

interface Reading {
  ts: string
  aqi_raw?: number
  pm25?: number
  temp?: number
}

interface AQIChartProps {
  data: Reading[]
  metric?: 'aqi_raw' | 'pm25' | 'temp'
  title?: string
  height?: number
}

export default function AQIChart({ 
  data, 
  metric = 'aqi_raw', 
  title = 'AQI Trend',
  height = 300 
}: AQIChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  
  useEffect(() => {
    if (!containerRef.current || !data || data.length === 0) return
    
    // Filter out null/undefined values and sort by time
    const validData = data
      .filter(d => d[metric] != null)
      .map(d => ({
        date: new Date(d.ts),
        value: d[metric] as number,
        aqi: d.aqi_raw
      }))
      .sort((a, b) => a.date.getTime() - b.date.getTime())
    
    if (validData.length === 0) {
      containerRef.current.innerHTML = '<div class="flex items-center justify-center h-full text-gray-500"><p>No valid data for chart</p></div>'
      return
    }
    
    // Use centralized AQI color function
    const getAQIColor = (aqi: number | undefined) => {
      if (!aqi) return AQI_COLORS.fallback
      return getAQIColorByValue(aqi)
    }
    
    // Chart configuration
    const chartConfig: Plot.PlotOptions = {
      width: containerRef.current.clientWidth,
      height,
      marginLeft: 60,
      marginRight: 20,
      marginTop: 20,
      marginBottom: 40,
      x: {
        type: 'time',
        label: 'Time',
        tickFormat: '%H:%M'
      },
      y: {
        label: metric === 'aqi_raw' ? 'AQI' : 
              metric === 'pm25' ? 'PM2.5 (µg/m³)' : 
              'Temperature (°C)',
        grid: true
      },
      marks: [
        Plot.line(validData, {
          x: 'date',
          y: 'value',
          stroke: metric === 'aqi_raw' ? (d: { aqi?: number }) => getAQIColor(d.aqi) : '#3B82F6',
          strokeWidth: 2
        }),
        Plot.dot(validData, {
          x: 'date',
          y: 'value',
          fill: metric === 'aqi_raw' ? (d: { aqi?: number }) => getAQIColor(d.aqi) : '#3B82F6',
          r: 3
        })
      ]
    }
    
    // Add AQI background bands for AQI chart
    if (metric === 'aqi_raw') {
      const maxValue = Math.max(...validData.map(d => d.value))
      const bands = [
        { start: 0, end: 50, color: AQI_COLORS.good, label: 'Good' },
        { start: 50, end: 100, color: AQI_COLORS.moderate, label: 'Moderate' },
        { start: 100, end: 150, color: AQI_COLORS.unhealthy_sensitive, label: 'Unhealthy for Sensitive' },
        { start: 150, end: 200, color: AQI_COLORS.unhealthy, label: 'Unhealthy' },
        { start: 200, end: Math.max(300, maxValue), color: AQI_COLORS.very_unhealthy, label: 'Very Unhealthy' }
      ]
      
      chartConfig.marks.unshift(
        ...bands.map(band => 
          Plot.rect([band], {
            x1: validData[0]?.date,
            x2: validData[validData.length - 1]?.date,
            y1: band.start,
            y2: band.end,
            fill: band.color,
            fillOpacity: 0.1
          })
        )
      )
    }
    
    // Create and render the plot
    const plot = Plot.plot(chartConfig)
    
    // Clear container and append new plot
    containerRef.current.innerHTML = ''
    containerRef.current.appendChild(plot)
    
    // Cleanup function
    return () => {
      const container = containerRef.current
      if (container) {
        container.innerHTML = ''
      }
    }
  }, [data, metric, height])
  
  return (
    <div className="w-full">
      <div ref={containerRef} className="w-full" style={{ height: `${height}px` }} />
      {data.length === 0 && (
        <div className="flex items-center justify-center h-full text-gray-500">
          <p>No data available for chart</p>
        </div>
      )}
    </div>
  )
}