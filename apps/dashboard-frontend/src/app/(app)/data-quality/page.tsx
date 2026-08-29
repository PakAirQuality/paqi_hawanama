"use client";

import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, ComposedChart, Area,
} from "recharts";

const API_BASE = "https://hawanama-152782825429.asia-south1.run.app";

// ── Types matching the real API responses ──

type StationListItem = {
  station_id: string;
  station_name: string;
  display_name: string;
};

type UptimeResponse = {
  station_id: string;
  bucket: string;
  window: { from: string; to: string };
  coverage: {
    expected_buckets: number;
    buckets_with_data: number;
    coverage_pct: number;
    missing_buckets: number;
  };
  offline_periods: Array<{
    start: string;
    end: string;
    duration_hours: number;
    reason: string;
  }>;
  flatline_periods: Array<{
    start: string;
    end: string;
    duration_hours: number;
    value: number;
    pollutant: string;
  }>;
};

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
  by_weekday_weekend: { weekday: HourBucket[]; weekend: HourBucket[] } | null;
  by_season: Record<string, HourBucket[]> | null;
};

type TopDay = {
  date: string;
  mean_value: number;
  max_value: number;
  hours_above_threshold: number;
  severity_score: number;
};

type Episode = {
  start_datetime_local: string;
  end_datetime_local: string;
  duration_hours: number;
  peak_value: number;
  peak_datetime_local: string;
  mean_value: number;
  severity_score: number;
};

type EpisodesResponse = {
  station_id: string;
  pollutant: string;
  level: string;
  threshold: number;
  window: { from: string; to: string };
  top_days: TopDay[];
  episodes: Episode[];
  total_episodes: number;
  total_episode_hours: number;
};

// ── Fetchers ──

async function fetchStations(): Promise<StationListItem[]> {
  const res = await fetch(`${API_BASE}/api/v1/meta/stations`);
  if (!res.ok) throw new Error("Failed to load stations");
  return res.json();
}

async function fetchUptime(stationId: string): Promise<UptimeResponse> {
  const res = await fetch(`${API_BASE}/api/v1/internal/stations/${stationId}/uptime`);
  if (!res.ok) throw new Error("Failed to load uptime");
  return res.json();
}

async function fetchDiurnal(stationId: string): Promise<DiurnalResponse> {
  const res = await fetch(`${API_BASE}/api/v1/internal/stations/${stationId}/diurnal`);
  if (!res.ok) throw new Error("Failed to load diurnal");
  return res.json();
}

async function fetchEpisodes(stationId: string): Promise<EpisodesResponse> {
  const res = await fetch(`${API_BASE}/api/v1/internal/stations/${stationId}/episodes`);
  if (!res.ok) throw new Error("Failed to load episodes");
  return res.json();
}

function getCity(displayName: string): string {
  const parts = displayName.split(", ");
  return parts.length >= 3 ? parts[1] : "";
}

function fmtDt(iso: string): string {
  try {
    return new Date(iso).toLocaleString("en-PK", {
      month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    });
  } catch { return iso; }
}

function coverageColor(pct: number): string {
  if (pct >= 80) return "text-green-600";
  if (pct >= 50) return "text-yellow-600";
  return "text-red-600";
}

function coverageBg(pct: number): string {
  if (pct >= 80) return "bg-green-500";
  if (pct >= 50) return "bg-yellow-500";
  return "bg-red-500";
}

// ── Component ──

