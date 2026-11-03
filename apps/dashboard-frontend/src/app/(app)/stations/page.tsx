"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, Search } from "lucide-react";
import { Skeleton } from "@/components/shared/Skeleton";
import { AqiCard } from "@/components/shared/AqiCard";
import { OverviewPanel } from "@/components/stations/panels/OverviewPanel";
import { UptimePanel } from "@/components/stations/panels/UptimePanel";
import { DiurnalPanel } from "@/components/stations/panels/DiurnalPanel";
import { EpisodesPanel } from "@/components/stations/panels/EpisodesPanel";
import { fetchCurrentStations } from "@/components/analyst-desk/api";
import { isPakistanStation } from "@/lib/api";
import { classifyPm25 } from "@/lib/aqi";
import { relativeAge } from "@/lib/time";
import {
  filterStationRows,
  groupStationRows,
  isReporting,
  stationCities,
  stationRows,
  worstStation,
  type StationListItem,
  type StationRow,
  type StationSort,
} from "@/lib/stationList";

type TabKey = "overview" | "uptime" | "diurnal" | "episodes";

const TABS: { key: TabKey; label: string }[] = [
  { key: "overview", label: "Overview" },
  { key: "uptime", label: "Uptime" },
  { key: "diurnal", label: "Diurnal" },
  { key: "episodes", label: "Episodes" },
];

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

// Viewport less the header, page padding and page title: list and details scroll on their own
const PANES_HEIGHT = "lg:h-[calc(100dvh-170px)]";

async function fetchStations(): Promise<StationListItem[]> {
  const res = await fetch(`${API_BASE}/api/v1/meta/stations`);
  if (!res.ok) throw new Error("Failed to load stations");
  return ((await res.json()) as StationListItem[]).filter(isPakistanStation);
}

function setStationInAddress(id: string | null) {
  const url = new URL(window.location.href);
  if (id) url.searchParams.set("station", id);
  else url.searchParams.delete("station");
  window.history.replaceState(null, "", url);
}

