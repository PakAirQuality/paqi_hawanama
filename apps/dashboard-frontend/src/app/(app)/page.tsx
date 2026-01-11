"use client";

import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { useState } from 'react'
import { DashboardWidget } from '@/components/dashboard/DashboardWidget'
import { StationMap } from '@/components/dashboard/StationMap'
import { AlertsPanel } from '@/components/dashboard/AlertsPanel'
import { TopCitiesWidget } from '@/components/dashboard/TopCitiesWidget'
import { InteractivePakistanMap } from '@/components/dashboard/InteractivePakistanMap'
import { YearOverYearChart } from '@/components/charts/YearOverYearChart'
import { HeatmapChart } from '@/components/charts/HeatmapChart'

const API_BASE = "https://hawanama-152782825429.asia-south1.run.app";

type DashboardStats = {
  avg_pm25: number;
  active_stations: number;
  total_stations: number;
  last_update: string;
  total_cities: number;
  top_cities: Array<{
    city: string;
    avg_aqi: number;
    station_count: number;
  }>;
};

type StationListItem = {
  station_id: string;
  name: string;
  city?: string;
  provider?: string;
  active?: boolean;
  uptime_30d?: number;
  pm25_latest?: number;
  last_seen?: string;
};

async function fetchDashboardStats(): Promise<DashboardStats> {
  const res = await fetch(`${API_BASE}/api/v1/dashboard/stats`);
  if (!res.ok) throw new Error("Failed to load dashboard stats");
  return res.json();
}

async function fetchStations(): Promise<StationListItem[]> {
  const res = await fetch(`${API_BASE}/api/v1/internal/stations`);
  if (!res.ok) throw new Error("Failed to load stations");
  const data = await res.json();
  return data.stations ?? data;
}

export default function AQIDashboard() {
  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ["dashboard-stats"],
    queryFn: fetchDashboardStats,
  });

  const { data: stations } = useQuery({
    queryKey: ["stations-overview"],
    queryFn: fetchStations,
  });

  // Find stations needing attention
  const stationsNeedingAttention = stations?.filter(station => {
    if (!station.active) return true;
    if (station.uptime_30d !== undefined && station.uptime_30d < 0.9) return true;
    if (station.last_seen) {
      const lastSeen = new Date(station.last_seen);
      const dayAgo = new Date(Date.now() - 24 * 60 * 60 * 1000);
      if (lastSeen < dayAgo) return true;
    }
    return false;
  }).slice(0, 5) || [];

  const getStationStatus = (station: StationListItem) => {
    if (!station.active) return { label: "Offline", color: "bg-red-100 text-red-700" };
    if (station.uptime_30d !== undefined && station.uptime_30d < 0.9) {
      return { label: "Low Uptime", color: "bg-orange-100 text-orange-700" };
    }
    if (station.last_seen) {
      const lastSeen = new Date(station.last_seen);
      const dayAgo = new Date(Date.now() - 24 * 60 * 60 * 1000);
      if (lastSeen < dayAgo) {
        return { label: "No Data 24h", color: "bg-yellow-100 text-yellow-700" };
      }
    }
    return { label: "Unknown Issue", color: "bg-gray-100 text-gray-700" };
  };

  const getAqiColor = (aqi: number) => {
    if (aqi <= 50) return "bg-green-500";
    if (aqi <= 100) return "bg-yellow-500";
    if (aqi <= 150) return "bg-orange-500";
    if (aqi <= 200) return "bg-red-500";
    if (aqi <= 300) return "bg-purple-500";
    return "bg-red-900";
  };

  return (
    <div className="space-y-6">

      {/* Pakistan Air Quality Overview */}
      <InteractivePakistanMap />

      {/* Year-over-Year PM2.5 Trends */}
      <YearOverYearChart />

      {/* Air Quality Heatmap */}
      <Card className="w-full">
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                🗺️ Air Quality Heatmap
              </CardTitle>
              <p className="text-sm text-gray-600 mt-1">
                Hourly patterns over the last 30 days
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Badge variant="outline" className="bg-green-50 text-green-700 border-green-200">
                📍 Hourly
              </Badge>
            </div>
          </div>
          
          {/* AQI Legend */}
          <div className="flex flex-wrap items-center gap-3 mt-4">
            <div className="flex items-center gap-1">
              <div className="w-3 h-3 bg-green-500 rounded"></div>
              <span className="text-xs text-gray-600">Good (0-50)</span>
            </div>
            <div className="flex items-center gap-1">
              <div className="w-3 h-3 bg-yellow-500 rounded"></div>
              <span className="text-xs text-gray-600">Moderate (51-100)</span>
            </div>
            <div className="flex items-center gap-1">
              <div className="w-3 h-3 bg-orange-500 rounded"></div>
              <span className="text-xs text-gray-600">Unhealthy (101-150)</span>
            </div>
            <div className="flex items-center gap-1">
              <div className="w-3 h-3 bg-red-600 rounded"></div>
              <span className="text-xs text-gray-600">Hazardous (150+)</span>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <HeatmapChart height={500} />
        </CardContent>
      </Card>

      {/* Main Dashboard Grid - MonetX inspired widget layout */}
      <div className="grid gap-6 lg:grid-cols-3">
        {/* Station Map */}
        <div className="lg:col-span-2">
          <StationMap stations={stations} />
        </div>
        
        {/* Top Cities Widget */}
        <div>
          <TopCitiesWidget 
            topCities={stats?.top_cities}
            getAqiColor={getAqiColor}
          />
        </div>
      </div>

      {/* System Alerts - Moved Below Heatmap */}
      <Card className="w-full">
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              System Alerts
            </CardTitle>
            <Link 
              href="/admin" 
              className="text-sm text-blue-600 hover:text-blue-800 font-medium"
            >
              View All →
            </Link>
          </div>
          <p className="text-sm text-gray-600">
            Stations requiring immediate attention
          </p>
        </CardHeader>
        <CardContent>
          <AlertsPanel 
            stationsNeedingAttention={stationsNeedingAttention}
            getStationStatus={getStationStatus}
          />
        </CardContent>
      </Card>

      {/* Additional Insights Row */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="p-6">
          <h3 className="text-lg font-semibold mb-4">Recent Pollution Episodes</h3>
          <div className="text-center py-8">
            <div className="text-4xl mb-2">📊</div>
            <h4 className="font-medium mb-1">Episodes Detection</h4>
            <p className="text-sm text-gray-600 mb-4">
              Advanced episode detection and alerting system
            </p>
            <Link 
              href="/analytics" 
              className="inline-flex items-center text-sm text-blue-600 hover:text-blue-800 font-medium"
            >
              View Network Analytics →
            </Link>
          </div>
        </Card>
        
        <Card className="p-6">
          <h3 className="text-lg font-semibold mb-4">Data Quality Summary</h3>
          <div className="text-center py-8">
            <div className="text-4xl mb-2">🔍</div>
            <h4 className="font-medium mb-1">QA/QC Status</h4>
            <p className="text-sm text-gray-600 mb-4">
              Real-time data validation and quality assessment
            </p>
            <Link 
              href="/data-quality" 
              className="inline-flex items-center text-sm text-blue-600 hover:text-blue-800 font-medium"
            >
              View Data Quality →
            </Link>
          </div>
        </Card>
      </div>
    </div>
  )
}