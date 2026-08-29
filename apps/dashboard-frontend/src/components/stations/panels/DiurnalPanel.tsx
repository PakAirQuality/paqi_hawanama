"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Area,
  ComposedChart,
} from "recharts";

const API_BASE = "https://hawanama-152782825429.asia-south1.run.app";

type HourBucket = {
  hour_local: number;
  mean: number;
  p10: number;
  p50: number;
  p90: number;
  count: number;
};

type DiurnalResponse = {
  station_id: string;
  pollutant: string;
  timezone: string;
  window: { from: string; to: string };
  overall: HourBucket[];
  by_weekday_weekend: {
    weekday: HourBucket[];
    weekend: HourBucket[];
  };
  by_season: {
    winter: HourBucket[];
    pre_monsoon: HourBucket[];
    monsoon: HourBucket[];
    post_monsoon: HourBucket[];
  };
};

type SeasonKey = keyof DiurnalResponse["by_season"];

const SEASON_LABELS: Record<SeasonKey, string> = {
  winter: "Winter",
  pre_monsoon: "Pre-Monsoon",
  monsoon: "Monsoon",
  post_monsoon: "Post-Monsoon",
};

const SEASON_COLORS: Record<SeasonKey, string> = {
  winter: "#3b82f6",
  pre_monsoon: "#f59e0b",
  monsoon: "#10b981",
  post_monsoon: "#ef4444",
};

async function fetchDiurnal(stationId: string): Promise<DiurnalResponse> {
  const res = await fetch(
    `${API_BASE}/api/v1/internal/stations/${stationId}/diurnal`
  );
  if (!res.ok) throw new Error("Failed to load diurnal data");
  return res.json();
}

function findPeakHour(overall: HourBucket[]): number | null {
  if (overall.length === 0) return null;
  return overall.reduce((best, cur) => (cur.mean > best.mean ? cur : best)).hour_local;
}

function findCleanestHour(overall: HourBucket[]): number | null {
  if (overall.length === 0) return null;
  return overall.reduce((best, cur) => (cur.mean < best.mean ? cur : best)).hour_local;
}

function formatHour(h: number): string {
  return `${String(h).padStart(2, "0")}:00`;
}

