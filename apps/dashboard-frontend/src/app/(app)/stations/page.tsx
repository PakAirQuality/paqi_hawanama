"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { OverviewPanel } from "@/components/stations/panels/OverviewPanel";
import { UptimePanel } from "@/components/stations/panels/UptimePanel";
import { DiurnalPanel } from "@/components/stations/panels/DiurnalPanel";
import { EpisodesPanel } from "@/components/stations/panels/EpisodesPanel";

type StationListItem = {
  station_id: string;
  name: string;
  city?: string | null;
  provider?: string | null;
  active?: boolean;
  uptime_30d?: number;
  pm25_latest?: number;
  aqi_latest?: number;
};

type TabKey = "overview" | "uptime" | "diurnal" | "episodes";

const API_BASE = "https://hawanama-152782825429.asia-south1.run.app";

async function fetchStations(): Promise<StationListItem[]> {
  const res = await fetch(`${API_BASE}/api/v1/internal/stations`);
  if (!res.ok) throw new Error("Failed to load stations");
  const data = await res.json();
  return data.stations ?? data;
}

export default function StationsPage() {
  const { data: stations, isLoading, error } = useQuery({
    queryKey: ["stations"],
    queryFn: fetchStations,
  });

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabKey>("overview");

  if (isLoading) {
    return (
      <div className="p-6">
        <div className="animate-pulse space-y-4">
          <div className="h-8 bg-muted rounded w-48"></div>
          <div className="grid grid-cols-1 md:grid-cols-[320px,1fr] gap-4">
            <div className="h-96 bg-muted rounded"></div>
            <div className="h-96 bg-muted rounded"></div>
          </div>
        </div>
      </div>
    );
  }

  if (error || !stations) {
    return (
      <div className="p-6">
        <div className="text-destructive">Error loading stations: {error?.message}</div>
      </div>
    );
  }

  const currentStation = stations.find(s => s.station_id === selectedId) ?? null;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-3xl font-bold">Station Management</h2>
        <p className="text-muted-foreground">
          {stations.length} monitoring stations • Select a station to view details
        </p>
      </div>

      <main className="grid grid-cols-1 lg:grid-cols-[380px,1fr] gap-6 min-h-[70vh]">
        {/* LEFT: Station List */}
        <aside className="border border-border rounded-lg overflow-hidden bg-card">
          <div className="px-4 py-3 border-b border-border bg-muted/50">
            <div className="font-medium">Stations ({stations.length})</div>
          </div>
          <ul className="max-h-[70vh] overflow-y-auto">
            {stations.map(station => (
              <li
                key={station.station_id}
                className={`px-4 py-3 cursor-pointer border-b border-border/50 transition-colors ${
                  station.station_id === selectedId
                    ? "bg-primary/10 border-l-4 border-l-primary"
                    : "hover:bg-muted/50"
                }`}
                onClick={() => setSelectedId(station.station_id)}
              >
                <div className="space-y-1">
                  <div className="flex items-center justify-between">
                    <div className="font-medium text-sm">{station.name}</div>
                    <div className={`text-xs px-2 py-1 rounded-full ${
                      station.active 
                        ? "bg-green-100 text-green-700" 
                        : "bg-red-100 text-red-700"
                    }`}>
                      {station.active ? "Online" : "Offline"}
                    </div>
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {station.city ?? "—"} • {station.provider ?? "Unknown"}
                  </div>
                  {station.uptime_30d !== undefined && (
                    <div className="text-xs text-muted-foreground">
                      Uptime: {(station.uptime_30d * 100).toFixed(1)}%
                    </div>
                  )}
                  {station.pm25_latest !== undefined && (
                    <div className="text-xs">
                      Latest: <span className="font-medium">{station.pm25_latest.toFixed(1)} μg/m³</span>
                    </div>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </aside>

        {/* RIGHT: Station Details */}
        <section className="border border-border rounded-lg bg-card">
          {!currentStation || !selectedId ? (
            <div className="flex items-center justify-center h-full p-8">
              <div className="text-center space-y-3">
                <div className="text-6xl">📊</div>
                <div className="text-muted-foreground">
                  Select a station from the list to view detailed analytics and monitoring data.
                </div>
              </div>
            </div>
          ) : (
            <div className="p-6 space-y-6">
              {/* Header */}
              <div className="space-y-1">
                <h1 className="text-2xl font-bold">{currentStation.name}</h1>
                <p className="text-muted-foreground">
                  {currentStation.city ?? "Unknown city"} • {currentStation.provider ?? "Unknown provider"}
                </p>
              </div>

              {/* Tabs */}
              <div className="border-b border-border">
                <div className="flex space-x-8">
                  {(["overview", "uptime", "diurnal", "episodes"] as TabKey[]).map((tab) => (
                    <button
                      key={tab}
                      onClick={() => setActiveTab(tab)}
                      className={`py-2 px-1 border-b-2 font-medium text-sm transition-colors ${
                        activeTab === tab
                          ? "border-primary text-primary"
                          : "border-transparent text-muted-foreground hover:text-foreground"
                      }`}
                    >
                      {tab.charAt(0).toUpperCase() + tab.slice(1)}
                    </button>
                  ))}
                </div>
              </div>

              {/* Tab Content */}
              <div className="min-h-96">
                {activeTab === "overview" && <OverviewPanel stationId={selectedId} />}
                {activeTab === "uptime" && <UptimePanel stationId={selectedId} />}
                {activeTab === "diurnal" && <DiurnalPanel stationId={selectedId} />}
                {activeTab === "episodes" && <EpisodesPanel stationId={selectedId} />}
              </div>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}