'use client'

import { useEffect } from 'react'
import { REPORTS_SITE } from '@/lib/reports'

// The Reports tab links straight to the reports site; this keeps old links working.
export default function ReportsRedirect() {
  useEffect(() => { window.location.replace(REPORTS_SITE) }, [])
  return null
}
