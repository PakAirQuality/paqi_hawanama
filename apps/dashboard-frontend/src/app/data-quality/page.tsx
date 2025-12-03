"use client";

import { useQuery } from '@tanstack/react-query'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { useState } from 'react'
import { ChartWidget } from '@/components/charts/ChartWidget'
import { ScatterChart } from '@/components/charts/ScatterChart'

const API_BASE = "https://hawanama-152782825429.asia-south1.run.app";

interface QualityMetric {
  station_id: string
  name: string
  city?: string
  provider?: string
  coverage_30d: number
  flatline_fraction: number
  bias_vs_neighbors?: number
  correlation_neighbors?: number
  ml_readiness: 'GOOD_FOR_ML' | 'CAUTION' | 'EXCLUDE'
}

async function fetchQualityMetrics(): Promise<QualityMetric[]> {
  // This would be a new endpoint that calculates QA/QC metrics
  const res = await fetch(`${API_BASE}/api/v1/internal/data-quality/metrics`);
  if (!res.ok) {
    // Mock data for now
    return [
      {
        station_id: "1", name: "Township Station", city: "Lahore", provider: "IQAir",
        coverage_30d: 0.92, flatline_fraction: 0.02, bias_vs_neighbors: -2.1,
        correlation_neighbors: 0.87, ml_readiness: "GOOD_FOR_ML"
      },
      {
        station_id: "2", name: "DHA Station", city: "Lahore", provider: "Urban Unit", 
        coverage_30d: 0.78, flatline_fraction: 0.15, bias_vs_neighbors: 8.5,
        correlation_neighbors: 0.45, ml_readiness: "CAUTION"
      },
      {
        station_id: "3", name: "Mall Road", city: "Lahore", provider: "Punjab EPA",
        coverage_30d: 0.35, flatline_fraction: 0.45, bias_vs_neighbors: 25.2,
        correlation_neighbors: 0.12, ml_readiness: "EXCLUDE"
      }
    ]
  }
  const data = await res.json();
  return data.metrics ?? data;
}

