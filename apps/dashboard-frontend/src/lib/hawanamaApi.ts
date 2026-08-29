export const API_BASE =
  process.env.NEXT_PUBLIC_HAWANAMA_API_BASE_URL ||
  "https://hawanama-152782825429.asia-south1.run.app";

async function apiGet<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
    cache: "no-store",
  });

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${text || res.statusText}`);
  }
  return res.json() as Promise<T>;
}

/**
 * NOTE:
 * I'm assuming these meta endpoints exist (common FastAPI naming).
 * If your docs show different paths, just change them here.
 */
export async function getPollutants() {
  // ✅ This is the one you referenced in the docs
  return apiGet<Array<{ key?: string; name?: string } | string>>(
    `/api/v1/meta/pollutants`
  );
}

export async function getProvinces() {
  return apiGet<string[]>(`/api/v1/meta/provinces`);
}

export async function getCities(province: string) {
  return apiGet<string[]>(
    `/api/v1/meta/cities?province=${encodeURIComponent(province)}`
  );
}

export async function getStations(province: string, city: string) {
  return apiGet<Array<{ id: string; name: string }> | string[]>(
    `/api/v1/meta/stations?province=${encodeURIComponent(
      province
    )}&city=${encodeURIComponent(city)}`
  );
}

/**
 * Report data using existing backend APIs
 */
export async function getReportData(params: {
  province: string;
  city: string;
  stationIds: string[]; // empty => all stations
  pollutants: string[];
  dateFromISO: string;
  dateToISO: string;
}) {
  try {
    // Calculate hours back from date range
    const startDate = new Date(params.dateFromISO);
    const endDate = new Date(params.dateToISO);
    const hoursBack = Math.min(168, Math.max(1, Math.ceil((endDate.getTime() - startDate.getTime()) / (1000 * 60 * 60))));

    if (params.stationIds.length === 0) {
      // Get city-wide average data
      const cityData = await apiGet<any>(`/api/v1/cities/${encodeURIComponent(params.city)}/average/history?hours=${hoursBack}`);
      
      return {
        type: "city_average",
        city: params.city,
        province: params.province,
        hours_back: hoursBack,
        data: cityData,
        requested_pollutants: params.pollutants,
        date_range: {
          from: params.dateFromISO,
          to: params.dateToISO
        }
      };
    } else {
      // Get individual station data
      const stationDataPromises = params.stationIds.map(async (stationId) => {
        try {
          const stationData = await apiGet<any>(`/api/v1/stations/${encodeURIComponent(stationId)}/history?hours=${hoursBack}`);
          return {
            station_id: stationId,
            data: stationData
          };
        } catch (error) {
          return {
            station_id: stationId,
            error: error.message,
            data: null
          };
        }
      });

      const stationResults = await Promise.all(stationDataPromises);
      
      return {
        type: "station_data",
        city: params.city,
        province: params.province,
        hours_back: hoursBack,
        stations: stationResults,
        requested_pollutants: params.pollutants,
        date_range: {
          from: params.dateFromISO,
          to: params.dateToISO
        }
      };
    }
  } catch (error) {
    throw new Error(`Failed to fetch report data: ${error.message}`);
  }
}