"use client";

import { useQuery } from '@tanstack/react-query'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { useState } from 'react'
import { ChartWidget } from '@/components/charts/ChartWidget'
import { TimeSeriesChart } from '@/components/charts/TimeSeriesChart'
import { HeatmapChart } from '@/components/charts/HeatmapChart'

const API_BASE = "https://hawanama-152782825429.asia-south1.run.app";

interface NetworkMetric {
  metric: string
  value: number
  change_24h: number
  status: 'good' | 'warning' | 'critical'
}

interface Episode {
  episode_id: string
  start_time: string
  end_time?: string
  peak_pm25: number
  affected_cities: string[]
  station_count: number
  severity: 'moderate' | 'high' | 'extreme'
}

async function fetchNetworkAnalytics(): Promise<{
  network_metrics: NetworkMetric[]
  recent_episodes: Episode[]
}> {
  // This would be a new endpoint for network-wide analytics
  const res = await fetch(`${API_BASE}/api/v1/internal/analytics/network`);
  if (!res.ok) {
    // Mock data for demonstration
    return {
      network_metrics: [
        {
          metric: "Network Availability",
          value: 87.5,
          change_24h: -2.1,
          status: "warning"
        },
        {
          metric: "Average Data Latency",
          value: 8.2,
          change_24h: 1.3,
          status: "good"
        },
        {
          metric: "Network PM2.5 Mean",
          value: 89.4,
          change_24h: -5.7,
          status: "good"
        },
        {
          metric: "Quality Score",
          value: 78.9,
          change_24h: 0.8,
          status: "warning"
        }
      ],
      recent_episodes: [
        {
          episode_id: "ep_001",
          start_time: "2025-01-20T18:00:00Z",
          end_time: "2025-01-21T06:00:00Z",
          peak_pm25: 385,
          affected_cities: ["Lahore", "Faisalabad", "Multan"],
          station_count: 23,
          severity: "extreme"
        },
        {
          episode_id: "ep_002", 
          start_time: "2025-01-18T22:00:00Z",
          end_time: "2025-01-19T14:00:00Z",
          peak_pm25: 245,
          affected_cities: ["Karachi", "Hyderabad"],
          station_count: 12,
          severity: "high"
        }
      ]
    }
  }
  const data = await res.json();
  return data;
}

