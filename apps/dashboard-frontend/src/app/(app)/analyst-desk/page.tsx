'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'

// Everything on the Analyst Desk moved to the Tracker; this keeps old links working.
export default function AnalystDeskRedirect() {
  const router = useRouter()
  useEffect(() => { router.replace('/') }, [router])
  return null
}
