'use client'

/**
 * Emissions — the PakEmis Explorer, embedded.
 *
 * The Explorer is its own application (its own repository, its own release payload, its own API on
 * Cloud Run). It is not copied in here: this page is the frame it hangs in, so that it can be
 * lifted out and deployed anywhere later without unpicking the dashboard from it.
 *
 * WHO IS READING. The Explorer's API runs with its sign-in gate on, so it answers only holders of
 * a Firebase ID token from this project whose address this organisation admits. The embedded page
 * has no session of its own — it asks this window for one. That is the whole handshake below: the
 * frame says `pakemis:auth-request`, we answer `pakemis:auth-token` with the token the signed-in
 * user already has, and every request the Explorer makes carries it. Nothing else crosses: we
 * check the message's origin, and we answer nothing else.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useAuth } from '@/components/auth/AuthProvider'

const EMISSIONS_URL = process.env.NEXT_PUBLIC_EMISSIONS_URL || 'https://pakemis.web.app'
const EMISSIONS_ORIGIN = new URL(EMISSIONS_URL).origin
const AUTH_REQUEST = 'pakemis:auth-request'
const AUTH_REPLY = 'pakemis:auth-token'

export default function EmissionsPage() {
  const { user, loading } = useAuth()
  const frameRef = useRef<HTMLIFrameElement>(null)
  const [ready, setReady] = useState(false)

  const answer = useCallback(async () => {
    const frame = frameRef.current?.contentWindow
    if (!frame || !user) return
    try {
      const token = await user.getIdToken()
      frame.postMessage({ type: AUTH_REPLY, token }, EMISSIONS_ORIGIN)
    } catch (error) {
      console.error('Could not hand the emissions view a sign-in token', error)
    }
  }, [user])

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (event.origin !== EMISSIONS_ORIGIN) return
      if ((event.data as { type?: string } | null)?.type !== AUTH_REQUEST) return
      void answer()
    }
    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
  }, [answer])

  // the frame asks on its own, but a re-sign-in mid-session should reach it without a reload
  useEffect(() => {
    if (ready && user) void answer()
  }, [ready, user, answer])

  if (loading) {
    return (
      <div className="h-full w-full flex items-center justify-center bg-slate-50">
        <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-slate-400" />
      </div>
    )
  }

  return (
    <iframe
      ref={frameRef}
      src={EMISSIONS_URL}
      title="Emissions"
      onLoad={() => setReady(true)}
      className="h-full w-full border-0 bg-white"
      allow="clipboard-write; fullscreen"
    />
  )
}
