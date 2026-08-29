import { create } from 'zustand'

interface StationSidebarState {
  isOpen: boolean
  stationId: string | null
  openStation: (stationId: string) => void
  close: () => void
}

export const useStationSidebar = create<StationSidebarState>((set) => ({
  isOpen: false,
  stationId: null,
  openStation: (stationId: string) => set({ isOpen: true, stationId }),
  close: () => set({ isOpen: false, stationId: null }),
}))