export default function DataQualityPage() {
  const { data: metrics, isLoading } = useQuery({
    queryKey: ["data-quality-metrics"],
    queryFn: fetchQualityMetrics,
  });

  const [filterML, setFilterML] = useState<string>('all')
  const [minCoverage, setMinCoverage] = useState(0)
  
  const filteredMetrics = metrics?.filter(metric => {
    if (filterML !== 'all' && metric.ml_readiness !== filterML) return false
    if (metric.coverage_30d < minCoverage / 100) return false
    return true
  }) || []
  
  const mlCounts = metrics?.reduce((acc, metric) => {
    acc[metric.ml_readiness] = (acc[metric.ml_readiness] || 0) + 1
    return acc
  }, {} as Record<string, number>) || {}

  return (
    <div className="space-y-6">

      {/* High-level Metrics */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center space-x-2 mb-2">
              <span className="text-lg">✅</span>
              <h3 className="text-sm font-medium text-gray-600">ML Ready</h3>
            </div>
            <div className="text-2xl font-bold text-green-600">
              {mlCounts['GOOD_FOR_ML'] || 0}
            </div>
            <p className="text-sm text-gray-500">High quality stations</p>
          </CardContent>
        </Card>
        
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center space-x-2 mb-2">
              <span className="text-lg">⚠️</span>
              <h3 className="text-sm font-medium text-gray-600">Caution</h3>
            </div>
            <div className="text-2xl font-bold text-yellow-600">
              {mlCounts['CAUTION'] || 0}
            </div>
            <p className="text-sm text-gray-500">Moderate quality</p>
          </CardContent>
        </Card>
        
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center space-x-2 mb-2">
              <span className="text-lg">❌</span>
              <h3 className="text-sm font-medium text-gray-600">Exclude</h3>
            </div>
            <div className="text-2xl font-bold text-red-600">
              {mlCounts['EXCLUDE'] || 0}
            </div>
            <p className="text-sm text-gray-500">Poor quality</p>
          </CardContent>
        </Card>
        
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center space-x-2 mb-2">
              <span className="text-lg">📊</span>
              <h3 className="text-sm font-medium text-gray-600">Total Stations</h3>
            </div>
            <div className="text-2xl font-bold text-gray-900">
              {metrics?.length || 0}
            </div>
            <p className="text-sm text-gray-500">In quality assessment</p>
          </CardContent>
        </Card>
      </div>

      {/* Filters and Controls */}
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Card>
            <CardHeader>
              <CardTitle className="text-lg font-semibold flex items-center space-x-2">
                <span>🔍</span>
                <span>Quality Filters & Dataset Builder</span>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* ML Readiness Filter */}
              <div className="grid gap-4 md:grid-cols-2">
                <div>
                  <label className="text-sm font-medium text-gray-700 mb-2 block">
                    ML Readiness Level
                  </label>
                  <select 
                    value={filterML}
                    onChange={(e) => setFilterML(e.target.value)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="all">All Levels</option>
                    <option value="GOOD_FOR_ML">Good for ML</option>
                    <option value="CAUTION">Caution</option>
                    <option value="EXCLUDE">Exclude</option>
                  </select>
                </div>
                
                <div>
                  <label className="text-sm font-medium text-gray-700 mb-2 block">
                    Min Coverage (%)
                  </label>
                  <input
                    type="range"
                    min="0"
                    max="100"
                    value={minCoverage}
                    onChange={(e) => setMinCoverage(Number(e.target.value))}
                    className="w-full"
                  />
                  <div className="text-sm text-gray-600 mt-1">{minCoverage}%</div>
                </div>
              </div>
              
              <div className="flex items-center justify-between pt-4 border-t border-gray-200">
                <div className="text-sm text-gray-600">
                  {filteredMetrics.length} stations match criteria
                </div>
                <div className="space-x-2">
                  <button className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900 transition-colors">
                    Reset Filters
                  </button>
                  <button className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 transition-colors">
                    Export ML Dataset
                  </button>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
        
        {/* Data Quality Visualization */}
        <div>
          <ChartWidget 
            title="Quality Assessment" 
            subtitle="Coverage vs Bias Analysis"
            minHeight="340px"
          >
            <ScatterChart
              height={280}
              data={filteredMetrics.map(metric => ({
                x: metric.coverage_30d * 100,
                y: metric.bias_vs_neighbors || 0,
                label: metric.name,
                category: metric.ml_readiness === 'GOOD_FOR_ML' ? 'Good for ML' : 
                        metric.ml_readiness === 'CAUTION' ? 'Caution' : 'Exclude'
              }))}
              xAxisTitle="Coverage (%)"
              yAxisTitle="Bias vs Neighbors (μg/m³)"
            />
          </ChartWidget>
        </div>
      </div>

      {/* Station Quality Table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg font-semibold flex items-center space-x-2">
            <span>📋</span>
            <span>Station Quality Assessment</span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="text-center py-8 text-gray-500">Loading quality metrics...</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-200">
                    <th className="text-left py-3 px-2">Station</th>
                    <th className="text-left py-3 px-2">Coverage</th>
                    <th className="text-left py-3 px-2">Flatline %</th>
                    <th className="text-left py-3 px-2">Bias vs Neighbors</th>
                    <th className="text-left py-3 px-2">Correlation</th>
                    <th className="text-left py-3 px-2">ML Readiness</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredMetrics.map((metric) => (
                    <tr key={metric.station_id} className="border-b border-gray-100 hover:bg-gray-50">
                      <td className="py-3 px-2">
                        <div>
                          <div className="font-medium">{metric.name}</div>
                          <div className="text-xs text-gray-600">{metric.city} • {metric.provider}</div>
                        </div>
                      </td>
                      <td className="py-3 px-2">
                        <div className="flex items-center space-x-2">
                          <div className="w-12 bg-gray-200 rounded-full h-2">
                            <div
                              className={`h-2 rounded-full ${
                                metric.coverage_30d > 0.9 ? 'bg-green-500' :
                                metric.coverage_30d > 0.7 ? 'bg-yellow-500' : 'bg-red-500'
                              }`}
                              style={{ width: `${metric.coverage_30d * 100}%` }}
                            ></div>
                          </div>
                          <span className="text-xs">{(metric.coverage_30d * 100).toFixed(0)}%</span>
                        </div>
                      </td>
                      <td className="py-3 px-2">
                        <span className={`text-xs ${
                          metric.flatline_fraction < 0.05 ? 'text-green-600' :
                          metric.flatline_fraction < 0.2 ? 'text-yellow-600' : 'text-red-600'
                        }`}>
                          {(metric.flatline_fraction * 100).toFixed(1)}%
                        </span>
                      </td>
                      <td className="py-3 px-2">
                        {metric.bias_vs_neighbors ? (
                          <span className={`text-xs ${
                            Math.abs(metric.bias_vs_neighbors) < 5 ? 'text-green-600' :
                            Math.abs(metric.bias_vs_neighbors) < 15 ? 'text-yellow-600' : 'text-red-600'
                          }`}>
                            {metric.bias_vs_neighbors > 0 ? '+' : ''}{metric.bias_vs_neighbors.toFixed(1)} μg/m³
                          </span>
                        ) : (
                          <span className="text-xs text-gray-400">N/A</span>
                        )}
                      </td>
                      <td className="py-3 px-2">
                        {metric.correlation_neighbors ? (
                          <span className={`text-xs ${
                            metric.correlation_neighbors > 0.8 ? 'text-green-600' :
                            metric.correlation_neighbors > 0.5 ? 'text-yellow-600' : 'text-red-600'
                          }`}>
                            {metric.correlation_neighbors.toFixed(2)}
                          </span>
                        ) : (
                          <span className="text-xs text-gray-400">N/A</span>
                        )}
                      </td>
                      <td className="py-3 px-2">
                        <Badge className={`text-xs ${
                          metric.ml_readiness === 'GOOD_FOR_ML' 
                            ? 'bg-green-100 text-green-700 border-green-200'
                            : metric.ml_readiness === 'CAUTION'
                            ? 'bg-yellow-100 text-yellow-700 border-yellow-200'
                            : 'bg-red-100 text-red-700 border-red-200'
                        }`}>
                          {metric.ml_readiness === 'GOOD_FOR_ML' ? 'Good' : 
                           metric.ml_readiness === 'CAUTION' ? 'Caution' : 'Exclude'}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}