"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { getAqiLabel } from "@/lib/api";

const API_BASE = "https://hawanama-152782825429.asia-south1.run.app";

type PollutionEpisode = {
  start_ts: string;
  end_ts: string;
  duration_hours: number;
  max_pm25: number;
  max_aqi: number;
  severity_label: string;
  cause_guess?: string;
};

type EpisodesData = {
  station_id: string;
  episodes: PollutionEpisode[];
};

async function fetchEpisodes(stationId: string): Promise<EpisodesData> {
  const res = await fetch(`${API_BASE}/api/v1/internal/stations/${stationId}/episodes`);
  if (!res.ok) throw new Error("Failed to load episodes data");
  return res.json();
}

export function EpisodesPanel({ stationId }: { stationId: string }) {
  const [timeFilter, setTimeFilter] = useState('30d'); // '7d', '30d', 'season'
  const [severityFilter, setSeverityFilter] = useState('all'); // 'all', 'very-unhealthy+'
  
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

  // Filter episodes based on selected criteria
  const now = new Date();
  const filterDate = timeFilter === '7d' ? 
    new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000) :
    timeFilter === '30d' ?
    new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000) :
    new Date(now.getTime() - 90 * 24 * 60 * 60 * 1000); // season = 90 days

  const filteredEpisodes = data.episodes
    .filter(episode => new Date(episode.start_ts) >= filterDate)
    .filter(episode => {
      if (severityFilter === 'very-unhealthy+') {
        return episode.max_aqi >= 201; // Very Unhealthy or worse
      }
      return true;
    })
    .sort((a, b) => new Date(b.start_ts).getTime() - new Date(a.start_ts).getTime());

  // Calculate statistics
  const totalEpisodes = filteredEpisodes.length;
  const totalHours = filteredEpisodes.reduce((acc, ep) => acc + ep.duration_hours, 0);
  const avgDuration = totalEpisodes > 0 ? totalHours / totalEpisodes : 0;
  const severeCases = filteredEpisodes.filter(ep => ep.max_aqi >= 201).length;

  const getSeverityColor = (severity: string) => {
    switch (severity.toLowerCase()) {
      case 'moderate': return 'bg-yellow-100 text-yellow-800';
      case 'unhealthy for sensitive groups': return 'bg-orange-100 text-orange-800';
      case 'unhealthy': return 'bg-red-100 text-red-800';
      case 'very unhealthy': return 'bg-purple-100 text-purple-800';
      case 'hazardous': return 'bg-red-200 text-red-900';
      default: return 'bg-gray-100 text-gray-800';
    }
  };

  return (
    <div className="space-y-6">
      {/* Filters */}
      <Card>
        <CardHeader className="pb-4">
          <div className="flex flex-wrap gap-4 items-center justify-between">
            <CardTitle>Pollution Episodes</CardTitle>
            <div className="flex flex-wrap gap-2">
              <select
                value={timeFilter}
                onChange={(e) => setTimeFilter(e.target.value)}
                className="px-3 py-1 border rounded-md text-sm bg-background"
              >
                <option value="7d">Last 7 days</option>
                <option value="30d">Last 30 days</option>
                <option value="season">Last 3 months</option>
              </select>
              <select
                value={severityFilter}
                onChange={(e) => setSeverityFilter(e.target.value)}
                className="px-3 py-1 border rounded-md text-sm bg-background"
              >
                <option value="all">All episodes</option>
                <option value="very-unhealthy+">Very Unhealthy+</option>
              </select>
            </div>
          </div>
        </CardHeader>
      </Card>

      {/* Statistics */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Total Episodes
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{totalEpisodes}</div>
            <p className="text-sm text-muted-foreground">
              {timeFilter === '7d' ? 'Last 7 days' : timeFilter === '30d' ? 'Last 30 days' : 'Last 3 months'}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Total Duration
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{totalHours.toFixed(1)}h</div>
            <p className="text-sm text-muted-foreground">
              Poor air quality
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Average Duration
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {avgDuration.toFixed(1)}h
            </div>
            <p className="text-sm text-muted-foreground">
              Per episode
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Severe Cases
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{severeCases}</div>
            <p className="text-sm text-muted-foreground">
              Very Unhealthy+
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Episodes List */}
      <Card>
        <CardHeader>
          <CardTitle>Recent Episodes</CardTitle>
          <p className="text-sm text-muted-foreground">
            High pollution events sorted by most recent
          </p>
        </CardHeader>
        <CardContent>
          {filteredEpisodes.length === 0 ? (
            <div className="text-center py-8">
              <div className="text-6xl mb-4">🌱</div>
              <p className="text-muted-foreground">
                No pollution episodes found for the selected period.
              </p>
            </div>
          ) : (
            <div className="space-y-4 max-h-96 overflow-y-auto">
              {filteredEpisodes.map((episode, index) => (
                <div key={index} className="border rounded-lg p-4 hover:bg-muted/50 transition-colors">
                  <div className="flex items-start justify-between">
                    <div className="space-y-2 flex-1">
                      <div className="flex items-center space-x-3">
                        <div className={`px-2 py-1 rounded text-xs font-medium ${getSeverityColor(episode.severity_label)}`}>
                          {episode.severity_label}
                        </div>
                        <span className="text-sm text-muted-foreground">
                          {episode.duration_hours.toFixed(1)} hours
                        </span>
                      </div>
                      
                      <div className="grid gap-2 md:grid-cols-2">
                        <div>
                          <p className="text-sm font-medium">Start Time</p>
                          <p className="text-sm text-muted-foreground">
                            {new Date(episode.start_ts).toLocaleString()}
                          </p>
                        </div>
                        <div>
                          <p className="text-sm font-medium">End Time</p>
                          <p className="text-sm text-muted-foreground">
                            {new Date(episode.end_ts).toLocaleString()}
                          </p>
                        </div>
                      </div>

                      <div className="grid gap-2 md:grid-cols-2">
                        <div>
                          <p className="text-sm font-medium">Peak PM₂.₅</p>
                          <p className="text-sm text-muted-foreground">
                            {episode.max_pm25.toFixed(1)} μg/m³
                          </p>
                        </div>
                        <div>
                          <p className="text-sm font-medium">Peak AQI</p>
                          <p className="text-sm text-muted-foreground">
                            {episode.max_aqi} ({getAqiLabel(episode.max_aqi)})
                          </p>
                        </div>
                      </div>

                      {episode.cause_guess && (
                        <div>
                          <p className="text-sm font-medium">Possible Cause</p>
                          <p className="text-sm text-muted-foreground">
                            {episode.cause_guess}
                          </p>
                        </div>
                      )}
                    </div>

                    <div className="ml-4">
                      <Badge variant="outline" className="text-xs">
                        AQI {episode.max_aqi}
                      </Badge>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Insights */}
      {filteredEpisodes.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Episode Insights</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {severeCases > 0 && (
              <div className="p-3 bg-red-50 rounded-lg">
                <p className="text-sm text-red-700">
                  <strong>Health Alert:</strong> {severeCases} severe pollution episodes 
                  recorded in the selected period. Consider air quality monitoring alerts.
                </p>
              </div>
            )}

            {avgDuration > 12 && (
              <div className="p-3 bg-orange-50 rounded-lg">
                <p className="text-sm text-orange-700">
                  <strong>Long Duration:</strong> Average episode duration of {avgDuration.toFixed(1)} hours 
                  indicates persistent pollution sources.
                </p>
              </div>
            )}

            {totalEpisodes === 0 && (
              <div className="p-3 bg-green-50 rounded-lg">
                <p className="text-sm text-green-700">
                  <strong>Good News:</strong> No significant pollution episodes recorded 
                  in the selected period.
                </p>
              </div>
            )}

            {totalEpisodes > 0 && avgDuration <= 12 && severeCases === 0 && (
              <div className="p-3 bg-blue-50 rounded-lg">
                <p className="text-sm text-blue-700">
                  <strong>Manageable Levels:</strong> Episodes are relatively short-lived 
                  and of moderate severity. Good overall air quality management.
                </p>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}