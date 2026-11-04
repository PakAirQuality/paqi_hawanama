'use client'

import type { ReactNode } from 'react'

export function Pill({ active, onClick, children, title }: { active: boolean; onClick: () => void; children: ReactNode; title?: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      title={title}
      className={`shrink-0 rounded-full px-3 py-1 text-xs font-medium transition-colors max-md:py-1.5 ${
        active ? 'bg-slate-900 text-white' : 'text-slate-700 hover:bg-slate-900/[0.06]'
      }`}
    >
      {children}
    </button>
  )
}

export function PillGroup({ children, label }: { children: ReactNode; label: string }) {
  return (
    <div role="group" aria-label={label} className="flex max-w-full gap-0.5 overflow-x-auto rounded-full bg-slate-900/[0.06] p-0.5 scrollbar-hide">
      {children}
    </div>
  )
}