export function DiurnalPanel({ stationId }: { stationId: string }) {
  const [showWeekend, setShowWeekend] = useState(false);
  const [selectedSeason, setSelectedSeason] = useState<SeasonKey | "none">("none");

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

  if (data.overall.length === 0) {
    return (
      <Card>
        <CardContent className="py-12 text-center text-muted-foreground">
          No data available for diurnal analysis.
        </CardContent>
      </Card>
    );
  }

  const peakHour = findPeakHour(data.overall);
  const cleanestHour = findCleanestHour(data.overall);

  // Build chart data keyed by hour_local (0-23)
  const overallMap = new Map(data.overall.map((b) => [b.hour_local, b]));
  const weekdayMap = new Map(data.by_weekday_weekend.weekday.map((b) => [b.hour_local, b]));
  const weekendMap = new Map(data.by_weekday_weekend.weekend.map((b) => [b.hour_local, b]));
  const seasonData =
    selectedSeason !== "none" ? data.by_season[selectedSeason] : [];
  const seasonMap = new Map(seasonData.map((b) => [b.hour_local, b]));

  const chartData = Array.from({ length: 24 }, (_, hour) => {
    const o = overallMap.get(hour);
    const wd = weekdayMap.get(hour);
    const we = weekendMap.get(hour);
    const s = seasonMap.get(hour);
    return {
      hour,
      mean: o?.mean ?? null,
      p10: o?.p10 ?? null,
      p90: o?.p90 ?? null,
      weekday_mean: wd?.mean ?? null,
      weekend_mean: we?.mean ?? null,
      season_mean: s?.mean ?? null,
    };
  });

  // Weekday vs weekend analysis
  const weekdayArr = data.by_weekday_weekend.weekday;
  const weekendArr = data.by_weekday_weekend.weekend;
  const maxWeekday = weekdayArr.length > 0 ? Math.max(...weekdayArr.map((b) => b.mean)) : null;
  const maxWeekend = weekendArr.length > 0 ? Math.max(...weekendArr.map((b) => b.mean)) : null;
  const minWeekday = weekdayArr.length > 0 ? Math.min(...weekdayArr.map((b) => b.mean)) : null;
  const minWeekend = weekendArr.length > 0 ? Math.min(...weekendArr.map((b) => b.mean)) : null;

  const availableSeasons = (Object.keys(SEASON_LABELS) as SeasonKey[]).filter(
    (k) => data.by_season[k].length > 0
  );

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
              {peakHour !== null ? formatHour(peakHour) : "--"}
            </div>
            <p className="text-sm text-muted-foreground">
              Highest average PM2.5
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
              {cleanestHour !== null ? formatHour(cleanestHour) : "--"}
            </div>
            <p className="text-sm text-muted-foreground">
              Lowest average PM2.5
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Diurnal Pattern Chart */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between flex-wrap gap-4">
            <div>
              <CardTitle>Diurnal Pattern</CardTitle>
              <p className="text-sm text-muted-foreground">
                Average PM2.5 concentration by hour of day (local time)
              </p>
            </div>
            <div className="flex items-center gap-4 flex-wrap">
              <label className="flex items-center space-x-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={showWeekend}
                  onChange={(e) => setShowWeekend(e.target.checked)}
                  className="rounded"
                />
                <span className="text-sm">Weekday / Weekend</span>
              </label>
              {availableSeasons.length > 0 && (
                <select
                  value={selectedSeason}
                  onChange={(e) =>
                    setSelectedSeason(e.target.value as SeasonKey | "none")
                  }
                  className="text-sm border rounded px-2 py-1"
                >
                  <option value="none">No season overlay</option>
                  {availableSeasons.map((s) => (
                    <option key={s} value={s}>
                      {SEASON_LABELS[s]}
                    </option>
                  ))}
                </select>
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart
                data={chartData}
                margin={{ top: 20, right: 30, left: 20, bottom: 5 }}
              >
                <XAxis
                  dataKey="hour"
                  tick={{ fontSize: 12 }}
                  tickFormatter={(v) => formatHour(v)}
                  domain={[0, 23]}
                />
                <YAxis
                  tick={{ fontSize: 12 }}
                  label={{
                    value: "PM2.5 (ug/m3)",
                    angle: -90,
                    position: "insideLeft",
                  }}
                />
                <Tooltip
                  labelFormatter={(v) => formatHour(v as number)}
                  formatter={(value: any, name: string) => {
                    if (value == null) return ["--", name];
                    const label =
                      name === "mean"
                        ? "Overall Mean"
                        : name === "weekday_mean"
                        ? "Weekday"
                        : name === "weekend_mean"
                        ? "Weekend"
                        : name === "season_mean"
                        ? SEASON_LABELS[selectedSeason as SeasonKey] ?? "Season"
                        : name;
                    return [`${Number(value).toFixed(1)} ug/m3`, label];
                  }}
                />
                {/* p10-p90 shaded band */}
                <Area
                  type="monotone"
                  dataKey="p90"
                  stroke="none"
                  fill="hsl(var(--primary))"
                  fillOpacity={0.1}
                  connectNulls
                  isAnimationActive={false}
                />
                <Area
                  type="monotone"
                  dataKey="p10"
                  stroke="none"
                  fill="#ffffff"
                  fillOpacity={1}
                  connectNulls
                  isAnimationActive={false}
                />

                {/* Overall mean line */}
                {!showWeekend && (
                  <Line
                    type="monotone"
                    dataKey="mean"
                    stroke="hsl(var(--primary))"
                    strokeWidth={2}
                    dot={false}
                    connectNulls
                  />
                )}

                {/* Weekday / Weekend lines */}
                {showWeekend && (
                  <>
                    <Line
                      type="monotone"
                      dataKey="weekday_mean"
                      stroke="hsl(var(--primary))"
                      strokeWidth={2}
                      dot={false}
                      connectNulls
                      name="weekday_mean"
                    />
                    <Line
                      type="monotone"
                      dataKey="weekend_mean"
                      stroke="hsl(var(--destructive))"
                      strokeWidth={2}
                      strokeDasharray="5 5"
                      dot={false}
                      connectNulls
                      name="weekend_mean"
                    />
                  </>
                )}

                {/* Season overlay */}
                {selectedSeason !== "none" && (
                  <Line
                    type="monotone"
                    dataKey="season_mean"
                    stroke={SEASON_COLORS[selectedSeason as SeasonKey]}
                    strokeWidth={2}
                    strokeDasharray="3 3"
                    dot={false}
                    connectNulls
                    name="season_mean"
                  />
                )}
              </ComposedChart>
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
                  <span className="text-sm text-muted-foreground">
                    Weekday Peak
                  </span>
                  <span className="font-medium">
                    {maxWeekday !== null
                      ? `${maxWeekday.toFixed(1)} ug/m3`
                      : "No data"}
                  </span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-sm text-muted-foreground">
                    Weekend Peak
                  </span>
                  <span className="font-medium">
                    {maxWeekend !== null
                      ? `${maxWeekend.toFixed(1)} ug/m3`
                      : "No data"}
                  </span>
                </div>
                {maxWeekday !== null && maxWeekend !== null && (
                  <div className="flex justify-between items-center">
                    <span className="text-sm text-muted-foreground">
                      Difference
                    </span>
                    <span className="font-medium">
                      {Math.abs(maxWeekday - maxWeekend).toFixed(1)} ug/m3
                      {maxWeekday > maxWeekend
                        ? " higher weekdays"
                        : " higher weekends"}
                    </span>
                  </div>
                )}
              </div>
            </div>

            <div>
              <p className="text-sm font-medium mb-2">Daily Variation</p>
              <div className="space-y-2">
                {minWeekday !== null && maxWeekday !== null && (
                  <div className="flex justify-between items-center">
                    <span className="text-sm text-muted-foreground">
                      Weekday Range
                    </span>
                    <span className="font-medium">
                      {(maxWeekday - minWeekday).toFixed(1)} ug/m3
                    </span>
                  </div>
                )}
                {minWeekend !== null && maxWeekend !== null && (
                  <div className="flex justify-between items-center">
                    <span className="text-sm text-muted-foreground">
                      Weekend Range
                    </span>
                    <span className="font-medium">
                      {(maxWeekend - minWeekend).toFixed(1)} ug/m3
                    </span>
                  </div>
                )}
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Insights</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {peakHour !== null && (
              <div className="p-3 bg-blue-50 rounded-lg">
                <p className="text-sm text-blue-700">
                  <strong>Rush Hour Impact:</strong>{" "}
                  {peakHour >= 7 && peakHour <= 9
                    ? "Morning rush hour shows peak pollution levels."
                    : peakHour >= 17 && peakHour <= 19
                    ? "Evening rush hour shows peak pollution levels."
                    : "Peak pollution occurs outside typical rush hours."}
                </p>
              </div>
            )}

            {cleanestHour !== null && (
              <div className="p-3 bg-green-50 rounded-lg">
                <p className="text-sm text-green-700">
                  <strong>Clean Air Window:</strong>{" "}
                  Best air quality typically around {formatHour(cleanestHour)},
                  making it an optimal time for outdoor activities.
                </p>
              </div>
            )}

            {maxWeekday !== null &&
              maxWeekend !== null &&
              Math.abs(maxWeekday - maxWeekend) > 10 && (
                <div className="p-3 bg-orange-50 rounded-lg">
                  <p className="text-sm text-orange-700">
                    <strong>Weekend Effect:</strong>{" "}
                    Significant difference between weekday and weekend patterns
                    suggests traffic or industrial influence.
                  </p>
                </div>
              )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
