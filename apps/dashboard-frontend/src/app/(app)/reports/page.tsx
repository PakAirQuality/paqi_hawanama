"use client";

import { useEffect, useMemo, useState } from "react";
import {
  getCities,
  getPollutants,
  getProvinces,
  getReportData,
  getStations,
} from "@/lib/hawanamaApi";

type Station = { id: string; name: string };

const FALLBACK_PROVINCES = [
  "Punjab",
  "Sindh",
  "Khyber Pakhtunkhwa",
  "Balochistan",
  "Gilgit-Baltistan",
  "Azad Jammu and Kashmir",
  "Islamabad Capital Territory",
];

const PARAM_OPTIONS = [
  { key: "pm10", label: "PM10" },
  { key: "pm25", label: "PM2.5" },
  { key: "no2", label: "NO₂" },
  { key: "so2", label: "SO₂" },
  { key: "co", label: "Carbon Monoxide" },
];

function toISO(dtLocal: string) {
  // dtLocal is from <input type="datetime-local" />
  // It is interpreted as local time by JS Date.
  const d = new Date(dtLocal);
  if (Number.isNaN(d.getTime())) return "";
  return d.toISOString();
}

export default function ReportsPage() {
  const [provinces, setProvinces] = useState<string[]>([]);
  const [cities, setCities] = useState<string[]>([]);
  const [stations, setStations] = useState<Station[]>([]);
  const [pollutantsMeta, setPollutantsMeta] = useState<any[]>([]);

  const [province, setProvince] = useState("");
  const [city, setCity] = useState("");

  const [selectAllStations, setSelectAllStations] = useState(false);
  const [selectedStationId, setSelectedStationId] = useState("");

  const [selectedParams, setSelectedParams] = useState<string[]>(
    PARAM_OPTIONS.map((p) => p.key) // default: all
  );

  const [reportFormat, setReportFormat] = useState<"tabular" | "graph">("tabular");

  // defaults: last 24 hours
  const now = useMemo(() => new Date(), []);
  const [dateFrom, setDateFrom] = useState(() => {
    const d = new Date(now.getTime() - 24 * 3600 * 1000);
    return d.toISOString().slice(0, 16); // YYYY-MM-DDTHH:MM
  });
  const [dateTo, setDateTo] = useState(() => now.toISOString().slice(0, 16));

  const [loadingMeta, setLoadingMeta] = useState(false);
  const [loadingReport, setLoadingReport] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [reportData, setReportData] = useState<any>(null);

  // Load top-level meta on mount
  useEffect(() => {
    (async () => {
      setLoadingMeta(true);
      setError(null);
      try {
        const [prov, pol] = await Promise.allSettled([
          getProvinces(),
          getPollutants(),
        ]);

        if (prov.status === "fulfilled") setProvinces(prov.value);
        else setProvinces(FALLBACK_PROVINCES);

        if (pol.status === "fulfilled") setPollutantsMeta(pol.value as any[]);
      } catch (e: any) {
        setProvinces(FALLBACK_PROVINCES);
        setError(e?.message || "Failed to load metadata.");
      } finally {
        setLoadingMeta(false);
      }
    })();
  }, []);

  // Province -> cities
  useEffect(() => {
    (async () => {
      setCities([]);
      setCity("");
      setStations([]);
      setSelectedStationId("");
      setSelectAllStations(false);

      if (!province) return;

      setError(null);
      try {
        // Extract just the province/state name without country suffix
        const provinceClean = province.replace(/, [^,]+$/, "");
        const c = await getCities(provinceClean);
        
        // Filter cities that belong to the selected province and extract city names
        const filteredCities = c
          .filter((fullCityName: string) => fullCityName.includes(province))
          .map((fullCityName: string) => {
            const parts = fullCityName.split(", ");
            return parts[0]; // Just the city name
          });
        
        setCities(filteredCities);
      } catch (e: any) {
        setError(e?.message || "Failed to load cities.");
      }
    })();
  }, [province]);

  // City -> stations
  useEffect(() => {
    (async () => {
      setStations([]);
      setSelectedStationId("");
      setSelectAllStations(false);

      if (!province || !city) return;

      setError(null);
      try {
        // Extract just the province/state name without country suffix
        const provinceClean = province.replace(/, [^,]+$/, "");
        const s = await getStations(provinceClean, city);

        // Backend returns [{station_id, station_name, display_name}, ...]
        const normalized: Station[] = Array.isArray(s)
          ? s.map((station: any) => ({
              id: station.station_id || station.id || station,
              name: station.station_name || station.name || station
            }))
          : [];

        setStations(normalized);
      } catch (e: any) {
        setError(e?.message || "Failed to load stations.");
      }
    })();
  }, [province, city]);

  const canSubmit =
    !!province &&
    !!city &&
    selectedParams.length > 0 &&
    !!toISO(dateFrom) &&
    !!toISO(dateTo) &&
    (selectAllStations || !!selectedStationId);

  const stationIdsToSend = useMemo(() => {
    if (selectAllStations) return []; // empty => backend interprets as ALL
    return selectedStationId ? [selectedStationId] : [];
  }, [selectAllStations, selectedStationId]);

  async function runReport() {
    setLoadingReport(true);
    setError(null);
    setReportData(null);

    try {
      const data = await getReportData({
        province,
        city,
        stationIds: stationIdsToSend,
        pollutants: selectedParams,
        dateFromISO: toISO(dateFrom),
        dateToISO: toISO(dateTo),
      });
      setReportData(data);
    } catch (e: any) {
      setError(e?.message || "Failed to fetch report data.");
    } finally {
      setLoadingReport(false);
    }
  }

  return (
    <div className="p-6 max-w-5xl">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">Average Report Criteria</h1>
      </div>

      {error && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-red-700">
          {error}
        </div>
      )}

      <div className="rounded-xl border bg-white p-5 shadow-sm">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Province */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Province Name
            </label>
            <select
              className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 appearance-none"
              value={province}
              onChange={(e) => setProvince(e.target.value)}
              disabled={loadingMeta}
            >
              <option value="">{loadingMeta ? "Loading..." : "Select..."}</option>
              {provinces.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </div>

          {/* City */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              City Name
            </label>
            <select
              className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 appearance-none disabled:bg-gray-50 disabled:text-gray-400"
              value={city}
              onChange={(e) => setCity(e.target.value)}
              disabled={!province || cities.length === 0}
            >
              <option value="">
                {!province ? "Select province to select city" : "Select..."}
              </option>
              {cities.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>

          {/* Station */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="block text-sm font-medium text-gray-700">
                Station Name
              </label>

              <label className="flex items-center gap-2 text-sm text-gray-700">
                <input
                  type="checkbox"
                  checked={selectAllStations}
                  onChange={(e) => setSelectAllStations(e.target.checked)}
                  disabled={!province || !city || stations.length === 0}
                />
                Select all stations
              </label>
            </div>

            <select
              className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 appearance-none disabled:bg-gray-50 disabled:text-gray-400"
              value={selectedStationId}
              onChange={(e) => setSelectedStationId(e.target.value)}
              disabled={!province || !city || stations.length === 0 || selectAllStations}
            >
              <option value="">
                {!city ? "Select city to select station" : "Select..."}
              </option>
              {stations.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>

            {selectAllStations && (
              <div className="text-xs text-gray-500 mt-1">
                All stations selected ({stations.length} stations in {city})
              </div>
            )}
          </div>

          {/* Parameters */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Parameters
            </label>

            <div className="rounded-lg border p-3">
              <div className="grid grid-cols-2 gap-2">
                {PARAM_OPTIONS.map((p) => {
                  const checked = selectedParams.includes(p.key);
                  return (
                    <label key={p.key} className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={(e) => {
                          setSelectedParams((prev) => {
                            if (e.target.checked) return [...prev, p.key];
                            return prev.filter((x) => x !== p.key);
                          });
                        }}
                      />
                      {p.label}
                    </label>
                  );
                })}
              </div>

              <div className="mt-3 flex gap-2">
                <button
                  className="text-sm px-3 py-1 rounded-lg border hover:bg-gray-50"
                  onClick={() => setSelectedParams(PARAM_OPTIONS.map((p) => p.key))}
                  type="button"
                >
                  Select all
                </button>
                <button
                  className="text-sm px-3 py-1 rounded-lg border hover:bg-gray-50"
                  onClick={() => setSelectedParams([])}
                  type="button"
                >
                  Clear
                </button>
              </div>
            </div>
          </div>

          {/* Report format */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Report Format
            </label>

            <div className="flex gap-2">
              <button
                type="button"
                className={`px-4 py-2 rounded-lg border ${
                  reportFormat === "tabular" ? "bg-blue-50 border-blue-300" : "hover:bg-gray-50"
                }`}
                onClick={() => setReportFormat("tabular")}
              >
                Tabular
              </button>
              <button
                type="button"
                className={`px-4 py-2 rounded-lg border ${
                  reportFormat === "graph" ? "bg-blue-50 border-blue-300" : "hover:bg-gray-50"
                }`}
                onClick={() => setReportFormat("graph")}
              >
                Graph
              </button>
            </div>
          </div>

          {/* Date From */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Date From
            </label>
            <input
              type="datetime-local"
              className="w-full rounded-lg border px-3 py-2"
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
            />
          </div>

          {/* Date To */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Date To
            </label>
            <input
              type="datetime-local"
              className="w-full rounded-lg border px-3 py-2"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
            />
          </div>
        </div>

        <div className="mt-5">
          <button
            className="px-6 py-2 rounded-lg bg-blue-600 text-white font-medium disabled:opacity-50"
            disabled={!canSubmit || loadingReport}
            onClick={runReport}
            type="button"
          >
            {loadingReport ? "Loading..." : "Submit"}
          </button>
        </div>
      </div>

      {/* Results */}
      <div className="mt-6">
        <h2 className="text-lg font-semibold text-gray-900 mb-2">Results</h2>

        {!reportData && !loadingReport && (
          <div className="text-gray-600 text-sm">
            Run a report to see results here.
          </div>
        )}

        {reportData && reportFormat === "tabular" && (
          <div className="rounded-xl border bg-white p-4 shadow-sm">
            <div className="text-sm text-gray-600 mb-2">
              Showing raw response (you can pivot into a proper table once your backend schema is finalized).
            </div>
            <pre className="text-xs overflow-auto whitespace-pre-wrap">
              {JSON.stringify(reportData, null, 2)}
            </pre>
          </div>
        )}

        {reportData && reportFormat === "graph" && (
          <div className="rounded-xl border bg-white p-4 shadow-sm">
            <div className="text-sm text-gray-600">
              Graph view needs the report response to be a consistent timeseries schema (e.g. timestamp/value per pollutant).
              Once you confirm the `/api/v1/reports/average` response format, we can render proper charts.
            </div>
            <pre className="text-xs overflow-auto whitespace-pre-wrap mt-3">
              {JSON.stringify(reportData, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}