'use client'

import { useEffect } from 'react'
import { usePersistentState } from '@/hooks/usePersistentState'
import { Switch } from '@/components/ui/switch'
import { Label } from '@/components/ui/label'

interface WindToggleProps {
  onToggle: (enabled: boolean) => void
  className?: string
}

export function WindToggle({ onToggle, className = '' }: WindToggleProps) {
  const [enabled, setEnabled] = usePersistentState('windLayerVisible', false)

  useEffect(() => {
    onToggle(enabled)
  }, [enabled, onToggle])

  const handleToggle = (checked: boolean) => {
    setEnabled(checked)
  }

  return (
    <div className={`bg-white/90 backdrop-blur-sm shadow-md rounded-md p-2 ${className}`}>
      <div className="flex items-center space-x-2">
        <Switch
          id="wind-layer"
          checked={enabled}
          onCheckedChange={handleToggle}
        />
        <Label
          htmlFor="wind-layer"
          className="text-sm font-medium cursor-pointer flex items-center gap-1.5"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M17.7 7.7a2.5 2.5 0 1 1 1.8 4.3H2" />
            <path d="M9.6 4.6A2 2 0 1 1 11 8H2" />
            <path d="M12.6 19.4A2 2 0 1 0 14 16H2" />
          </svg>
          Wind
        </Label>
      </div>
    </div>
  )
}
