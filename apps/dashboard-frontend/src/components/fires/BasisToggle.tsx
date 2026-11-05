'use client'

import { composeBasis, isCropBasis, isN20Basis, type Basis } from './api'
import { Pill, PillGroup } from './Pill'

/**
 * Which detections are counted. Two independent choices: every satellite or NOAA-20 alone (comparable
 * across years), and every detection or only those classified as likely crop-residue burning.
 */
export function BasisToggle({ value, onChange, available }: { value: Basis; onChange: (b: Basis) => void; available?: Basis[] }) {
  const can = (b: Basis) => !available || available.includes(b)
  const crop = isCropBasis(value)
  const n20 = isN20Basis(value)
  const cropOk = can(composeBasis(true, n20))
  const n20Ok = can(composeBasis(crop, true))
  return (
    <>
      <PillGroup label="Detections counted">
        <Pill active={!crop} onClick={() => onChange(composeBasis(false, n20))} title="Every deduplicated detection cluster, whatever burned">All detections</Pill>
        <Pill active={crop} onClick={() => cropOk && onChange(composeBasis(true, n20))}
          title={cropOk ? 'Only detections classified as likely crop-residue burning: cropland, harvest window, no listed kiln or industrial site within 1 km, not a persistent out-of-season cell (unvalidated)' : 'Available after the next fire-store rebuild'}>
          Likely crop-residue{cropOk ? '' : ' (soon)'}
        </Pill>
      </PillGroup>
      <PillGroup label="Satellites counted">
        <Pill active={!n20} onClick={() => onChange(composeBasis(crop, false))} title="Every satellite flown that day, deduplicated across satellites: the fullest picture of today">All satellites</Pill>
        <Pill active={n20} onClick={() => n20Ok && onChange(composeBasis(crop, true))}
          title={n20Ok ? 'NOAA-20 detections only: the satellite flown and processed in every year since 2020, so the series is comparable across years' : 'Available after the next fire-store rebuild'}>
          NOAA-20 only{n20Ok ? '' : ' (soon)'}
        </Pill>
      </PillGroup>
    </>
  )
}
