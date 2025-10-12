import { BarChart, Bar, XAxis, YAxis, ResponsiveContainer } from 'recharts'
import type { StationHistory, AQICategory } from '@/lib/apiClient'
import { getAQICategory } from '@/lib/aqi'

interface HistoryMiniChartProps {
  data: StationHistory[]
  categories: AQICategory[]
}

export function HistoryMiniChart({ data, categories }: HistoryMiniChartProps) {
  // Prepare chart data with colors using Pakistan time
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

  return (
    <div className="h-32">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={chartData} margin={{ top: 5, right: 5, left: 5, bottom: 5 }}>
          <XAxis 
            dataKey="timeLabel" 
            axisLine={false}
            tickLine={false}
            tick={{ fontSize: 10, fill: '#6B7280' }}
            interval={0}
            angle={-45}
            textAnchor="end"
            height={40}
          />
          <YAxis 
            axisLine={false}
            tickLine={false}
            tick={{ fontSize: 11, fill: '#6B7280' }}
            domain={[0, 'dataMax']}
          />
          <Bar 
            dataKey="aqi" 
            radius={[2, 2, 0, 0]}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}