"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';

const API_BASE = "https://hawanama-152782825429.asia-south1.run.app";

type DiurnalData = {
  station_id: string;
  diurnal_pattern: Array<{
    hour: number;
    mean_pm25: number;
    median_pm25: number;
    weekday: boolean;
  }>;
  peak_hour: number;
  cleanest_hour: number;
};

async function fetchDiurnal(stationId: string): Promise<DiurnalData> {
  const res = await fetch(`${API_BASE}/api/v1/internal/stations/${stationId}/diurnal`);
  if (!res.ok) throw new Error("Failed to load diurnal data");
  return res.json();
}

export function DiurnalPanel({ stationId }: { stationId: string }) {
  const [showWeekend, setShowWeekend] = useState(false);
  
  const { data, isLoading, error } = useQuery({
    queryKey: ["station-diurnal", stationId],
    queryFn: () => fetchDiurnal(stationId),
  });

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div className="grid gap-6 md:grid-cols-2">
          {[...Array(2)].map((_, i) => (
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
        <Card className="h-96 animate-pulse bg-muted"></Card>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="text-destructive p-4 bg-destructive/10 rounded-lg">
        Error loading diurnal data: {error?.message}
      </div>
    );
  }

  // Separate weekday and weekend data
  const weekdayData = data.diurnal_pattern
    .filter(point => point.weekday)
    .map(point => ({
      hour: point.hour,
      mean_pm25: point.mean_pm25,
      median_pm25: point.median_pm25,
    }));

  const weekendData = data.diurnal_pattern
    .filter(point => !point.weekday)
    .map(point => ({
      hour: point.hour,
      mean_pm25: point.mean_pm25,
      median_pm25: point.median_pm25,
    }));

  // Combine data for chart
  const chartData = Array.from({ length: 24 }, (_, hour) => {
    const weekdayPoint = weekdayData.find(p => p.hour === hour);
    const weekendPoint = weekendData.find(p => p.hour === hour);
    
    return {
      hour,
      weekday_mean: weekdayPoint?.mean_pm25 || 0,
      weekend_mean: weekendPoint?.mean_pm25 || 0,
    };
  });

  const maxWeekday = Math.max(...weekdayData.map(p => p.mean_pm25));
  const maxWeekend = Math.max(...weekendData.map(p => p.mean_pm25));
  const minWeekday = Math.min(...weekdayData.map(p => p.mean_pm25));
  const minWeekend = Math.min(...weekendData.map(p => p.mean_pm25));

  return (
    <div className="space-y-6">
      {/* Summary Metrics */}
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Peak Pollution Hour
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">
              {String(data.peak_hour).padStart(2, '0')}:00
            </div>
            <p className="text-sm text-muted-foreground">
              Highest average PM₂.₅
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Cleanest Hour
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">
              {String(data.cleanest_hour).padStart(2, '0')}:00
            </div>
            <p className="text-sm text-muted-foreground">
              Lowest average PM₂.₅
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Diurnal Pattern Chart */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Diurnal Pattern</CardTitle>
              <p className="text-sm text-muted-foreground">
                Average PM₂.₅ concentration by hour of day
              </p>
            </div>
            <div className="flex items-center space-x-4">
              <label className="flex items-center space-x-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={showWeekend}
                  onChange={(e) => setShowWeekend(e.target.checked)}
                  className="rounded"
                />
                <span className="text-sm">Show Weekend</span>
              </label>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData} margin={{ top: 20, right: 30, left: 20, bottom: 5 }}>
                <XAxis 
                  dataKey="hour" 
                  tick={{ fontSize: 12 }}
                  tickFormatter={(value) => `${value}:00`}
                  domain={[0, 23]}
                />
                <YAxis 
                  tick={{ fontSize: 12 }}
                  label={{ value: 'PM₂.₅ (μg/m³)', angle: -90, position: 'insideLeft' }}
                />
                <Tooltip 
                  labelFormatter={(value) => `${value}:00`}
                  formatter={(value: any, name: string) => [
                    `${value.toFixed(1)} μg/m³`, 
                    name.includes('weekday') ? 'Weekday' : 'Weekend'
                  ]}
                />
                <Line 
                  type="monotone" 
                  dataKey="weekday_mean" 
                  stroke="hsl(var(--primary))" 
                  strokeWidth={2}
                  name="Weekday Mean"
                  dot={false}
                />
                {showWeekend && (
                  <Line 
                    type="monotone" 
                    dataKey="weekend_mean" 
                    stroke="hsl(var(--destructive))" 
                    strokeWidth={2}
                    strokeDasharray="5 5"
                    name="Weekend Mean"
                    dot={false}
                  />
                )}
              </LineChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      {/* Pattern Analysis */}
      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Pattern Analysis</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <p className="text-sm font-medium mb-2">Weekday vs Weekend</p>
              <div className="space-y-2">
                <div className="flex justify-between items-center">
                  <span className="text-sm text-muted-foreground">Weekday Peak</span>
                  <span className="font-medium">{maxWeekday.toFixed(1)} μg/m³</span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-sm text-muted-foreground">Weekend Peak</span>
                  <span className="font-medium">{maxWeekend.toFixed(1)} μg/m³</span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-sm text-muted-foreground">Difference</span>
                  <span className="font-medium">
                    {Math.abs(maxWeekday - maxWeekend).toFixed(1)} μg/m³
                    {maxWeekday > maxWeekend ? ' higher weekdays' : ' higher weekends'}
                  </span>
                </div>
              </div>
            </div>

            <div>
              <p className="text-sm font-medium mb-2">Daily Variation</p>
              <div className="space-y-2">
                <div className="flex justify-between items-center">
                  <span className="text-sm text-muted-foreground">Weekday Range</span>
                  <span className="font-medium">
                    {(maxWeekday - minWeekday).toFixed(1)} μg/m³
                  </span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-sm text-muted-foreground">Weekend Range</span>
                  <span className="font-medium">
                    {(maxWeekend - minWeekend).toFixed(1)} μg/m³
                  </span>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Insights</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="p-3 bg-blue-50 rounded-lg">
              <p className="text-sm text-blue-700">
                <strong>Rush Hour Impact:</strong> {' '}
                {data.peak_hour >= 7 && data.peak_hour <= 9 ? 
                  'Morning rush hour shows peak pollution levels.' :
                  data.peak_hour >= 17 && data.peak_hour <= 19 ?
                  'Evening rush hour shows peak pollution levels.' :
                  'Peak pollution occurs outside typical rush hours.'
                }
              </p>
            </div>

            <div className="p-3 bg-green-50 rounded-lg">
              <p className="text-sm text-green-700">
                <strong>Clean Air Window:</strong> {' '}
                Best air quality typically around {String(data.cleanest_hour).padStart(2, '0')}:00, 
                making it an optimal time for outdoor activities.
              </p>
            </div>

            {Math.abs(maxWeekday - maxWeekend) > 10 && (
              <div className="p-3 bg-orange-50 rounded-lg">
                <p className="text-sm text-orange-700">
                  <strong>Weekend Effect:</strong> {' '}
                  Significant difference between weekday and weekend patterns suggests 
                  traffic or industrial influence.
                </p>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}