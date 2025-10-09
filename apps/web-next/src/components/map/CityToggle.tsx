'use client'

import { useEffect } from 'react'
import { usePersistentState } from '@/hooks/usePersistentState'
import { Switch } from '@/components/ui/switch'
import { Label } from '@/components/ui/label'

interface CityToggleProps {
  onToggle: (enabled: boolean) => void
  className?: string
}

export function CityToggle({ onToggle, className = '' }: CityToggleProps) {
  const [enabled, setEnabled] = usePersistentState('cityBoundariesVisible', false)

  // Synchronize with parent when enabled state changes
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
          id="city-boundaries"
          checked={enabled}
          onCheckedChange={handleToggle}
        />
        <Label 
          htmlFor="city-boundaries" 
          className="text-sm font-medium cursor-pointer"
        >
          Cities
        </Label>
      </div>
    </div>
  )
}