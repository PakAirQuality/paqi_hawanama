'use client'

import type { Basis } from './api'
import { Pill, PillGroup } from './Pill'

/** Which detections are counted: every satellite flown that day, or NOAA-20 alone (comparable across years). */
export function BasisToggle({ value, onChange, available = true }: { value: Basis; onChange: (b: Basis) => void; available?: boolean }) {
  return (
    <PillGroup label="Satellites counted">
      <Pill active={value === 'all'} onClick={() => onChange('all')} title="Every satellite flown that day, deduplicated across satellites: the fullest picture of today">All satellites</Pill>
      <Pill active={value === 'n20'} onClick={() => available && onChange('n20')}
        title={available ? 'NOAA-20 detections only: the satellite flown and processed in every year since 2020, so the series is comparable across years' : 'Available after the next fire-store rebuild'}>
        NOAA-20 only{available ? '' : ' (soon)'}
      </Pill>
    </PillGroup>
  )
}
