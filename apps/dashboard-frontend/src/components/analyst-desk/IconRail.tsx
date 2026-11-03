'use client'

import { MessageCircle, BarChart3, Radio, Building2, Flame, Layers } from 'lucide-react'
import { m } from 'motion/react'

export type RailTab = 'chat' | 'analytics' | 'stations' | 'sources' | 'fires' | 'layers'

interface IconRailProps {
  activeTab: RailTab | null
  onTabChange: (tab: RailTab | null) => void
  isStreaming?: boolean
  tabs?: RailTab[]
}

const ALL_TABS: { id: RailTab; icon: typeof MessageCircle; label: string }[] = [
  { id: 'chat', icon: MessageCircle, label: 'Chat' },
  { id: 'analytics', icon: BarChart3, label: 'Analytics' },
  { id: 'stations', icon: Radio, label: 'Stations' },
  { id: 'sources', icon: Building2, label: 'Sources' },
  { id: 'fires', icon: Flame, label: 'Fires' },
  { id: 'layers', icon: Layers, label: 'Layers' },
]

const SPRING = { type: 'spring', stiffness: 420, damping: 34 } as const

export function IconRail({ activeTab, onTabChange, isStreaming, tabs }: IconRailProps) {
  return (
    <nav
      aria-label="Panels"
      className="z-[100] flex shrink-0 items-center bg-white shadow-[1px_0_12px_rgba(15,23,42,0.06)] max-md:h-14 max-md:w-full max-md:justify-around max-md:px-2 max-md:shadow-[0_-1px_12px_rgba(15,23,42,0.08)] md:w-[56px] md:flex-col md:gap-1 md:pt-2"
    >
      {(tabs ? ALL_TABS.filter(t => tabs.includes(t.id)) : ALL_TABS).map((tab) => {
        const Icon = tab.icon
        const isActive = activeTab === tab.id
        return (
          <m.button
            key={tab.id}
            onClick={() => onTabChange(isActive ? null : tab.id)}
            title={tab.label}
            aria-label={tab.label}
            aria-pressed={isActive}
            whileTap={{ scale: 0.92 }}
            transition={SPRING}
            className={`relative flex h-12 w-12 max-md:w-16 flex-col items-center justify-center gap-0.5 rounded-xl transition-colors ${
              isActive ? 'text-slate-900' : 'text-slate-500 hover:bg-slate-900/[0.04] hover:text-slate-800'
            }`}
          >
            {/* Active background slides between tabs */}
            {isActive && (
              <m.span
                layoutId="rail-active"
                transition={SPRING}
                className="absolute inset-0 rounded-xl bg-slate-900/[0.07]"
              />
            )}
            <m.span
              className="relative"
              animate={tab.id === 'chat' && isStreaming ? { opacity: [1, 0.35, 1] } : { opacity: 1 }}
              transition={tab.id === 'chat' && isStreaming ? { duration: 1.4, repeat: Infinity, ease: 'easeInOut' } : { duration: 0.15 }}
            >
              <Icon size={19} strokeWidth={isActive ? 2.2 : 1.8} />
            </m.span>
            <span className="relative text-[11px] font-medium leading-none">{tab.label}</span>
          </m.button>
        )
      })}
    </nav>
  )
}
