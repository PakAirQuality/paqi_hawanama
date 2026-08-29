// API client for internal station endpoints
const API_BASE = 'https://hawanama-152782825429.asia-south1.run.app/api/v1';

export interface Station {
  station_id: string;
  name: string;
  city: string;
  provider: string;
  active: boolean;
  last_seen: string;
  uptime_30d: number;
  pm25_latest?: number;
  aqi_latest?: number;
  latitude?: number;
  longitude?: number;
}

export interface StationOverview {
  station_id: string;
  name: string;
  city: string;
  provider: string;
  coordinates: {
    latitude: number;
    longitude: number;
  };
  status: 'online' | 'offline';
  current_reading: {
    pm25: number;
    aqi: number;
    timestamp: string;
  };
  summary_stats: {
    pm25_24h_avg: number;
    pm25_7d_avg: number;
    pm25_95th_percentile: number;
  };
  health_flags: string[];
  sparkline_data: Array<{
    timestamp: string;
    pm25: number;
  }>;
}

export interface StationUptime {
  station_id: string;
  uptime_30d: number;
  daily_uptime: Array<{
    date: string;
    uptime_percent: number;
  }>;
}

export interface DiurnalData {
  station_id: string;
  diurnal_pattern: Array<{
    hour: number;
    mean_pm25: number;
    median_pm25: number;
    weekday: boolean;
  }>;
  peak_hour: number;
  cleanest_hour: number;
}

export interface PollutionEpisode {
  start_ts: string;
  end_ts: string;
  duration_hours: number;
  max_pm25: number;
  max_aqi: number;
  severity_label: string;
  cause_guess?: string;
}

export interface StationEpisodes {
  station_id: string;
  episodes: PollutionEpisode[];
}

// API functions
export const stationsApi = {
  // List all stations
  getStations: async (): Promise<Station[]> => {
    const response = await fetch(`${API_BASE}/meta/stations`);
    if (!response.ok) throw new Error('Failed to fetch stations');
    return response.json();
  },

  // Get station overview
  getStationOverview: async (stationId: string): Promise<StationOverview> => {
    const response = await fetch(`${API_BASE}/internal/stations/${stationId}/overview`);
    if (!response.ok) throw new Error('Failed to fetch station overview');
    return response.json();
  },

  // Get station uptime data
  getStationUptime: async (stationId: string): Promise<StationUptime> => {
    const response = await fetch(`${API_BASE}/internal/stations/${stationId}/uptime`);
    if (!response.ok) throw new Error('Failed to fetch station uptime');
    return response.json();
  },

  // Get station diurnal pattern
  getStationDiurnal: async (stationId: string): Promise<DiurnalData> => {
    const response = await fetch(`${API_BASE}/internal/stations/${stationId}/diurnal`);
    if (!response.ok) throw new Error('Failed to fetch station diurnal data');
    return response.json();
  },

  // Get station pollution episodes
  getStationEpisodes: async (stationId: string): Promise<StationEpisodes> => {
    const response = await fetch(`${API_BASE}/internal/stations/${stationId}/episodes`);
    if (!response.ok) throw new Error('Failed to fetch station episodes');
    return response.json();
  },
};

// Utility functions
export const getAqiColor = (aqi: number): string => {
  if (aqi <= 50) return 'aqi-good';
  if (aqi <= 100) return 'aqi-moderate';
  if (aqi <= 150) return 'aqi-unhealthy-sensitive';
  if (aqi <= 200) return 'aqi-unhealthy';
  if (aqi <= 300) return 'aqi-very-unhealthy';
  return 'aqi-hazardous';
};

export const getAqiLabel = (aqi: number): string => {
  if (aqi <= 50) return 'Good';
  if (aqi <= 100) return 'Moderate';
  if (aqi <= 150) return 'Unhealthy for Sensitive Groups';
  if (aqi <= 200) return 'Unhealthy';
  if (aqi <= 300) return 'Very Unhealthy';
  return 'Hazardous';
};