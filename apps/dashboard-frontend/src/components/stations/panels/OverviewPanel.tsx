"use client";

import { useQuery } from "@tanstack/react-query";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";

const API_BASE = "https://hawanama-152782825429.asia-south1.run.app";

type StationOverview = {
  station: {
    station_id: string;
    name: string;
    provider: string;
    provider_id: number | null;
    source_station_id: string | null;
    country: string | null;
    state: string | null;
    city: string | null;
    lat: number | null;
    lon: number | null;
    site_type: string | null;
    indoor_outdoor: string | null;
    height_m: number | null;
    distance_to_road_m: number | null;
    timezone: string | null;
    metadata: Record<string, unknown>;
  };
  data_availability: {
    first_obs: string | null;
    last_obs: string | null;
    total_days_with_any_data: number | null;
    coverage_last_365d_pct: number | null;
    hours_total: number | null;
    hours_with_data: number | null;
    hours_qc_ok: number | null;
  };
  sensors: unknown[];
  pollutant_summary: {
    pollutant: string | null;
    last_value: number | null;
    last_value_ts: string | null;
    rolling_means: {
      "24h": number | null;
      "7d": number | null;
      "30d": number | null;
    } | null;
    days_above_thresholds_last_30d: {
      WHO_24h: number | null;
      local_24h: number | null;
    } | null;
    days_above_thresholds_last_365d: {
      WHO_24h: number | null;
      local_24h: number | null;
    } | null;
  } | null;
};

async function fetchOverview(stationId: string): Promise<StationOverview> {
  const res = await fetch(`${API_BASE}/api/v1/internal/stations/${stationId}/overview`);
  if (!res.ok) throw new Error("Failed to load overview");
  return res.json();
}

function fmt(val: number | null | undefined, decimals = 1): string {
  if (val == null) return "N/A";
  return val.toFixed(decimals);
}

function fmtDate(val: string | null | undefined): string {
  if (!val) return "N/A";
  return new Date(val).toLocaleString();
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

  const station = data.station;
  const avail = data.data_availability;
  const poll = data.pollutant_summary;

  return (
    <div className="space-y-6">
      {/* Metric Cards */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Current PM2.5
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {fmt(poll?.last_value)} {poll?.last_value != null ? "ug/m3" : ""}
            </div>
            <p className="text-sm text-muted-foreground">
              {fmtDate(poll?.last_value_ts)}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              24h Mean
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {fmt(poll?.rolling_means?.["24h"])} {poll?.rolling_means?.["24h"] != null ? "ug/m3" : ""}
            </div>
            <p className="text-sm text-muted-foreground">Rolling average</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              7d Mean
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {fmt(poll?.rolling_means?.["7d"])} {poll?.rolling_means?.["7d"] != null ? "ug/m3" : ""}
            </div>
            <p className="text-sm text-muted-foreground">Rolling average</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              30d Mean
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {fmt(poll?.rolling_means?.["30d"])} {poll?.rolling_means?.["30d"] != null ? "ug/m3" : ""}
            </div>
            <p className="text-sm text-muted-foreground">Rolling average</p>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        {/* Station Info */}
        <Card>
          <CardHeader>
            <CardTitle>Station Details</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Name</span>
              <span className="font-medium">{station?.name ?? "N/A"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">City</span>
              <span className="font-medium">{station?.city ?? "N/A"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">State</span>
              <span className="font-medium">{station?.state ?? "N/A"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Provider</span>
              <span className="font-medium">{station?.provider ?? "N/A"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Coordinates</span>
              <span className="font-medium">
                {station?.lat != null && station?.lon != null
                  ? `${station.lat.toFixed(4)}, ${station.lon.toFixed(4)}`
                  : "N/A"}
              </span>
            </div>
          </CardContent>
        </Card>

        {/* Data Availability */}
        <Card>
          <CardHeader>
            <CardTitle>Data Availability</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Coverage (365d)</span>
              <span className="font-medium">
                {avail?.coverage_last_365d_pct != null
                  ? `${avail.coverage_last_365d_pct.toFixed(1)}%`
                  : "N/A"}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">First Observation</span>
              <span className="font-medium">{fmtDate(avail?.first_obs)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Last Observation</span>
              <span className="font-medium">{fmtDate(avail?.last_obs)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Days with Data</span>
              <span className="font-medium">
                {avail?.total_days_with_any_data ?? "N/A"}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Hours with Data</span>
              <span className="font-medium">
                {avail?.hours_with_data != null && avail?.hours_total != null
                  ? `${avail.hours_with_data} / ${avail.hours_total}`
                  : "N/A"}
              </span>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Threshold Exceedances */}
      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Days Above Thresholds (Last 30d)</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex justify-between">
              <span className="text-muted-foreground">WHO 24h Guideline</span>
              <span className="font-medium">
                {poll?.days_above_thresholds_last_30d?.WHO_24h ?? "N/A"}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Local 24h Standard</span>
              <span className="font-medium">
                {poll?.days_above_thresholds_last_30d?.local_24h ?? "N/A"}
              </span>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Days Above Thresholds (Last 365d)</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex justify-between">
              <span className="text-muted-foreground">WHO 24h Guideline</span>
              <span className="font-medium">
                {poll?.days_above_thresholds_last_365d?.WHO_24h ?? "N/A"}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Local 24h Standard</span>
              <span className="font-medium">
                {poll?.days_above_thresholds_last_365d?.local_24h ?? "N/A"}
              </span>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
