import { useSyncExternalStore } from 'react'

/** Subscribes to a CSS media query. Server and first client render report `false`. */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (notify) => {
      const mql = window.matchMedia(query)
      mql.addEventListener('change', notify)
      return () => mql.removeEventListener('change', notify)
    },
    () => window.matchMedia(query).matches,
    () => false,
  )
}

/** Phones and small tablets: below Tailwind's `md` breakpoint. */
export const useIsMobile = () => useMediaQuery('(max-width: 767px)')
