'use client'

import { useEffect } from 'react'
import { usePersistentState } from '@/hooks/usePersistentState'
import { Switch } from '@/components/ui/switch'
import { Label } from '@/components/ui/label'

interface ModelToggleProps {
  onToggle: (supportAware: boolean) => void
  className?: string
}

export function ModelToggle({ onToggle, className = '' }: ModelToggleProps) {
  const [supportAware, setSupportAware] = usePersistentState('supportAwareModel', false)

  useEffect(() => {
    onToggle(supportAware)
  }, [supportAware, onToggle])

  const handleToggle = (checked: boolean) => {
    setSupportAware(checked)
  }

  return (
    <div className={`bg-white/90 backdrop-blur-sm shadow-md rounded-md p-2 ${className}`}>
      <div className="flex items-center space-x-2">
        <Switch
          id="model-toggle"
          checked={supportAware}
          onCheckedChange={handleToggle}
        />
        <Label
          htmlFor="model-toggle"
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
            <path d="M12 2v4" />
            <path d="m6.34 6.34 2.83 2.83" />
            <path d="M2 12h4" />
            <path d="m6.34 17.66 2.83-2.83" />
            <path d="M12 18v4" />
            <path d="m17.66 17.66-2.83-2.83" />
            <path d="M18 12h4" />
            <path d="m17.66 6.34-2.83 2.83" />
          </svg>
          {supportAware ? 'Enhanced' : 'Satellite'}
        </Label>
      </div>
    </div>
  )
}