export default function StationsPage() {
  const { data: stations, isLoading, error, refetch } = useQuery({
    queryKey: ["stations"],
    queryFn: fetchStations,
  });
  const { data: liveData, isError: liveFailed } = useQuery({
    queryKey: ["current-stations"],
    queryFn: fetchCurrentStations,
    staleTime: 5 * 60 * 1000,
    refetchInterval: 5 * 60 * 1000,
    retry: 2,
  });

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabKey>("overview");
  const [search, setSearch] = useState("");
  const [city, setCity] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [sort, setSort] = useState<StationSort>("worst");

  const rows = useMemo(() => stationRows(stations ?? [], liveData?.stations ?? []), [stations, liveData]);
  const reportingCount = useMemo(() => rows.filter(isReporting).length, [rows]);
  const liveReady = !!liveData || liveFailed;
  // With no readings to go on, "reporting" would hide every station
  const reportingOnly = !showAll && !!liveData;
  const matches = useMemo(() => filterStationRows(rows, search, reportingOnly, city), [rows, search, reportingOnly, city]);
  const cities = useMemo(() => stationCities(rows, reportingOnly), [rows, reportingOnly]);
  const groups = useMemo(() => groupStationRows(matches, sort), [matches, sort]);

  const current = rows.find(r => r.id === selectedId) ?? null;

  // First view: a shared link's station, or on a wide screen the worst one, so the details are never empty.
  // Phones open on the list.
  const firstViewDone = useRef(false);
  useEffect(() => {
    if (firstViewDone.current || !rows.length || !liveReady) return;
    firstViewDone.current = true;
    const linked = new URLSearchParams(window.location.search).get("station");
    if (linked && rows.some(r => r.id === linked)) setSelectedId(linked);
    else if (window.matchMedia("(min-width: 1024px)").matches) setSelectedId(worstStation(rows)?.id ?? rows[0].id);
  }, [rows, liveReady]);

  const detailsRef = useRef<HTMLElement>(null);
  const select = (id: string | null) => {
    setSelectedId(id);
    setActiveTab("overview");
    setStationInAddress(id);
    detailsRef.current?.scrollTo(0, 0);
    document.querySelector("main")?.scrollTo(0, 0);
  };

  if (isLoading) {
    return (
      <div className="space-y-4" aria-busy="true" aria-label="Loading stations">
        <Skeleton className="h-8 w-48 rounded-lg" />
        <div className={`grid grid-cols-1 gap-4 lg:grid-cols-[360px_1fr] ${PANES_HEIGHT}`}>
          <Skeleton className="h-[60vh] rounded-2xl lg:h-full" />
          <Skeleton className="hidden rounded-2xl lg:block" />
        </div>
      </div>
    );
  }

  if (error || !stations) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-white p-6">
        <p className="font-medium text-slate-900">Couldn&rsquo;t load the stations</p>
        <p className="mt-1 text-sm text-slate-600">{error?.message}</p>
        <button
          onClick={() => refetch()}
          className="mt-3 rounded-full bg-slate-900 px-3.5 py-1.5 text-[13px] font-medium text-white hover:bg-slate-800"
        >
          Try again
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <header className={current ? "max-lg:hidden" : undefined}>
        <h1 className="text-[22px] font-semibold leading-tight tracking-tight text-slate-900">Stations</h1>
        <p className="mt-0.5 text-[13px] text-slate-600">
          {liveData ? `${reportingCount} reporting now, of ${stations.length} registered in Pakistan` : `${stations.length} registered in Pakistan`}
        </p>
      </header>

      <div className={`grid grid-cols-1 gap-4 lg:grid-cols-[360px_1fr] ${PANES_HEIGHT}`}>
        {/* List */}
        <section
          aria-label="Stations"
          className={`min-h-0 flex-col overflow-hidden rounded-2xl border border-slate-200/70 bg-white ${current ? "hidden lg:flex" : "flex"}`}
        >
          <div className="space-y-2.5 border-b border-slate-100 p-3">
            <div className="relative">
              <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" aria-hidden />
              <input
                type="search"
                aria-label="Search stations or cities"
                placeholder="Search stations or cities"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full rounded-full bg-slate-900/[0.05] py-2 pl-9 pr-3 text-base text-slate-900 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-900/20 md:text-[13px]"
              />
            </div>
            <div className="flex flex-wrap items-center justify-between gap-2">
              {liveData ? (
                <div className="flex items-center gap-0.5 rounded-full bg-slate-900/[0.06] p-0.5" role="group" aria-label="Which stations">
                  <Segment active={!showAll} onClick={() => setShowAll(false)}>Reporting</Segment>
                  <Segment active={showAll} onClick={() => setShowAll(true)}>All</Segment>
                </div>
              ) : (
                <span className="text-xs text-amber-700">{liveFailed ? "Latest readings unavailable" : "Loading readings"}</span>
              )}
              <select
                aria-label="City"
                value={city}
                onChange={(e) => setCity(e.target.value)}
                className={`min-w-0 flex-1 cursor-pointer truncate rounded-full py-1 pl-2.5 text-xs font-medium max-md:order-last max-md:basis-full max-md:py-2 focus:outline-none focus:ring-2 focus:ring-slate-900/20 ${city ? "bg-slate-900 text-white" : "bg-slate-900/[0.06] text-slate-700"}`}
              >
                <option value="">All cities</option>
                {/* The chosen city stays listed when the other filter leaves it empty */}
                {city && !cities.some(c => c.city === city) && <option value={city}>{city} (0)</option>}
                {cities.map(c => <option key={c.city} value={c.city}>{c.city} ({c.count})</option>)}
              </select>
              <select
                aria-label="Sort stations"
                value={sort}
                onChange={(e) => setSort(e.target.value as StationSort)}
                className="shrink-0 cursor-pointer rounded-full bg-transparent py-1 text-xs font-medium max-md:py-2 text-slate-700 focus:outline-none focus:ring-2 focus:ring-slate-900/20"
              >
                <option value="worst">Worst first</option>
                <option value="city">By city</option>
              </select>
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto scrollbar-hide p-1.5">
            {groups.length === 0 ? (
              <div className="p-6 text-center text-[13px] text-slate-600">
                <p>
                  No {reportingOnly ? "reporting " : ""}stations
                  {search && <> match &ldquo;{search}&rdquo;</>}
                  {city && <> in {city}</>}
                </p>
                {reportingOnly && (
                  <button onClick={() => setShowAll(true)} className="mt-2 font-medium text-slate-900 underline underline-offset-2">
                    Search all stations
                  </button>
                )}
                {!reportingOnly && city && (
                  <button onClick={() => setCity("")} className="mt-2 font-medium text-slate-900 underline underline-offset-2">
                    Search all cities
                  </button>
                )}
              </div>
            ) : (
              groups.map(group => (
                <div key={group.city ?? "all"}>
                  {group.city && (
                    <h2 className="sticky top-0 z-10 bg-white px-2.5 pb-1 pt-2.5 text-xs font-semibold text-slate-600">
                      {group.city} <span className="font-normal">{group.rows.length}</span>
                    </h2>
                  )}
                  {group.rows.map(row => (
                    <StationButton
                      key={row.id}
                      row={row}
                      showCity={!group.city}
                      selected={row.id === selectedId}
                      onClick={() => select(row.id)}
                    />
                  ))}
                </div>
              ))
            )}
          </div>

          <p className="truncate border-t border-slate-100 px-3 py-2 text-right text-xs text-slate-600">
            {matches.length} of {rows.length}, latest hourly PM2.5 in µg/m³
          </p>
        </section>

        {/* Details */}
        <section
          ref={detailsRef}
          aria-label="Station details"
          className={`min-h-0 overflow-y-auto rounded-2xl border border-slate-200/70 bg-white ${current ? "block" : "hidden lg:block"}`}
        >
          {current && (
            <StationDetails
              key={current.id}
              station={current}
              activeTab={activeTab}
              onTab={setActiveTab}
              onBack={() => select(null)}
            />
          )}
        </section>
      </div>
    </div>
  );
}

