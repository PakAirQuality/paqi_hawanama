import { create } from 'zustand'

/** Daily-mean snapshot of the station on a specific past date (estimated mode). */
export type StationViewSnapshot = {
  pm25: number
  name?: string
  city?: string
}

interface StationSidebarState {
  isOpen: boolean
  stationId: string | null
  /** ISO date (YYYY-MM-DD) the user is viewing in estimated mode. null in live mode. */
  viewDate: string | null
  /** Snapshot from the daily-stations list. Drives the historical popup header. */
  viewSnapshot: StationViewSnapshot | null
  openStation: (stationId: string, viewDate?: string, snapshot?: StationViewSnapshot) => void
  close: () => void
}

export const useStationSidebar = create<StationSidebarState>((set) => ({
  isOpen: false,
  stationId: null,
  viewDate: null,
  viewSnapshot: null,
  openStation: (stationId, viewDate, snapshot) =>
    set({
      isOpen: true,
      stationId,
      viewDate: viewDate ?? null,
      viewSnapshot: snapshot ?? null,
    }),
  close: () => set({ isOpen: false, stationId: null, viewDate: null, viewSnapshot: null }),
}))