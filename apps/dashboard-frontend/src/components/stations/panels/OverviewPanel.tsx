"use client";

import { useQuery } from "@tanstack/react-query";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { getAqiLabel } from "@/lib/api";

const API_BASE = "https://hawanama-152782825429.asia-south1.run.app";

type Overview = {
  station_id: string;
  name: string;
  city: string;
  provider: string;
  coordinates: {
    latitude: number;
    longitude: number;
  };
  status: 'online' | 'offline';
  current_reading: {
    pm25: number;
    aqi: number;
    timestamp: string;
  };
  summary_stats: {
    pm25_24h_avg: number;
    pm25_7d_avg: number;
    pm25_95th_percentile: number;
  };
  health_flags: string[];
  sparkline_data: Array<{
    timestamp: string;
    pm25: number;
  }>;
};

async function fetchOverview(stationId: string): Promise<Overview> {
  const res = await fetch(`${API_BASE}/api/v1/internal/stations/${stationId}/overview`);
  if (!res.ok) throw new Error("Failed to load overview");
  return res.json();
}

export function OverviewPanel({ stationId }: { stationId: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["station-overview", stationId],
    queryFn: () => fetchOverview(stationId),
  });

  if (isLoading) {
    return (
      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-4">
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
    );
  }

  if (error || !data) {
    return (
      <div className="text-destructive p-4 bg-destructive/10 rounded-lg">
        Error loading overview: {error?.message}
      </div>
    );
  }

  const sparklineData = data.sparkline_data?.map(point => ({
    timestamp: new Date(point.timestamp).getHours(),
    pm25: point.pm25,
  })) || [];

  return (
    <div className="space-y-6">
      {/* Metric Cards */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Current PM₂.₅
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {data.current_reading?.pm25.toFixed(1)} μg/m³
            </div>
            <p className="text-sm text-muted-foreground">
              AQI {data.current_reading?.aqi} ({getAqiLabel(data.current_reading?.aqi || 0)})
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              24h Average
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {data.summary_stats?.pm25_24h_avg.toFixed(1)} μg/m³
            </div>
            <p className="text-sm text-muted-foreground">
              Last 24 hours
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              7d Average
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {data.summary_stats?.pm25_7d_avg.toFixed(1)} μg/m³
            </div>
            <p className="text-sm text-muted-foreground">
              Last 7 days
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              95th Percentile
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {data.summary_stats?.pm25_95th_percentile.toFixed(1)} μg/m³
            </div>
            <p className="text-sm text-muted-foreground">
              Peak levels
            </p>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        {/* Sparkline Chart */}
        <Card>
          <CardHeader>
            <CardTitle>Recent Trend (24h)</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={sparklineData}>
                  <XAxis 
                    dataKey="timestamp" 
                    type="number" 
                    scale="linear"
                    domain={[0, 23]}
                    tickFormatter={(value) => `${value}:00`}
                  />
                  <YAxis />
                  <Tooltip 
                    labelFormatter={(value) => `${value}:00`}
                    formatter={(value: any) => [`${value.toFixed(1)} μg/m³`, 'PM₂.₅']}
                  />
                  <Line 
                    type="monotone" 
                    dataKey="pm25" 
                    stroke="hsl(var(--primary))" 
                    strokeWidth={2}
                    dot={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>

        {/* Station Info & Health */}
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Station Details</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Location</span>
                <span className="font-medium">
                  {data.coordinates.latitude.toFixed(4)}°, {data.coordinates.longitude.toFixed(4)}°
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Provider</span>
                <span className="font-medium">{data.provider}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Status</span>
                <span className={`font-medium ${data.status === 'online' ? 'text-green-600' : 'text-red-600'}`}>
                  {data.status === 'online' ? 'Online' : 'Offline'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Last Update</span>
                <span className="font-medium">
                  {new Date(data.current_reading?.timestamp || '').toLocaleString()}
                </span>
              </div>
            </CardContent>
          </Card>

          {data.health_flags.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Health Flags</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  {data.health_flags.map((flag, index) => (
                    <div key={index} className="text-sm text-orange-600 bg-orange-50 px-3 py-2 rounded">
                      {flag}
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {data.health_flags.length === 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Health Status</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-sm text-green-600 bg-green-50 px-3 py-2 rounded">
                  ✅ No health issues detected
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}