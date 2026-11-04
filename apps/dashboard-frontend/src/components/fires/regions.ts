// Region chip presets (ids are what the URL carries; `api` is what /api/v1/fires understands).

export interface RegionPreset {
  id: string
  label: string
  short?: string
  group: 'main' | 'province'
}

export const REGION_PRESETS: RegionPreset[] = [
  { id: 'pakistan', label: 'Pakistan', group: 'main' },
  { id: 'india', label: 'Indian Punjab + Haryana', short: 'India', group: 'main' },
  { id: 'indian-punjab', label: 'Indian Punjab', group: 'main' },
  { id: 'haryana', label: 'Haryana', group: 'main' },
  { id: 'bbox', label: 'Whole box', group: 'main' },
  { id: 'punjab', label: 'Punjab', group: 'province' },
  { id: 'sindh', label: 'Sindh', group: 'province' },
  { id: 'kp', label: 'Khyber Pakhtunkhwa', short: 'KP', group: 'province' },
  { id: 'balochistan', label: 'Balochistan', group: 'province' },
  { id: 'gb', label: 'Gilgit-Baltistan', short: 'GB', group: 'province' },
  { id: 'ajk', label: 'Azad Kashmir', short: 'AJK', group: 'province' },
  { id: 'islamabad', label: 'Islamabad', group: 'province' },
]

export const PRESET_IDS = new Set(REGION_PRESETS.map(p => p.id))

/** Districts are passed by name; everything else by preset id. */
export function isPreset(region: string): boolean {
  return PRESET_IDS.has(region)
}

export function regionLabel(region: string, districts?: { name: string; province: string }[]): string {
  const p = REGION_PRESETS.find(r => r.id === region)
  if (p) return p.label
  const d = districts?.find(x => x.name.toLowerCase() === region.toLowerCase())
  return d ? `${d.name} district` : region
}

/** The district table's scope for a chip: a province restricts, Pakistan/box show all, India has none. */
export function districtScope(region: string): string | null {
  if (['india', 'indian-punjab', 'haryana'].includes(region)) return null
  if (['pakistan', 'bbox'].includes(region)) return 'pakistan'
  return region
}

export function isProvince(region: string): boolean {
  return REGION_PRESETS.some(p => p.id === region && p.group === 'province')
}
