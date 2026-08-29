import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient, type StationCurrent, type StationHistory, type StationPM25History, type AQICategory } from '@/lib/apiClient'

export function useStationCurrent(stationId: string | null) {
  return useQuery({
    queryKey: ['station', stationId, 'current'],
    queryFn: ({ signal }) => apiClient.getStationCurrent(stationId!, signal),
    enabled: !!stationId,
    staleTime: 5 * 60 * 1000, // 5 minutes
    refetchInterval: 5 * 60 * 1000, // Poll every 5 minutes
  })
}

export function useStationHistory(stationId: string | null) {
  return useQuery({
    queryKey: ['station', stationId, 'history'],
    queryFn: ({ signal }) => apiClient.getStationHistory(stationId!, 24, signal),
    enabled: !!stationId,
    staleTime: 5 * 60 * 1000, // 5 minutes
  })
}

export function useStationPM25History(stationId: string | null) {
  return useQuery({
    queryKey: ['station', stationId, 'pm25-history'],
    queryFn: ({ signal }) => apiClient.getStationPM25History(stationId!, 24, signal),
    enabled: !!stationId,
    staleTime: 5 * 60 * 1000, // 5 minutes
  })
}

export function useAQICategories() {
  return useQuery({
    queryKey: ['aqi', 'categories'],
    queryFn: ({ signal }) => apiClient.getAQICategories(signal),
    staleTime: 60 * 60 * 1000, // 1 hour (categories rarely change)
  })
}

export function useAbortOnStationChange(stationId: string | null) {
  const queryClient = useQueryClient()
  
  return () => {
    // Cancel all queries for the previous station
    queryClient.cancelQueries({ queryKey: ['station'] })
  }
}