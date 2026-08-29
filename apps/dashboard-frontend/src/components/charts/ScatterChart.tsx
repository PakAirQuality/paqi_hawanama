'use client'

import { useEffect, useState } from 'react'
import dynamic from 'next/dynamic'
import { ApexOptions } from 'apexcharts'

const Chart = dynamic(() => import('react-apexcharts'), { ssr: false })

interface ScatterDataPoint {
  x: number
  y: number
  label?: string
  category?: string
}

interface ScatterChartProps {
  title?: string
  height?: number
  data?: ScatterDataPoint[]
  xAxisTitle?: string
  yAxisTitle?: string
  loading?: boolean
}

export function ScatterChart({
  title = 'Data Quality Assessment',
  height = 300,
  data = [],
  xAxisTitle = 'Coverage (%)',
  yAxisTitle = 'Bias vs Neighbors (μg/m³)',
  loading = false
}: ScatterChartProps) {
  const [isClient, setIsClient] = useState(false)
  
  useEffect(() => {
    setIsClient(true)
  }, [])

  // Generate mock data for QA/QC analysis if no data provided
  const mockData = data.length > 0 ? data : generateMockQualityData()
  
  // Group data by category for different series
  const groupedData = mockData.reduce((acc, point) => {
    const category = point.category || 'Unknown'
    if (!acc[category]) {
      acc[category] = []
    }
    acc[category].push([point.x, point.y])
    return acc
  }, {} as Record<string, number[][]>)

  const series = Object.entries(groupedData).map(([category, points]) => ({
    name: category,
    data: points
  }))

  const colors = ['#10B981', '#F59E0B', '#EF4444', '#6366F1'] // green, amber, red, indigo

  const options: ApexOptions = {
    chart: {
      type: 'scatter',
      height: height,
      zoom: {
        enabled: true,
        type: 'xy'
      },
      toolbar: {
        show: true
      }
    },
    colors: colors,
    grid: {
      borderColor: '#f1f5f9',
      strokeDashArray: 3
    },
    xaxis: {
      title: {
        text: xAxisTitle,
        style: {
          color: '#64748b',
          fontSize: '12px'
        }
      },
      labels: {
        style: {
          colors: '#64748b',
          fontSize: '11px'
        }
      }
    },
    yaxis: {
      title: {
        text: yAxisTitle,
        style: {
          color: '#64748b',
          fontSize: '12px'
        }
      },
      labels: {
        style: {
          colors: '#64748b',
          fontSize: '11px'
        }
      }
    },
    tooltip: {
      shared: false,
      intersect: true,
      x: {
        formatter: (val) => `${xAxisTitle}: ${val.toFixed(1)}`
      },
      y: {
        formatter: (val) => `${yAxisTitle}: ${val.toFixed(1)}`
      }
    },
    legend: {
      show: true,
      position: 'top',
      horizontalAlign: 'right',
      fontFamily: 'Inter, sans-serif',
      fontSize: '12px',
      labels: {
        colors: '#64748b'
      }
    },
    markers: {
      size: 6,
      strokeWidth: 2,
      strokeColors: '#fff',
      hover: {
        sizeOffset: 3
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
    <div className="scatter-chart flex items-center justify-center" style={{ height }}>
      <div className="text-center py-8">
        <div className="text-3xl mb-2">📊</div>
        <h4 className="font-medium text-gray-700">Scatter Plot</h4>
        <p className="text-sm text-gray-500 mt-2">
          Quality assessment visualization coming soon
        </p>
      </div>
    </div>
  )
}

// Mock data generator for QA/QC analysis
function generateMockQualityData(): ScatterDataPoint[] {
  const data: ScatterDataPoint[] = []
  
  // Good stations (high coverage, low bias)
  for (let i = 0; i < 15; i++) {
    data.push({
      x: 85 + Math.random() * 15, // 85-100% coverage
      y: -5 + Math.random() * 10, // -5 to +5 bias
      category: 'Good for ML',
      label: `Station ${i + 1}`
    })
  }
  
  // Caution stations (medium coverage or medium bias)
  for (let i = 0; i < 10; i++) {
    data.push({
      x: 65 + Math.random() * 25, // 65-90% coverage
      y: -15 + Math.random() * 30, // -15 to +15 bias
      category: 'Caution',
      label: `Station ${i + 16}`
    })
  }
  
  // Exclude stations (low coverage or high bias)
  for (let i = 0; i < 8; i++) {
    data.push({
      x: 20 + Math.random() * 50, // 20-70% coverage
      y: -30 + Math.random() * 60, // -30 to +30 bias
      category: 'Exclude',
      label: `Station ${i + 26}`
    })
  }
  
  return data
}