'use client'

import { useEffect, useState } from 'react'

interface TimeSeriesChartProps {
  title?: string
  height?: number
  data?: Array<{ timestamp: string; value: number }>
  loading?: boolean
}

export function TimeSeriesChart({ 
  title = 'PM₂.₅ Concentration',
  height = 300,
  data = [],
  loading = false 
}: TimeSeriesChartProps) {
  const [isClient, setIsClient] = useState(false)
  
  useEffect(() => {
    setIsClient(true)
  }, [])

  // Generate mock real-time data if no data provided
  const mockData = data.length > 0 ? data : generateMockTimeSeriesData()
  
  const series = [{
    name: 'PM₂.₅ (μg/m³)',
    data: mockData.map(point => ({
      x: new Date(point.timestamp).getTime(),
      y: point.value
    }))
  }]

  const options: ApexOptions = {
    chart: {
      type: 'area',
      height: height,
      zoom: {
        enabled: true,
        type: 'x'
      },
      toolbar: {
        show: true,
        tools: {
          download: true,
          selection: true,
          zoom: true,
          zoomin: true,
          zoomout: true,
          pan: true,
          reset: true
        }
      },
      animations: {
        enabled: true,
        easing: 'easeinout',
        speed: 800
      }
    },
    colors: ['#3B82F6'],
    fill: {
      type: 'gradient',
      gradient: {
        shade: 'light',
        type: 'vertical',
        shadeIntensity: 0.5,
        gradientToColors: ['#93C5FD'],
        inverseColors: false,
        opacityFrom: 0.8,
        opacityTo: 0.1,
      }
    },
    stroke: {
      curve: 'smooth',
      width: 2
    },
    grid: {
      borderColor: '#f1f5f9',
      strokeDashArray: 3
    },
    xaxis: {
      type: 'datetime',
      labels: {
        style: {
          colors: '#64748b',
          fontSize: '12px'
        }
      }
    },
    yaxis: {
      title: {
        text: 'PM₂.₅ (μg/m³)',
        style: {
          color: '#64748b',
          fontSize: '12px'
        }
      },
      labels: {
        style: {
          colors: '#64748b',
          fontSize: '12px'
        }
      }
    },
    tooltip: {
      shared: true,
      intersect: false,
      x: {
        format: 'dd MMM yyyy HH:mm'
      },
      y: {
        formatter: (val) => `${val.toFixed(1)} μg/m³`
      }
    },
    legend: {
      show: true,
      position: 'top',
      horizontalAlign: 'left',
      fontFamily: 'Inter, sans-serif',
      fontSize: '12px',
      labels: {
        colors: '#64748b'
      }
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center" style={{ height }}>
        <div className="animate-pulse text-gray-500">Loading chart data...</div>
      </div>
    )
  }

  if (!isClient) {
    return (
      <div className="flex items-center justify-center" style={{ height }}>
        <div className="text-gray-500">Initializing chart...</div>
      </div>
    )
  }

  return (
    <div className="time-series-chart flex items-center justify-center" style={{ height }}>
      <div className="text-center py-8">
        <div className="text-3xl mb-2">📈</div>
        <h4 className="font-medium text-gray-700">Time Series Chart</h4>
        <p className="text-sm text-gray-500 mt-2">
          Chart visualization coming soon
        </p>
      </div>
    </div>
  )
}

// Mock data generator for demonstration
function generateMockTimeSeriesData() {
  const data = []
  const now = new Date()
  
  for (let i = 47; i >= 0; i--) {
    const timestamp = new Date(now.getTime() - i * 30 * 60 * 1000) // 30-minute intervals
    const baseValue = 85
    const variation = Math.sin(i / 8) * 30 + Math.random() * 20
    const value = Math.max(0, baseValue + variation)
    
    data.push({
      timestamp: timestamp.toISOString(),
      value: Math.round(value * 10) / 10
    })
  }
  
  return data
}