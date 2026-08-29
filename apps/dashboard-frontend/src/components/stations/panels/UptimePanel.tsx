"use client";

import { useQuery } from "@tanstack/react-query";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";

const API_BASE = "https://hawanama-152782825429.asia-south1.run.app";

type OfflinePeriod = {
  start: string;
  end: string;
  duration_hours: number;
  reason: string;
};

type FlatlinePeriod = {
  start: string;
  end: string;
  duration_hours: number;
  reason: string;
};

type UptimeData = {
  station_id: string;
  bucket: string;
  window: {
    from: string;
    to: string;
  };
  coverage: {
    expected_buckets: number;
    buckets_with_data: number;
    coverage_pct: number;
    missing_buckets: number;
  };
  offline_periods: OfflinePeriod[];
  flatline_periods: FlatlinePeriod[];
};

async function fetchUptime(stationId: string): Promise<UptimeData> {
  const res = await fetch(`${API_BASE}/api/v1/internal/stations/${stationId}/uptime`);
  if (!res.ok) throw new Error("Failed to load uptime data");
  return res.json();
}

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatDuration(hours: number): string {
  if (hours < 24) return `${hours.toFixed(1)}h`;
  const days = Math.floor(hours / 24);
  const remainingHours = hours % 24;
  return remainingHours > 0 ? `${days}d ${remainingHours.toFixed(0)}h` : `${days}d`;
}

export function UptimePanel({ stationId }: { stationId: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["station-uptime", stationId],
    queryFn: () => fetchUptime(stationId),
  });

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div className="grid gap-6 md:grid-cols-4">
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
        <Card className="h-48 animate-pulse bg-muted"></Card>
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

  const { coverage, offline_periods, flatline_periods, window, bucket } = data;
  const coverageColor =
    coverage.coverage_pct >= 90
      ? "text-green-600"
      : coverage.coverage_pct >= 50
        ? "text-yellow-600"
        : "text-red-600";

  return (
    <div className="space-y-6">
      {/* Window info */}
      <p className="text-sm text-muted-foreground">
        Bucket: <span className="font-medium">{bucket}</span> | Window:{" "}
        {formatDateTime(window.from)} &ndash; {formatDateTime(window.to)}
      </p>

      {/* Coverage Metrics */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Coverage
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className={`text-3xl font-bold ${coverageColor}`}>
              {coverage.coverage_pct.toFixed(1)}%
            </div>
            <p className="text-sm text-muted-foreground">
              Data availability
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Buckets with Data
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">
              {coverage.buckets_with_data.toLocaleString()}
            </div>
            <p className="text-sm text-muted-foreground">
              of {coverage.expected_buckets.toLocaleString()} expected
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Missing Buckets
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold text-red-600">
              {coverage.missing_buckets.toLocaleString()}
            </div>
            <p className="text-sm text-muted-foreground">
              Hours without data
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Offline Periods
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">
              {offline_periods.length}
            </div>
            <p className="text-sm text-muted-foreground">
              {flatline_periods.length} flatline period{flatline_periods.length !== 1 ? "s" : ""}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Offline Periods */}
      <Card>
        <CardHeader>
          <CardTitle>Offline Periods</CardTitle>
        </CardHeader>
        <CardContent>
          {offline_periods.length === 0 ? (
            <p className="text-sm text-muted-foreground">No offline periods recorded.</p>
          ) : (
            <div className="space-y-3">
              {offline_periods.map((period, i) => (
                <div
                  key={i}
                  className="flex flex-col sm:flex-row sm:items-center justify-between p-3 rounded-lg bg-red-50 gap-2"
                >
                  <div className="text-sm">
                    <span className="font-medium">{formatDateTime(period.start)}</span>
                    {" "}&ndash;{" "}
                    <span className="font-medium">{formatDateTime(period.end)}</span>
                  </div>
                  <div className="flex items-center gap-3 text-sm">
                    <span className="text-red-600 font-semibold">
                      {formatDuration(period.duration_hours)}
                    </span>
                    <span className="text-muted-foreground capitalize">{period.reason}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Flatline Periods */}
      {flatline_periods.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Flatline Periods</CardTitle>
            <p className="text-sm text-muted-foreground">
              Periods where sensor readings remained unchanged
            </p>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {flatline_periods.map((period, i) => (
                <div
                  key={i}
                  className="flex flex-col sm:flex-row sm:items-center justify-between p-3 rounded-lg bg-yellow-50 gap-2"
                >
                  <div className="text-sm">
                    <span className="font-medium">{formatDateTime(period.start)}</span>
                    {" "}&ndash;{" "}
                    <span className="font-medium">{formatDateTime(period.end)}</span>
                  </div>
                  <div className="flex items-center gap-3 text-sm">
                    <span className="text-yellow-600 font-semibold">
                      {formatDuration(period.duration_hours)}
                    </span>
                    <span className="text-muted-foreground capitalize">{period.reason}</span>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
