"use client";

import { useQuery } from "@tanstack/react-query";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

const API_BASE = "https://hawanama-152782825429.asia-south1.run.app";

type TopDay = {
  date: string;
  mean_value: number;
  max_value: number;
  hours_above_threshold: number;
  severity_score: number;
};

type EpisodeHour = {
  datetime_local: string;
  value: number;
  threshold: number;
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
  hours: EpisodeHour[];
};

type EpisodesData = {
  station_id: string;
  pollutant: string;
  level: string;
  threshold: number;
  window: {
    from: string;
    to: string;
  };
  top_days: TopDay[];
  episodes: Episode[];
  total_episodes: number;
  total_episode_hours: number;
};

async function fetchEpisodes(stationId: string): Promise<EpisodesData> {
  const res = await fetch(`${API_BASE}/api/v1/internal/stations/${stationId}/episodes`);
  if (!res.ok) throw new Error("Failed to load episodes data");
  return res.json();
}

function formatSeverity(score: number): string {
  return `${(score * 100).toFixed(1)}%`;
}

function severityBadgeVariant(score: number): "default" | "secondary" | "destructive" | "outline" {
  if (score >= 0.1) return "destructive";
  if (score >= 0.05) return "default";
  return "secondary";
}

function formatLocalDatetime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function EpisodesPanel({ stationId }: { stationId: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["station-episodes", stationId],
    queryFn: () => fetchEpisodes(stationId),
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
        Error loading episodes data: {error?.message}
      </div>
    );
  }

  const hasEpisodes = data.episodes.length > 0;
  const hasTopDays = data.top_days.length > 0;

  return (
    <div className="space-y-6">
      {/* Summary Stats */}
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Total Episodes
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{data.total_episodes}</div>
            <p className="text-sm text-muted-foreground">Last 30 days</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Total Episode Hours
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{data.total_episode_hours}h</div>
            <p className="text-sm text-muted-foreground">Above threshold</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Threshold
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{data.threshold} &micro;g/m&sup3;</div>
            <p className="text-sm text-muted-foreground">PM2.5 ({data.level}ly)</p>
          </CardContent>
        </Card>
      </div>

      {/* No episodes state */}
      {!hasEpisodes && !hasTopDays && (
        <Card>
          <CardContent className="py-12">
            <div className="text-center">
              <p className="text-lg font-medium">No episodes detected</p>
              <p className="text-sm text-muted-foreground mt-2">
                No pollution episodes exceeded the {data.threshold} &micro;g/m&sup3; threshold
                during the 30-day window ({new Date(data.window.from).toLocaleDateString()} &ndash;{" "}
                {new Date(data.window.to).toLocaleDateString()}). This is a positive sign for air
                quality at this station.
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Top Days */}
      {hasTopDays && (
        <Card>
          <CardHeader>
            <CardTitle>Worst Days</CardTitle>
            <p className="text-sm text-muted-foreground">
              Days with the highest pollution levels
            </p>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {data.top_days.map((day) => (
                <div
                  key={day.date}
                  className="flex items-center justify-between border rounded-lg p-3 hover:bg-muted/50 transition-colors"
                >
                  <div className="space-y-1">
                    <p className="text-sm font-medium">
                      {new Date(day.date + "T00:00:00").toLocaleDateString(undefined, {
                        weekday: "short",
                        month: "short",
                        day: "numeric",
                        year: "numeric",
                      })}
                    </p>
                    <p className="text-sm text-muted-foreground">
                      Mean: {day.mean_value.toFixed(1)} &micro;g/m&sup3; &middot; Max:{" "}
                      {day.max_value.toFixed(1)} &micro;g/m&sup3; &middot;{" "}
                      {day.hours_above_threshold}h above threshold
                    </p>
                  </div>
                  <Badge variant={severityBadgeVariant(day.severity_score)}>
                    {formatSeverity(day.severity_score)}
                  </Badge>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Episodes List */}
      {hasEpisodes && (
        <Card>
          <CardHeader>
            <CardTitle>Episodes</CardTitle>
            <p className="text-sm text-muted-foreground">
              Continuous periods above the {data.threshold} &micro;g/m&sup3; threshold
            </p>
          </CardHeader>
          <CardContent>
            <div className="space-y-4 max-h-[32rem] overflow-y-auto">
              {data.episodes.map((episode, index) => (
                <div
                  key={index}
                  className="border rounded-lg p-4 hover:bg-muted/50 transition-colors"
                >
                  <div className="flex items-start justify-between">
                    <div className="space-y-2 flex-1">
                      <div className="flex items-center space-x-3">
                        <Badge variant={severityBadgeVariant(episode.severity_score)}>
                          Severity: {formatSeverity(episode.severity_score)}
                        </Badge>
                        <span className="text-sm text-muted-foreground">
                          {episode.duration_hours} hours
                        </span>
                      </div>

                      <div className="grid gap-2 md:grid-cols-2">
                        <div>
                          <p className="text-sm font-medium">Start</p>
                          <p className="text-sm text-muted-foreground">
                            {formatLocalDatetime(episode.start_datetime_local)}
                          </p>
                        </div>
                        <div>
                          <p className="text-sm font-medium">End</p>
                          <p className="text-sm text-muted-foreground">
                            {formatLocalDatetime(episode.end_datetime_local)}
                          </p>
                        </div>
                      </div>

                      <div className="grid gap-2 md:grid-cols-3">
                        <div>
                          <p className="text-sm font-medium">Peak Value</p>
                          <p className="text-sm text-muted-foreground">
                            {episode.peak_value.toFixed(1)} &micro;g/m&sup3;
                          </p>
                        </div>
                        <div>
                          <p className="text-sm font-medium">Mean Value</p>
                          <p className="text-sm text-muted-foreground">
                            {episode.mean_value.toFixed(1)} &micro;g/m&sup3;
                          </p>
                        </div>
                        <div>
                          <p className="text-sm font-medium">Peak Time</p>
                          <p className="text-sm text-muted-foreground">
                            {formatLocalDatetime(episode.peak_datetime_local)}
                          </p>
                        </div>
                      </div>
                    </div>
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
