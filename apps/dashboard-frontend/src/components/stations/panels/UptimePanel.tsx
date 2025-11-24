"use client";

import { useQuery } from "@tanstack/react-query";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts';

const API_BASE = "https://hawanama-152782825429.asia-south1.run.app";

type UptimeData = {
  station_id: string;
  uptime_30d: number;
  daily_uptime: Array<{
    date: string;
    uptime_percent: number;
  }>;
};

async function fetchUptime(stationId: string): Promise<UptimeData> {
  const res = await fetch(`${API_BASE}/api/v1/internal/stations/${stationId}/uptime`);
  if (!res.ok) throw new Error("Failed to load uptime data");
  return res.json();
}

export function UptimePanel({ stationId }: { stationId: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["station-uptime", stationId],
    queryFn: () => fetchUptime(stationId),
  });

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div className="grid gap-6 md:grid-cols-3">
          {[...Array(3)].map((_, i) => (
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
        Error loading uptime data: {error?.message}
      </div>
    );
  }

  const uptimeChartData = data.daily_uptime.map(day => ({
    date: new Date(day.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
    uptime: day.uptime_percent,
    fill: day.uptime_percent >= 95 ? '#6ecc39' : day.uptime_percent >= 90 ? '#f0c20c' : '#ef7855'
  }));

  const averageUptime = data.daily_uptime.length > 0 
    ? data.daily_uptime.reduce((acc, day) => acc + day.uptime_percent, 0) / data.daily_uptime.length 
    : 0;

  const goodDays = data.daily_uptime.filter(day => day.uptime_percent >= 95).length;
  const totalDays = data.daily_uptime.length;

  return (
    <div className="space-y-6">
      {/* Uptime Metrics */}
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              30-Day Uptime
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">
              {(data.uptime_30d * 100).toFixed(1)}%
            </div>
            <p className="text-sm text-muted-foreground">
              Overall availability
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Good Days (≥95%)
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">
              {goodDays}/{totalDays}
            </div>
            <p className="text-sm text-muted-foreground">
              {((goodDays / totalDays) * 100).toFixed(1)}% of days
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Average Daily
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">
              {averageUptime.toFixed(1)}%
            </div>
            <p className="text-sm text-muted-foreground">
              Daily average
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Uptime Chart */}
      <Card>
        <CardHeader>
          <CardTitle>Daily Uptime (Last 30 Days)</CardTitle>
          <p className="text-sm text-muted-foreground">
            Green: ≥95% | Yellow: 90-95% | Red: &lt;90%
          </p>
        </CardHeader>
        <CardContent>
          <div className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={uptimeChartData} margin={{ top: 20, right: 30, left: 20, bottom: 5 }}>
                <XAxis 
                  dataKey="date" 
                  tick={{ fontSize: 12 }}
                  interval="preserveStartEnd"
                />
                <YAxis 
                  domain={[0, 100]}
                  tick={{ fontSize: 12 }}
                  label={{ value: 'Uptime (%)', angle: -90, position: 'insideLeft' }}
                />
                <Tooltip 
                  formatter={(value: any) => [`${value.toFixed(1)}%`, 'Uptime']}
                  labelStyle={{ color: '#000' }}
                />
                <ReferenceLine y={95} stroke="#6ecc39" strokeDasharray="5 5" />
                <ReferenceLine y={90} stroke="#f0c20c" strokeDasharray="5 5" />
                <Bar 
                  dataKey="uptime" 
                  radius={[2, 2, 0, 0]}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      {/* Insights */}
      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Availability Standards</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center justify-between p-3 rounded-lg bg-green-50">
              <span className="font-medium">Excellent (≥95%)</span>
              <span className="text-green-600 font-bold">
                {goodDays} days
              </span>
            </div>
            <div className="flex items-center justify-between p-3 rounded-lg bg-yellow-50">
              <span className="font-medium">Good (90-95%)</span>
              <span className="text-yellow-600 font-bold">
                {data.daily_uptime.filter(day => day.uptime_percent >= 90 && day.uptime_percent < 95).length} days
              </span>
            </div>
            <div className="flex items-center justify-between p-3 rounded-lg bg-red-50">
              <span className="font-medium">Poor (&lt;90%)</span>
              <span className="text-red-600 font-bold">
                {data.daily_uptime.filter(day => day.uptime_percent < 90).length} days
              </span>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Insights</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <p className="text-sm font-medium">Reliability Score</p>
              <div className="flex items-center mt-1">
                <div className="flex-1 bg-muted rounded-full h-2 mr-3">
                  <div 
                    className="h-2 rounded-full bg-gradient-to-r from-red-500 via-yellow-500 to-green-500" 
                    style={{ width: `${data.uptime_30d * 100}%` }}
                  ></div>
                </div>
                <span className="text-sm font-medium">
                  {data.uptime_30d >= 0.95 ? 'Excellent' : 
                   data.uptime_30d >= 0.90 ? 'Good' : 'Needs Attention'}
                </span>
              </div>
            </div>
            
            {data.uptime_30d < 0.95 && (
              <div className="p-3 bg-orange-50 rounded-lg">
                <p className="text-sm text-orange-700">
                  <strong>Recommendation:</strong> Station uptime below 95% target. 
                  Consider checking sensor connectivity and power supply.
                </p>
              </div>
            )}

            {data.uptime_30d >= 0.95 && (
              <div className="p-3 bg-green-50 rounded-lg">
                <p className="text-sm text-green-700">
                  <strong>Excellent Performance:</strong> Station exceeds 95% uptime target. 
                  Consistent and reliable data collection.
                </p>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}