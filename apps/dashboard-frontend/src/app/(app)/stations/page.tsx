"use client";

import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { OverviewPanel } from "@/components/stations/panels/OverviewPanel";
import { UptimePanel } from "@/components/stations/panels/UptimePanel";
import { DiurnalPanel } from "@/components/stations/panels/DiurnalPanel";
import { EpisodesPanel } from "@/components/stations/panels/EpisodesPanel";

type StationListItem = {
  station_id: string;
  station_name: string;
  display_name: string;
};

type TabKey = "overview" | "uptime" | "diurnal" | "episodes";

const TABS: { key: TabKey; label: string }[] = [
  { key: "overview", label: "Overview" },
  { key: "uptime", label: "Uptime" },
  { key: "diurnal", label: "Diurnal" },
  { key: "episodes", label: "Episodes" },
];

const API_BASE = "https://hawanama-152782825429.asia-south1.run.app";

async function fetchStations(): Promise<StationListItem[]> {
  const res = await fetch(`${API_BASE}/api/v1/meta/stations`);
  if (!res.ok) throw new Error("Failed to load stations");
  return res.json();
}

/** Extract city from display_name like "Station Name, City, State, Country" */
function getCity(displayName: string): string {
  const parts = displayName.split(", ");
  return parts.length >= 3 ? parts[1] : "";
}

export default function StationsPage() {
  const { data: stations, isLoading, error } = useQuery({
    queryKey: ["stations"],
    queryFn: fetchStations,
  });

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabKey>("overview");
  const [search, setSearch] = useState("");

  // Group stations by city and filter by search
  const { filteredStations, groupedStations, matchCount } = useMemo(() => {
    if (!stations) return { filteredStations: [], groupedStations: new Map<string, StationListItem[]>(), matchCount: 0 };

    const q = search.toLowerCase().trim();
    const filtered = q
      ? stations.filter(s =>
          s.station_name.toLowerCase().includes(q) ||
          s.display_name.toLowerCase().includes(q)
        )
      : stations;

    const grouped = new Map<string, StationListItem[]>();
    for (const s of filtered) {
      const city = getCity(s.display_name) || "Other";
      if (!grouped.has(city)) grouped.set(city, []);
      grouped.get(city)!.push(s);
    }

    // Sort cities alphabetically, sort stations within each city
    const sorted = new Map(
      [...grouped.entries()]
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([city, list]) => [city, list.sort((a, b) => a.station_name.localeCompare(b.station_name))])
    );

    return { filteredStations: filtered, groupedStations: sorted, matchCount: filtered.length };
  }, [stations, search]);

  const currentStation = stations?.find(s => s.station_id === selectedId) ?? null;

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div className="animate-pulse space-y-4">
          <div className="h-8 bg-muted rounded w-48"></div>
          <div className="grid grid-cols-1 lg:grid-cols-[380px,1fr] gap-6">
            <div className="h-[600px] bg-muted rounded-lg"></div>
            <div className="h-[600px] bg-muted rounded-lg"></div>
          </div>
        </div>
      </div>
    );
  }

  if (error || !stations) {
    return (
      <Card className="border-destructive">
        <CardContent className="p-6">
          <p className="text-destructive font-medium">Failed to load stations</p>
          <p className="text-sm text-muted-foreground mt-1">{error?.message}</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-3xl font-bold tracking-tight">Stations</h2>
        <p className="text-muted-foreground">
          {stations.length} monitoring stations across South Asia
        </p>
      </div>

      <main className="grid grid-cols-1 lg:grid-cols-[380px,1fr] gap-6 min-h-[70vh]">
        {/* LEFT: Station List */}
        <div className="border border-border rounded-lg overflow-hidden bg-card flex flex-col">
          {/* Search */}
          <div className="p-3 border-b border-border bg-muted/30">
            <div className="relative">
              <svg
                className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
                />
              </svg>
              <input
                type="text"
                placeholder="Search stations or cities..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full pl-9 pr-3 py-2 text-sm rounded-md border border-border bg-background focus:outline-none focus:ring-2 focus:ring-primary/50 placeholder:text-muted-foreground"
              />
            </div>
            <div className="text-xs text-muted-foreground mt-2">
              {search ? `${matchCount} of ${stations.length} stations` : `${stations.length} stations`}
            </div>
          </div>

          {/* Station List grouped by city */}
          <div className="flex-1 overflow-y-auto max-h-[65vh]">
            {matchCount === 0 ? (
              <div className="p-6 text-center text-muted-foreground text-sm">
                No stations match &ldquo;{search}&rdquo;
              </div>
            ) : (
              [...groupedStations.entries()].map(([city, cityStations]) => (
                <div key={city}>
                  <div className="px-4 py-2 text-xs font-semibold text-muted-foreground uppercase tracking-wider bg-muted/40 border-b border-border/50 sticky top-0">
                    {city} ({cityStations.length})
                  </div>
                  {cityStations.map(station => (
                    <button
                      key={station.station_id}
                      className={`w-full text-left px-4 py-3 border-b border-border/30 transition-colors ${
                        station.station_id === selectedId
                          ? "bg-primary/10 border-l-[3px] border-l-primary"
                          : "hover:bg-muted/50 border-l-[3px] border-l-transparent"
                      }`}
                      onClick={() => {
                        setSelectedId(station.station_id);
                        setActiveTab("overview");
                      }}
                    >
                      <div className="font-medium text-sm leading-tight">
                        {station.station_name}
                      </div>
                      <div className="text-xs text-muted-foreground mt-0.5 truncate">
                        {station.station_id}
                      </div>
                    </button>
                  ))}
                </div>
              ))
            )}
          </div>
        </div>

        {/* RIGHT: Station Details */}
        <div className="border border-border rounded-lg bg-card min-h-[400px]">
          {!currentStation || !selectedId ? (
            <div className="flex items-center justify-center h-full p-8">
              <div className="text-center space-y-2 max-w-sm">
                <div className="text-5xl mb-4">📡</div>
                <p className="font-medium">Select a station</p>
                <p className="text-sm text-muted-foreground">
                  Choose a station from the list to view overview, uptime, diurnal patterns, and pollution episodes.
                </p>
              </div>
            </div>
          ) : (
            <div className="flex flex-col">
              {/* Station Header */}
              <div className="px-6 pt-6 pb-4 border-b border-border">
                <h1 className="text-xl font-bold">{currentStation.station_name}</h1>
                <p className="text-sm text-muted-foreground mt-0.5">
                  {currentStation.display_name}
                </p>
              </div>

              {/* Tabs */}
              <div className="border-b border-border px-6">
                <div className="flex gap-6">
                  {TABS.map(({ key, label }) => (
                    <button
                      key={key}
                      onClick={() => setActiveTab(key)}
                      className={`py-3 text-sm font-medium border-b-2 transition-colors ${
                        activeTab === key
                          ? "border-primary text-primary"
                          : "border-transparent text-muted-foreground hover:text-foreground"
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Tab Content */}
              <div className="p-6">
                {activeTab === "overview" && <OverviewPanel stationId={selectedId} />}
                {activeTab === "uptime" && <UptimePanel stationId={selectedId} />}
                {activeTab === "diurnal" && <DiurnalPanel stationId={selectedId} />}
                {activeTab === "episodes" && <EpisodesPanel stationId={selectedId} />}
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
