"use client";

import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { useState } from 'react'

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

export default function DashboardHome() {
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
    <div className="space-y-8">
      {/* Header */}
      <div className="space-y-2">
        <h2 className="text-3xl font-bold">Dashboard</h2>
        <p className="text-muted-foreground">
          System snapshot and network health overview
        </p>
      </div>

      {/* System Snapshot */}
      <div className="space-y-4">
        <h3 className="text-lg font-semibold">System Snapshot</h3>
        {statsLoading ? (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            {[...Array(4)].map((_, i) => (
              <Card key={i} className="animate-pulse">
                <CardHeader className="pb-2">
                  <div className="h-4 bg-muted rounded w-24"></div>
                </CardHeader>
                <CardContent>
                  <div className="h-8 bg-muted rounded w-16"></div>
                </CardContent>
              </Card>
            ))}
          </div>
        ) : stats ? (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                  Average PM₂.₅
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{stats.avg_pm25.toFixed(1)} μg/m³</div>
                <p className="text-xs text-muted-foreground">Last 24 hours (non-Punjab EPA)</p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                  Stations Online
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">
                  {stats.active_stations}/{stats.total_stations}
                </div>
                <p className="text-xs text-muted-foreground">
                  {((stats.active_stations / stats.total_stations) * 100).toFixed(1)}% operational
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                  Last Data Update
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{stats.last_update}</div>
                <p className="text-xs text-muted-foreground">Most recent reading</p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                  Cities Covered
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{stats.total_cities}</div>
                <p className="text-xs text-muted-foreground">Monitoring locations</p>
              </CardContent>
            </Card>
          </div>
        ) : (
          <Card className="p-6">
            <p className="text-destructive">Failed to load system stats</p>
          </Card>
        )}
      </div>

      <div className="grid gap-8 lg:grid-cols-2">
        {/* Stations Needing Attention */}
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-semibold">Stations Needing Attention</h3>
            <Link href="/stations" className="text-sm text-primary hover:underline">
              View all stations →
            </Link>
          </div>
          
          {stationsNeedingAttention.length === 0 ? (
            <Card className="p-6 text-center">
              <div className="text-4xl mb-2">✅</div>
              <p className="text-muted-foreground">All stations operating normally</p>
            </Card>
          ) : (
            <Card>
              <CardContent className="p-0">
                <div className="divide-y">
                  {stationsNeedingAttention.map((station) => {
                    const status = getStationStatus(station);
                    return (
                      <div
                        key={station.station_id}
                        className="p-4 hover:bg-muted/50 cursor-pointer transition-colors"
                        onClick={() => {
                          // TODO: Navigate to /stations with this station pre-selected
                          window.location.href = '/stations';
                        }}
                      >
                        <div className="flex items-center justify-between">
                          <div>
                            <div className="font-medium">{station.name}</div>
                            <div className="text-sm text-muted-foreground">
                              {station.city} • {station.provider}
                            </div>
                          </div>
                          <Badge className={`text-xs ${status.color}`}>
                            {status.label}
                          </Badge>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </CardContent>
            </Card>
          )}
        </div>

        {/* Top Cities Right Now */}
        <div className="space-y-4">
          <h3 className="text-lg font-semibold">Top Cities Right Now</h3>
          {stats?.top_cities ? (
            <Card>
              <CardContent className="p-0">
                <div className="divide-y">
                  {stats.top_cities.slice(0, 6).map((cityData, index) => (
                    <div key={index} className="p-4 flex items-center justify-between">
                      <div className="flex items-center space-x-3">
                        <div 
                          className={`w-3 h-3 rounded-full ${getAqiColor(cityData.avg_aqi)}`}
                        ></div>
                        <div>
                          <div className="font-medium">{cityData.city}</div>
                          <div className="text-sm text-muted-foreground">
                            {cityData.station_count} station{cityData.station_count !== 1 ? 's' : ''}
                          </div>
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="font-medium">AQI {cityData.avg_aqi}</div>
                        <div className="text-sm text-muted-foreground">24h avg</div>
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          ) : (
            <Card className="p-6">
              <p className="text-muted-foreground text-center">Loading city data...</p>
            </Card>
          )}
        </div>
      </div>

      {/* Recent Episodes Placeholder */}
      <div className="space-y-4">
        <h3 className="text-lg font-semibold">Recent Pollution Episodes</h3>
        <Card className="p-6 text-center">
          <div className="text-4xl mb-2">📊</div>
          <h4 className="font-medium mb-1">Episodes Overview Coming Soon</h4>
          <p className="text-sm text-muted-foreground">
            Will show recent high-AQI events across all stations.
          </p>
          <Link href="/stations" className="text-sm text-primary hover:underline">
            View individual station episodes →
          </Link>
        </Card>
      </div>

      {/* Quick Navigation */}
      <div className="space-y-4">
        <h3 className="text-lg font-semibold">Quick Actions</h3>
        <div className="grid gap-4 md:grid-cols-2">
          <Link href="/stations">
            <Card className="p-4 hover:shadow-md transition-shadow cursor-pointer">
              <div className="flex items-center space-x-3">
                <div className="h-10 w-10 rounded-lg bg-primary/10 flex items-center justify-center">
                  <svg className="h-5 w-5 text-primary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 14l-5 -5l-2 2l-3 -3l6 6" />
                  </svg>
                </div>
                <div>
                  <h4 className="font-medium">Station Management</h4>
                  <p className="text-sm text-muted-foreground">
                    Detailed station analytics and monitoring
                  </p>
                </div>
              </div>
            </Card>
          </Link>

          <Card className="p-4 opacity-60">
            <div className="flex items-center space-x-3">
              <div className="h-10 w-10 rounded-lg bg-muted flex items-center justify-center">
                <svg className="h-5 w-5 text-muted-foreground" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                </svg>
              </div>
              <div>
                <h4 className="font-medium">Network Reports</h4>
                <p className="text-sm text-muted-foreground">
                  System-wide analytics (Coming Soon)
                </p>
              </div>
            </div>
          </Card>
        </div>
      </div>
    </div>
  )
}