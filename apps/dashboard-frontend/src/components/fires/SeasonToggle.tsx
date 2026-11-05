'use client'

import type { SeasonId } from './api'
import { Pill, PillGroup } from './Pill'

export function SeasonToggle({ value, onChange }: { value: SeasonId; onChange: (s: SeasonId) => void }) {
  return (
    <PillGroup label="Season">
      <Pill active={value === 'rice'} onClick={() => onChange('rice')} title="Rice stubble, 15 September to 30 November (the ISRO/CAQM paddy window)">Rice season (Sep–Nov)</Pill>
      <Pill active={value === 'wheat'} onClick={() => onChange('wheat')} title="Wheat stubble, 15 April to 31 May">Wheat season (Apr–May)</Pill>
    </PillGroup>
  )
}