export default function DataQualityPage() {
  const [selectedId, setSelectedId] = useState<string>("");
  const [search, setSearch] = useState("");

  const { data: stations } = useQuery({
    queryKey: ["dq-stations"],
    queryFn: fetchStations,
  });

  const { data: uptime, isLoading: uptimeLoading } = useQuery({
    queryKey: ["dq-uptime", selectedId],
    queryFn: () => fetchUptime(selectedId),
    enabled: !!selectedId,
  });

  const { data: diurnal, isLoading: diurnalLoading } = useQuery({
    queryKey: ["dq-diurnal", selectedId],
    queryFn: () => fetchDiurnal(selectedId),
    enabled: !!selectedId,
  });

  const { data: episodes, isLoading: episodesLoading } = useQuery({
    queryKey: ["dq-episodes", selectedId],
    queryFn: () => fetchEpisodes(selectedId),
    enabled: !!selectedId,
  });

  const filteredStations = useMemo(() => {
    if (!stations) return [];
    const q = search.toLowerCase().trim();
    if (!q) return stations;
    return stations.filter(
      (s) =>
        s.station_name.toLowerCase().includes(q) ||
        s.display_name.toLowerCase().includes(q)
    );
  }, [stations, search]);

  const loading = uptimeLoading || diurnalLoading || episodesLoading;

  // Diurnal chart data
  const diurnalChart = useMemo(() => {
    if (!diurnal?.overall?.length) return [];
    return diurnal.overall.map((b) => ({
      hour: `${String(b.hour_local).padStart(2, "0")}:00`,
      mean: Number(b.mean?.toFixed(1)),
      p10: Number(b.p10?.toFixed(1)),
      p90: Number(b.p90?.toFixed(1)),
      p50: Number(b.p50?.toFixed(1)),
    }));
  }, [diurnal]);

  const peakHour = useMemo(() => {
    if (!diurnal?.overall?.length) return null;
    return diurnal.overall.reduce((a, b) => (b.mean > a.mean ? b : a));
  }, [diurnal]);

  const cleanestHour = useMemo(() => {
    if (!diurnal?.overall?.length) return null;
    return diurnal.overall.reduce((a, b) => (b.mean < a.mean ? b : a));
  }, [diurnal]);

  const selectedStation = stations?.find((s) => s.station_id === selectedId);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-3xl font-bold tracking-tight">Data Quality</h2>
        <p className="text-muted-foreground">
          Pollution episodes, diurnal cycles, and station uptime
        </p>
      </div>

      {/* Station Selector */}
      <Card>
        <CardContent className="p-4">
          <div className="flex flex-col sm:flex-row gap-3">
            <div className="relative flex-1">
              <svg
                className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground"
                fill="none" stroke="currentColor" viewBox="0 0 24 24"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
              <input
                type="text"
                placeholder="Search stations..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full pl-9 pr-3 py-2 text-sm rounded-md border border-border bg-background focus:outline-none focus:ring-2 focus:ring-primary/50"
              />
            </div>
            <select
              className="w-full sm:w-auto sm:min-w-[320px] rounded-md border border-border px-3 py-2 text-sm bg-background focus:outline-none focus:ring-2 focus:ring-primary/50"
              value={selectedId}
              onChange={(e) => setSelectedId(e.target.value)}
            >
              <option value="">Choose a station...</option>
              {filteredStations.map((s) => (
                <option key={s.station_id} value={s.station_id}>
                  {s.station_name} — {getCity(s.display_name)}
                </option>
              ))}
            </select>
          </div>
          {search && (
            <p className="text-xs text-muted-foreground mt-2">
              {filteredStations.length} of {stations?.length ?? 0} stations
            </p>
          )}
        </CardContent>
      </Card>

      {!selectedId && (
        <Card>
          <CardContent className="p-12 text-center">
            <div className="text-5xl mb-4">🔍</div>
            <p className="font-medium">Select a station above</p>
            <p className="text-sm text-muted-foreground mt-1">
              View uptime coverage, diurnal pollution patterns, and episode history
            </p>
          </CardContent>
        </Card>
      )}

      {selectedId && loading && (
        <div className="grid gap-6 md:grid-cols-3">
          {[...Array(3)].map((_, i) => (
            <Card key={i} className="animate-pulse">
              <CardContent className="p-6">
                <div className="h-4 bg-muted rounded w-24 mb-3" />
                <div className="h-8 bg-muted rounded w-16" />
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {selectedId && !loading && (
        <>
          {/* Station Name Banner */}
          {selectedStation && (
            <div className="flex items-center gap-3 px-1">
              <h3 className="text-lg font-semibold">{selectedStation.station_name}</h3>
              <span className="text-sm text-muted-foreground">{selectedStation.display_name}</span>
            </div>
          )}

          {/* ── Row 1: Uptime Summary Cards ── */}
          <div className="grid gap-4 md:grid-cols-4">
            <Card>
              <CardContent className="p-5">
                <p className="text-sm font-medium text-muted-foreground mb-1">Coverage</p>
                <p className={`text-3xl font-bold ${coverageColor(uptime?.coverage.coverage_pct ?? 0)}`}>
                  {uptime?.coverage.coverage_pct?.toFixed(1) ?? "—"}%
                </p>
                <p className="text-xs text-muted-foreground mt-1">
                  {uptime?.coverage.buckets_with_data?.toLocaleString() ?? "—"} / {uptime?.coverage.expected_buckets?.toLocaleString() ?? "—"} buckets
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-5">
                <p className="text-sm font-medium text-muted-foreground mb-1">Missing Buckets</p>
                <p className="text-3xl font-bold">
                  {uptime?.coverage.missing_buckets?.toLocaleString() ?? "—"}
                </p>
                <p className="text-xs text-muted-foreground mt-1">
                  Bucket size: {uptime?.bucket ?? "—"}
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-5">
                <p className="text-sm font-medium text-muted-foreground mb-1">Offline Periods</p>
                <p className="text-3xl font-bold text-red-600">
                  {uptime?.offline_periods?.length ?? 0}
                </p>
                <p className="text-xs text-muted-foreground mt-1">
                  {uptime?.offline_periods?.length
                    ? `${uptime.offline_periods.reduce((a, p) => a + p.duration_hours, 0).toFixed(0)}h total downtime`
                    : "No outages detected"}
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-5">
                <p className="text-sm font-medium text-muted-foreground mb-1">Flatlines</p>
                <p className="text-3xl font-bold text-yellow-600">
                  {uptime?.flatline_periods?.length ?? 0}
                </p>
                <p className="text-xs text-muted-foreground mt-1">
                  Stuck-sensor periods
                </p>
              </CardContent>
            </Card>
          </div>

          {/* ── Row 2: Diurnal Pattern + Episode Stats ── */}
          <div className="grid gap-6 lg:grid-cols-3">
            {/* Diurnal chart — 2 cols */}
            <Card className="lg:col-span-2">
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Diurnal Pollution Pattern</CardTitle>
                <p className="text-xs text-muted-foreground">
                  Hourly PM₂.₅ distribution (mean with p10–p90 band)
                  {diurnal?.timezone ? ` • ${diurnal.timezone}` : ""}
                </p>
              </CardHeader>
              <CardContent>
                {diurnalChart.length === 0 ? (
                  <div className="py-12 text-center text-muted-foreground text-sm">
                    No diurnal data available for this station
                  </div>
                ) : (
                  <>
                    <div className="h-72">
                      <ResponsiveContainer width="100%" height="100%">
                        <ComposedChart data={diurnalChart} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                          <XAxis dataKey="hour" tick={{ fontSize: 11 }} interval={2} />
                          <YAxis tick={{ fontSize: 11 }} label={{ value: "μg/m³", angle: -90, position: "insideLeft", fontSize: 11 }} />
                          <Tooltip
                            formatter={(v: number, name: string) => [
                              `${v} μg/m³`,
                              name === "mean" ? "Mean" : name === "p10" ? "P10" : name === "p90" ? "P90" : name === "p50" ? "Median" : name,
                            ]}
                          />
                          <Area dataKey="p90" stroke="none" fill="hsl(var(--primary))" fillOpacity={0.1} />
                          <Area dataKey="p10" stroke="none" fill="#fff" fillOpacity={1} />
                          <Line dataKey="p50" stroke="hsl(var(--primary))" strokeWidth={1} strokeDasharray="4 2" dot={false} name="Median" />
                          <Line dataKey="mean" stroke="hsl(var(--primary))" strokeWidth={2} dot={false} name="Mean" />
                        </ComposedChart>
                      </ResponsiveContainer>
                    </div>

                    {/* Peak / cleanest */}
                    <div className="flex gap-4 mt-4">
                      {peakHour && (
                        <div className="flex-1 rounded-lg bg-red-50 p-3">
                          <p className="text-xs font-medium text-red-700">Peak Hour</p>
                          <p className="text-lg font-bold text-red-700">
                            {String(peakHour.hour_local).padStart(2, "0")}:00
                          </p>
                          <p className="text-xs text-red-600">{peakHour.mean.toFixed(1)} μg/m³ avg</p>
                        </div>
                      )}
                      {cleanestHour && (
                        <div className="flex-1 rounded-lg bg-green-50 p-3">
                          <p className="text-xs font-medium text-green-700">Cleanest Hour</p>
                          <p className="text-lg font-bold text-green-700">
                            {String(cleanestHour.hour_local).padStart(2, "0")}:00
                          </p>
                          <p className="text-xs text-green-600">{cleanestHour.mean.toFixed(1)} μg/m³ avg</p>
                        </div>
                      )}
                    </div>
                  </>
                )}
              </CardContent>
            </Card>

            {/* Episode stats — 1 col */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Pollution Episodes</CardTitle>
                <p className="text-xs text-muted-foreground">
                  Last 30 days • Threshold: {episodes?.threshold ?? 15} μg/m³
                </p>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-2 gap-3">
                  <div className="rounded-lg bg-muted/50 p-3 text-center">
                    <p className="text-2xl font-bold">{episodes?.total_episodes ?? 0}</p>
                    <p className="text-xs text-muted-foreground">Episodes</p>
                  </div>
                  <div className="rounded-lg bg-muted/50 p-3 text-center">
                    <p className="text-2xl font-bold">{episodes?.total_episode_hours ?? 0}h</p>
                    <p className="text-xs text-muted-foreground">Total Duration</p>
                  </div>
                </div>

                {/* Top worst days */}
                {episodes?.top_days && episodes.top_days.length > 0 ? (
                  <div>
                    <p className="text-sm font-medium mb-2">Worst Days</p>
                    <div className="space-y-2 max-h-48 overflow-y-auto">
                      {episodes.top_days.map((day, i) => (
                        <div key={day.date} className="flex items-center justify-between rounded-lg border border-border/50 px-3 py-2">
                          <div>
                            <p className="text-sm font-medium">{day.date}</p>
                            <p className="text-xs text-muted-foreground">
                              {day.hours_above_threshold}h above threshold
                            </p>
                          </div>
                          <div className="text-right">
                            <p className="text-sm font-bold">{day.mean_value.toFixed(0)} μg/m³</p>
                            <Badge variant={day.severity_score >= 0.1 ? "destructive" : "secondary"} className="text-[10px]">
                              {(day.severity_score * 100).toFixed(0)}% severity
                            </Badge>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="py-4 text-center text-sm text-muted-foreground">
                    No episodes detected — clean period
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          {/* ── Row 3: Offline Periods + Episodes Detail ── */}
          <div className="grid gap-6 lg:grid-cols-2">
            {/* Offline periods */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Offline Periods</CardTitle>
                <p className="text-xs text-muted-foreground">
                  Gaps in data collection
                </p>
              </CardHeader>
              <CardContent>
                {!uptime?.offline_periods?.length ? (
                  <div className="py-6 text-center text-sm text-muted-foreground">
                    No offline periods — continuous data collection
                  </div>
                ) : (
                  <div className="space-y-2 max-h-64 overflow-y-auto">
                    {uptime.offline_periods.slice(0, 15).map((p, i) => {
                      const days = Math.floor(p.duration_hours / 24);
                      const hours = Math.round(p.duration_hours % 24);
                      const durationStr = days > 0 ? `${days}d ${hours}h` : `${hours}h`;
                      return (
                        <div key={i} className="flex items-center justify-between rounded-lg border border-red-100 bg-red-50/50 px-3 py-2">
                          <div className="text-sm">
                            <span className="font-medium">{fmtDt(p.start)}</span>
                            <span className="text-muted-foreground"> → </span>
                            <span className="font-medium">{fmtDt(p.end)}</span>
                          </div>
                          <Badge variant="outline" className="text-xs text-red-600 border-red-200">
                            {durationStr}
                          </Badge>
                        </div>
                      );
                    })}
                    {uptime.offline_periods.length > 15 && (
                      <p className="text-xs text-muted-foreground text-center pt-1">
                        + {uptime.offline_periods.length - 15} more periods
                      </p>
                    )}
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Episodes list */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Episode Details</CardTitle>
                <p className="text-xs text-muted-foreground">
                  Continuous periods above {episodes?.threshold ?? 15} μg/m³
                </p>
              </CardHeader>
              <CardContent>
                {!episodes?.episodes?.length ? (
                  <div className="py-6 text-center text-sm text-muted-foreground">
                    No hourly-level episodes detected
                  </div>
                ) : (
                  <div className="space-y-3 max-h-64 overflow-y-auto">
                    {episodes.episodes.map((ep, i) => (
                      <div key={i} className="rounded-lg border border-border p-3 space-y-2">
                        <div className="flex items-center justify-between">
                          <Badge variant={ep.severity_score >= 0.1 ? "destructive" : "secondary"} className="text-xs">
                            {(ep.severity_score * 100).toFixed(0)}% severity
                          </Badge>
                          <span className="text-xs text-muted-foreground">{ep.duration_hours}h duration</span>
                        </div>
                        <div className="grid grid-cols-2 gap-x-4 text-sm">
                          <div>
                            <p className="text-xs text-muted-foreground">Start</p>
                            <p className="font-medium">{fmtDt(ep.start_datetime_local)}</p>
                          </div>
                          <div>
                            <p className="text-xs text-muted-foreground">End</p>
                            <p className="font-medium">{fmtDt(ep.end_datetime_local)}</p>
                          </div>
                        </div>
                        <div className="grid grid-cols-2 gap-x-4 text-sm">
                          <div>
                            <p className="text-xs text-muted-foreground">Peak</p>
                            <p className="font-bold">{ep.peak_value.toFixed(0)} μg/m³</p>
                          </div>
                          <div>
                            <p className="text-xs text-muted-foreground">Mean</p>
                            <p className="font-medium">{ep.mean_value.toFixed(0)} μg/m³</p>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          {/* ── Row 4: Flatline periods (if any) ── */}
          {uptime?.flatline_periods && uptime.flatline_periods.length > 0 && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Flatline (Stuck Sensor) Periods</CardTitle>
                <p className="text-xs text-muted-foreground">
                  Periods where the sensor reported a constant value
                </p>
              </CardHeader>
              <CardContent>
                <div className="space-y-2 max-h-48 overflow-y-auto">
                  {uptime.flatline_periods.map((p, i) => {
                    const days = Math.floor(p.duration_hours / 24);
                    const hours = Math.round(p.duration_hours % 24);
                    const durationStr = days > 0 ? `${days}d ${hours}h` : `${hours}h`;
                    return (
                      <div key={i} className="flex items-center justify-between rounded-lg border border-yellow-100 bg-yellow-50/50 px-3 py-2">
                        <div className="text-sm">
                          <span className="font-medium">{fmtDt(p.start)}</span>
                          <span className="text-muted-foreground"> → </span>
                          <span className="font-medium">{fmtDt(p.end)}</span>
                          <span className="text-xs text-yellow-700 ml-2">stuck at {p.value.toFixed(1)} μg/m³</span>
                        </div>
                        <Badge variant="outline" className="text-xs text-yellow-600 border-yellow-200">
                          {durationStr}
                        </Badge>
                      </div>
                    );
                  })}
                </div>
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
