'use client'

import { useCallback, useMemo } from 'react'
import { usePathname, useSearchParams } from 'next/navigation'
import { parseFiresParams, serializeFiresParams, type FiresParams } from './params'

/** URL-backed page state (static export: read with useSearchParams, write with replaceState). */
export function useFiresParams(districts?: { name: string }[]) {
  const sp = useSearchParams()
  const pathname = usePathname()
  const params = useMemo(() => parseFiresParams(sp.toString(), { districts }), [sp, districts])
  const set = useCallback((patch: Partial<FiresParams>) => {
    const next = { ...params, ...patch }
    const q = serializeFiresParams(next)
    if (typeof window !== 'undefined') window.history.replaceState(null, '', `${pathname}${q}`)
  }, [params, pathname])
  return { params, set }
}
