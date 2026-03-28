'use client'

import { MessageCircle, BarChart3, Layers, Flame, Wind } from 'lucide-react'

export type RailTab = 'chat' | 'analytics' | 'layers'

interface IconRailProps {
  activeTab: RailTab | null
  onTabChange: (tab: RailTab | null) => void
  isStreaming?: boolean
}

const TABS: { id: RailTab; icon: typeof MessageCircle; label: string }[] = [
  { id: 'chat', icon: MessageCircle, label: 'Chat' },
  { id: 'analytics', icon: BarChart3, label: 'Analytics' },
  { id: 'layers', icon: Layers, label: 'Layers' },
]

export function IconRail({ activeTab, onTabChange, isStreaming }: IconRailProps) {
  return (
    <div
      style={{
        width: 48,
        flexShrink: 0,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        paddingTop: 8,
        gap: 2,
        background: 'rgba(30, 41, 59, 0.97)',
        borderRight: '1px solid rgba(30, 41, 59, 0.3)',
        zIndex: 100,
      }}
    >
      {TABS.map((tab) => {
        const Icon = tab.icon
        const isActive = activeTab === tab.id
        return (
          <button
            key={tab.id}
            onClick={() => onTabChange(isActive ? null : tab.id)}
            title={tab.label}
            style={{
              width: 40,
              height: 40,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 2,
              border: 'none',
              borderRadius: 8,
              cursor: 'pointer',
              background: isActive ? 'rgba(255,255,255,0.15)' : 'transparent',
              color: isActive ? '#fff' : 'rgba(255,255,255,0.5)',
              transition: 'all 0.15s',
              position: 'relative',
            }}
            onMouseEnter={(e) => {
              if (!isActive) e.currentTarget.style.background = 'rgba(255,255,255,0.08)'
            }}
            onMouseLeave={(e) => {
              if (!isActive) e.currentTarget.style.background = 'transparent'
            }}
          >
            <Icon size={18} />
            <span style={{ fontSize: 7, fontWeight: 600, letterSpacing: '0.3px' }}>
              {tab.label}
            </span>
            {/* Streaming indicator on Chat tab */}
            {tab.id === 'chat' && isStreaming && (
              <span
                style={{
                  position: 'absolute',
                  top: 4,
                  right: 4,
                  width: 7,
                  height: 7,
                  borderRadius: '50%',
                  background: '#f59e0b',
                  border: '1.5px solid rgba(30, 41, 59, 0.95)',
                  animation: 'pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
                }}
              />
            )}
          </button>
        )
      })}
    </div>
  )
}
