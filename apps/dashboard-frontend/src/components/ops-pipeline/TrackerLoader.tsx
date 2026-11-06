'use client'

import { m } from 'motion/react'

/**
 * The Tracker's loading screen: the PAQI logo filling in from top to bottom over a faint copy of itself, then
 * fading and filling again, with the Hawanama wordmark beneath. The page and the map show the same screen, so
 * the hand-off from one to the other is not seen.
 */
export function TrackerLoader({ className = '' }: { className?: string }) {
  return (
    <div
      role="status"
      aria-label="Loading the air quality map"
      className={`flex items-center justify-center bg-[radial-gradient(ellipse_at_center,#ffffff_0%,#f1f5f9_70%)] ${className}`}
    >
      <div className="flex flex-col items-center gap-3">
      <div className="relative h-16 w-16">
        {/* The faint outline the logo fills */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/logo-mark.png" alt="" width={64} height={64} className="absolute inset-0 h-full w-full object-contain opacity-[0.12] grayscale" />
        {/* The logo itself, revealed from the top down */}
        <m.div
          className="absolute inset-0"
          initial={{ clipPath: 'inset(0% 0% 100% 0%)', opacity: 1 }}
          animate={{ clipPath: ['inset(0% 0% 100% 0%)', 'inset(0% 0% 0% 0%)', 'inset(0% 0% 0% 0%)', 'inset(0% 0% 0% 0%)'], opacity: [1, 1, 1, 0] }}
          transition={{ duration: 2, times: [0, 0.6, 0.8, 1], ease: 'easeInOut', repeat: Infinity }}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/logo-mark.png" alt="" width={64} height={64} className="h-full w-full object-contain" />
        </m.div>
      </div>
      {/* The wordmark, as in the header */}
      <span className="text-[17px] font-semibold tracking-tight text-slate-900">Hawanama</span>
      </div>
    </div>
  )
}
