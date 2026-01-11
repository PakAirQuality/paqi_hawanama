'use client'

import { useEffect, useState } from 'react'
import dynamic from 'next/dynamic'
import { ApexOptions } from 'apexcharts'

const Chart = dynamic(() => import('react-apexcharts'), { ssr: false })

interface HeatmapDataPoint {
  x: string
  y: number
}

interface HeatmapChartProps {
  title?: string
  height?: number
  data?: Array<{ name: string; data: HeatmapDataPoint[] }>
  loading?: boolean
}

export function HeatmapChart({
  title = 'Hourly AQI Heatmap',
  height = 300,
  data = [],
  loading = false
}: HeatmapChartProps) {
  const [isClient, setIsClient] = useState(false)
  
  useEffect(() => {
    setIsClient(true)
  }, [])

  // Generate mock heatmap data if no data provided
  const mockData = data.length > 0 ? data : generateMockHeatmapData()

  const options: ApexOptions = {
    chart: {
      type: 'heatmap',
      height: height,
      toolbar: {
        show: true
      }
    },
    plotOptions: {
      heatmap: {
        shadeIntensity: 0.5,
        radius: 0,
        useFillColorAsStroke: true,
        colorScale: {
          ranges: [
            {
              from: 0,
              to: 50,
              name: 'Good',
              color: '#10B981'
            },
            {
              from: 51,
              to: 100,
              name: 'Moderate',
              color: '#F59E0B'
            },
            {
              from: 101,
              to: 150,
              name: 'Unhealthy for Sensitive',
              color: '#F97316'
            },
            {
              from: 151,
              to: 200,
              name: 'Unhealthy',
              color: '#EF4444'
            },
            {
              from: 201,
              to: 300,
              name: 'Very Unhealthy',
              color: '#7C3AED'
            },
            {
              from: 301,
              to: 500,
              name: 'Hazardous',
              color: '#7F1D1D'
            }
          ]
        }
      }
    },
    dataLabels: {
      enabled: false
    },
    stroke: {
      width: 1
    },
    grid: {
      borderColor: '#f1f5f9'
    },
    xaxis: {
      type: 'category',
      categories: ['00', '02', '04', '06', '08', '10', '12', '14', '16', '18', '20', '22'],
      title: {
        text: 'Hour of Day',
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
        text: 'Day of Month',
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
      y: {
        formatter: (val) => `AQI: ${val.toFixed(0)}`
      }
    },
    legend: {
      show: true,
      position: 'bottom',
      horizontalAlign: 'center',
      fontFamily: 'Inter, sans-serif',
      fontSize: '11px',
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
    <div className="heatmap-chart">
      <Chart
        options={options}
        series={mockData}
        type="heatmap"
        height={height}
      />
    </div>
  )
}

// Mock data generator for heatmap (30 days x 12 time periods)
function generateMockHeatmapData() {
  const series = []
  const hours = ['00', '02', '04', '06', '08', '10', '12', '14', '16', '18', '20', '22']
  
  for (let day = 1; day <= 30; day++) {
    const dayData: HeatmapDataPoint[] = hours.map(hour => {
      // Simulate higher pollution during morning (6-10) and evening (18-22) rush hours
      let baseValue = 60
      const hourNum = parseInt(hour)
      
      if (hourNum >= 6 && hourNum <= 10) {
        baseValue += 40 + Math.random() * 30 // Morning rush
      } else if (hourNum >= 18 && hourNum <= 22) {
        baseValue += 35 + Math.random() * 25 // Evening rush
      } else if (hourNum >= 0 && hourNum <= 4) {
        baseValue += 20 + Math.random() * 20 // Night
      } else {
        baseValue += Math.random() * 15 // Day time
      }
      
      // Add some seasonal/weekly variation
      baseValue += Math.sin(day / 7) * 15
      
      return {
        x: hour,
        y: Math.round(Math.max(0, baseValue))
      }
    })
    
    series.push({
      name: `Day ${day}`,
      data: dayData
    })
  }
  
  return series
}