function Segment({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      className={`rounded-full px-3 py-1 text-xs font-medium transition-colors max-md:py-2 ${active ? "bg-slate-900 text-white" : "text-slate-700 hover:bg-slate-900/[0.06]"}`}
    >
      {children}
    </button>
  );
}

function StationButton({ row, showCity, selected, onClick }: { row: StationRow; showCity: boolean; selected: boolean; onClick: () => void }) {
  const band = row.pm25 != null ? classifyPm25(row.pm25) : null;
  const status = row.pm25 == null ? "Not reporting" : row.lastReading ? relativeAge(row.lastReading) : "";
  return (
    <button
      onClick={onClick}
      aria-current={selected ? "true" : undefined}
      className={`flex w-full items-center gap-3 rounded-xl px-2.5 py-2 text-left transition-colors ${selected ? "bg-slate-100" : "hover:bg-slate-50"}`}
    >
      <span
        className={`flex w-12 shrink-0 flex-col items-center rounded-lg py-1 leading-none ${band ? "" : "bg-slate-100 text-slate-500"}`}
        style={band ? { background: band.color, color: band.textColor } : undefined}
      >
        <span className="text-[13px] font-semibold tabular-nums">{row.pm25 != null ? Math.round(row.pm25) : "—"}</span>
        <span className="mt-0.5 text-[9px] font-medium">PM2.5</span>
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13px] font-medium text-slate-900">{row.name}</span>
        <span className="block truncate text-xs text-slate-600">
          {[showCity ? row.city : null, status].filter(Boolean).join(", ")}
        </span>
      </span>
    </button>
  );
}

function StationDetails({ station, activeTab, onTab, onBack }: { station: StationRow; activeTab: TabKey; onTab: (tab: TabKey) => void; onBack: () => void }) {
  return (
    <>
      <div className="p-4 md:p-5">
        <button onClick={onBack} className="-ml-1 mb-1 flex items-center gap-0.5 py-2 text-[13px] font-medium text-slate-700 lg:hidden">
          <ChevronLeft size={16} aria-hidden />
          All stations
        </button>
        <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
          <div className="min-w-0">
            <h2 className="text-[20px] font-semibold leading-snug tracking-tight text-slate-900">{station.name}</h2>
            {station.place && <p className="mt-0.5 text-[13px] text-slate-600">{station.place}</p>}
            <p className={`mt-0.5 text-xs font-medium ${station.pm25 != null ? "text-emerald-700" : "text-slate-500"}`}>
              {station.pm25 != null ? `Reporting${station.lastReading ? `, last reading ${relativeAge(station.lastReading)}` : ""}` : "Not reporting now"}
            </p>
          </div>
          {station.pm25 != null && <AqiCard pm25={station.pm25} caption="Latest hourly PM2.5" className="w-full shrink-0 shadow-none md:w-[300px]" />}
        </div>
      </div>

      <div className="sticky top-0 z-10 border-b border-slate-100 bg-white px-4 pb-3 md:px-5">
        <div className="inline-flex items-center gap-0.5 rounded-full bg-slate-900/[0.06] p-0.5" role="tablist" aria-label="Station information">
          {TABS.map(({ key, label }) => (
            <button
              key={key}
              role="tab"
              aria-selected={activeTab === key}
              onClick={() => onTab(key)}
              className={`rounded-full px-3 py-1 text-xs font-medium transition-colors max-md:py-2 ${activeTab === key ? "bg-slate-900 text-white" : "text-slate-700 hover:bg-slate-900/[0.06]"}`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="station-panels p-4 md:p-5">
        {activeTab === "overview" && <OverviewPanel stationId={station.id} />}
        {activeTab === "uptime" && <UptimePanel stationId={station.id} />}
        {activeTab === "diurnal" && <DiurnalPanel stationId={station.id} />}
        {activeTab === "episodes" && <EpisodesPanel stationId={station.id} />}
      </div>
    </>
  );
}