export default function NetworkAnalyticsPage() {
  const { data: analytics, isLoading } = useQuery({
    queryKey: ["network-analytics"],
    queryFn: fetchNetworkAnalytics,
  });

  const [selectedTimeframe, setSelectedTimeframe] = useState('7d')
  
  return (
    <div className="space-y-6">

      {/* Timeframe Selector */}
      <div className="flex items-center space-x-4">
        <span className="text-sm font-medium text-gray-700">Analysis Period:</span>
        <div className="flex bg-gray-100 rounded-lg p-1">
          {['24h', '7d', '30d', '90d'].map(period => (
            <button
              key={period}
              onClick={() => setSelectedTimeframe(period)}
              className={`px-3 py-1 text-sm font-medium rounded-md transition-colors ${
                selectedTimeframe === period 
                  ? 'bg-white text-gray-900 shadow-sm' 
                  : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              {period}
            </button>
          ))}
        </div>
      </div>

      {/* Network Health Metrics */}
      <div className="grid gap-4 md:grid-cols-4">
        {analytics?.network_metrics.map((metric, index) => (
          <Card key={index}>
            <CardContent className="p-6">
              <div className="flex items-center space-x-2 mb-2">
                <div className={`w-3 h-3 rounded-full ${
                  metric.status === 'good' ? 'bg-green-500' :
                  metric.status === 'warning' ? 'bg-yellow-500' : 'bg-red-500'
                }`}></div>
                <h3 className="text-sm font-medium text-gray-600">{metric.metric}</h3>
              </div>
              <div className="text-2xl font-bold text-gray-900">
                {metric.value.toFixed(1)}
                {metric.metric.includes('Availability') || metric.metric.includes('Score') ? '%' :
                 metric.metric.includes('Latency') ? 's' : 
                 metric.metric.includes('PM2.5') ? ' μg/m³' : ''}
              </div>
              <div className={`text-sm flex items-center space-x-1 ${
                metric.change_24h > 0 ? 'text-red-600' : 'text-green-600'
              }`}>
                <span>{metric.change_24h > 0 ? '↗' : '↘'}</span>
                <span>{Math.abs(metric.change_24h).toFixed(1)} (24h)</span>
              </div>
            </CardContent>
          </Card>
        )) || [...Array(4)].map((_, i) => (
          <Card key={i} className="animate-pulse">
            <CardContent className="p-6">
              <div className="h-4 bg-gray-200 rounded w-24 mb-2"></div>
              <div className="h-8 bg-gray-200 rounded w-16 mb-1"></div>
              <div className="h-3 bg-gray-200 rounded w-20"></div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Main Analytics Grid */}
      <div className="grid gap-6 lg:grid-cols-2">
        {/* Network-wide Trends Chart */}
        <ChartWidget 
          title="Network-wide PM₂.₅ Trends" 
          subtitle="Multi-city time series with episode markers"
          headerActions={
            <div className="flex items-center space-x-2">
              <button className="px-3 py-1 text-xs bg-blue-100 text-blue-700 rounded-full hover:bg-blue-200 transition-colors">
                Multi-City
              </button>
              <button className="px-3 py-1 text-xs text-gray-600 hover:text-gray-800 transition-colors">
                📊
              </button>
            </div>
          }
          minHeight="320px"
        >
          <TimeSeriesChart
            height={260}
            title="Network Average PM₂.₅"
          />
        </ChartWidget>

        {/* Geographic Heatmap */}
        <ChartWidget 
          title="Geographic Patterns" 
          subtitle="Hourly AQI distribution analysis"
          headerActions={
            <div className="flex items-center space-x-2">
              <button className="px-3 py-1 text-xs bg-green-100 text-green-700 rounded-full hover:bg-green-200 transition-colors">
                Regional
              </button>
              <button className="px-3 py-1 text-xs text-gray-600 hover:text-gray-800 transition-colors">
                🗺️
              </button>
            </div>
          }
          minHeight="320px"
        >
          <HeatmapChart
            height={260}
            title="Regional AQI Patterns"
          />
        </ChartWidget>
      </div>

      {/* Pollution Episodes */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="text-lg font-semibold flex items-center space-x-2">
              <span>🚨</span>
              <span>Recent Pollution Episodes</span>
            </CardTitle>
            <Badge variant="outline" className="text-xs">
              Last {selectedTimeframe}
            </Badge>
          </div>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-3">
              {[...Array(3)].map((_, i) => (
                <div key={i} className="animate-pulse">
                  <div className="flex items-center justify-between p-4 bg-gray-50 rounded-lg">
                    <div className="space-y-2">
                      <div className="h-4 bg-gray-300 rounded w-32"></div>
                      <div className="h-3 bg-gray-300 rounded w-48"></div>
                    </div>
                    <div className="h-6 bg-gray-300 rounded w-16"></div>
                  </div>
                </div>
              ))}
            </div>
          ) : analytics?.recent_episodes?.length ? (
            <div className="space-y-3">
              {analytics.recent_episodes.map((episode) => (
                <div key={episode.episode_id} className="p-4 bg-gray-50 rounded-lg hover:bg-gray-100 transition-colors">
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <div className="flex items-center space-x-3 mb-2">
                        <Badge className={`text-xs ${
                          episode.severity === 'extreme' ? 'bg-red-100 text-red-700 border-red-200' :
                          episode.severity === 'high' ? 'bg-orange-100 text-orange-700 border-orange-200' :
                          'bg-yellow-100 text-yellow-700 border-yellow-200'
                        }`}>
                          {episode.severity.toUpperCase()}
                        </Badge>
                        <div className="text-sm font-medium">
                          Peak: {episode.peak_pm25} μg/m³
                        </div>
                      </div>
                      
                      <div className="space-y-1">
                        <div className="text-sm text-gray-600">
                          <span className="font-medium">Duration:</span> {
                            new Date(episode.start_time).toLocaleDateString()
                          } - {
                            episode.end_time ? new Date(episode.end_time).toLocaleDateString() : 'Ongoing'
                          }
                        </div>
                        
                        <div className="text-sm text-gray-600">
                          <span className="font-medium">Affected:</span> {episode.affected_cities.join(', ')} 
                          <span className="ml-2">({episode.station_count} stations)</span>
                        </div>
                      </div>
                    </div>
                    
                    <button className="text-sm text-blue-600 hover:text-blue-800 font-medium">
                      View Details →
                    </button>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center py-8">
              <div className="text-3xl mb-2">✨</div>
              <h4 className="font-medium text-gray-700">No Episodes Detected</h4>
              <p className="text-sm text-gray-500 mt-1">
                No significant pollution episodes in the selected timeframe
              </p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Additional Analytics Tools */}
      <div className="grid gap-6 lg:grid-cols-3">
        <ChartWidget 
          title="Statistical Summary" 
          subtitle="Network-wide data distributions"
          minHeight="240px"
        >
          <div className="space-y-4">
            <div className="text-center py-8">
              <div className="text-3xl mb-2">📈</div>
              <h4 className="font-medium text-gray-700">Network Statistics</h4>
              <p className="text-sm text-gray-500 mt-2">
                Statistical analysis coming soon
              </p>
            </div>
          </div>
        </ChartWidget>
        
        <ChartWidget 
          title="Custom Reports" 
          subtitle="Generate analytics reports"
          minHeight="240px"
        >
          <div className="space-y-4">
            <div className="text-center py-8">
              <div className="text-3xl mb-2">📝</div>
              <h4 className="font-medium text-gray-700">Report Builder</h4>
              <p className="text-sm text-gray-500 mt-2">
                Custom report generation coming soon
              </p>
            </div>
          </div>
        </ChartWidget>
        
        <ChartWidget 
          title="Alert Configuration" 
          subtitle="Network monitoring alerts"
          minHeight="240px"
        >
          <div className="space-y-4">
            <div className="text-center py-8">
              <div className="text-3xl mb-2">⚙️</div>
              <h4 className="font-medium text-gray-700">Alert Settings</h4>
              <p className="text-sm text-gray-500 mt-2">
                Alert configuration coming soon
              </p>
            </div>
          </div>
        </ChartWidget>
      </div>
    </div>
  )
}