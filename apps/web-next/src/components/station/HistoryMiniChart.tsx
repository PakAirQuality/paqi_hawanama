import { useState, useEffect } from 'react'
import { BarChart, Bar, XAxis, YAxis, ResponsiveContainer, CartesianGrid, ReferenceLine } from 'recharts'
import type { StationHistory, AQICategory } from '@/lib/apiClient'
import { getAQICategory } from '@/lib/aqi'

interface HistoryMiniChartProps {
  data: StationHistory[]
  categories: AQICategory[]
}

export function HistoryMiniChart({ data, categories }: HistoryMiniChartProps) {
  const [isMobile, setIsMobile] = useState(false)

  useEffect(() => {
    const checkIsMobile = () => {
      setIsMobile(window.innerWidth <= 768)
    }
    
    checkIsMobile()
    window.addEventListener('resize', checkIsMobile)
    return () => window.removeEventListener('resize', checkIsMobile)
  }, [])

  // Prepare chart data with colors using local time
  const chartData = data.map(item => {
    const category = getAQICategory(item.aqi_us, categories)
    const pkDate = new Date(item.timestamp_pk || item.timestamp)
    return {
      time: pkDate.getHours(),
      timeLabel: pkDate.toLocaleTimeString('en-US', { hour: '2-digit', hour12: false }),
      aqi: item.aqi_us,
      fill: category.color,
    }
  })

  // Mobile-optimized configuration for mini chart
  const mobileConfig = {
    margin: isMobile 
      ? { top: 3, right: 3, left: 3, bottom: 15 }
      : { top: 5, right: 5, left: 5, bottom: 5 },
    fontSize: isMobile ? 8 : 10,
    yAxisFontSize: isMobile ? 9 : 11,
    interval: isMobile ? Math.max(0, Math.floor(chartData.length / 6)) : 0,
    angle: isMobile ? -60 : -45,
    height: isMobile ? 35 : 40
  }

  return (
    <div className="h-28 sm:h-32">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={chartData} margin={mobileConfig.margin}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e5e5" horizontal={true} vertical={false} />
          <XAxis 
            dataKey="timeLabel" 
            axisLine={{ stroke: '#d1d5db' }}
            tickLine={{ stroke: '#d1d5db' }}
            tick={{ fontSize: mobileConfig.fontSize, fill: '#6B7280' }}
            interval={mobileConfig.interval}
            angle={mobileConfig.angle}
            textAnchor="end"
            height={mobileConfig.height}
          />
          <YAxis 
            axisLine={false}
            tickLine={false}
            tick={{ fontSize: mobileConfig.yAxisFontSize, fill: '#6B7280' }}
            domain={[0, 'dataMax']}
            width={isMobile ? 30 : 35}
          />
          <ReferenceLine y={0} stroke="#374151" strokeWidth={1} />
          <Bar 
            dataKey="aqi" 
            radius={[2, 2, 0, 0]}
            maxBarSize={isMobile ? 8 : 12}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}