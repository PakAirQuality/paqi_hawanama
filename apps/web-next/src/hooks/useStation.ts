import { useCallback } from 'react'
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

export function useStationHistory(stationId: string | null, date?: string) {
  return useQuery({
    queryKey: ['station', stationId, 'history', date ?? 'live'],
    queryFn: ({ signal }) => apiClient.getStationHistory(stationId!, 24, date, signal),
    enabled: !!stationId,
    staleTime: 5 * 60 * 1000, // 5 minutes
    refetchInterval: date ? false : 5 * 60 * 1000, // live series refreshes; a fixed date never changes
  })
}

export function useStationPM25History(stationId: string | null, date?: string) {
  return useQuery({
    queryKey: ['station', stationId, 'pm25-history', date ?? 'live'],
    queryFn: ({ signal }) => apiClient.getStationPM25History(stationId!, 24, date, signal),
    enabled: !!stationId,
    staleTime: 5 * 60 * 1000, // 5 minutes
    refetchInterval: date ? false : 5 * 60 * 1000,
  })
}

export function useAQICategories() {
  return useQuery({
    queryKey: ['aqi', 'categories'],
    queryFn: ({ signal }) => apiClient.getAQICategories(signal),
    staleTime: 60 * 60 * 1000, // 1 hour (categories rarely change)
    refetchInterval: false,
  })
}

export function useAbortOnStationChange(stationId: string | null) {
  const queryClient = useQueryClient()

  // Stable identity: StationCard uses this in an effect dependency list.
  return useCallback(() => {
    // Cancel all queries for the previous station
    queryClient.cancelQueries({ queryKey: ['station'] })
  }, [queryClient])
}