/**
 * The fire report's counting rule (Hawanama Fire Analytics, §5.1), applied to one day's detections
 * in the browser so the map and the API count the same way:
 *
 *  - detections from DIFFERENT satellites within 1 km and 90 minutes join one group (union-find,
 *    so the rule is transitive); pixels of one satellite never merge;
 *  - the detection with the highest FRP is the group's primary, and its FRP is the group's FRP;
 *  - a group is high/nominal if any member is;
 *  - "fires" = primaries of high/nominal groups (n_dedup_hn); raw rows are "detections".
 *
 * A group is a detection cluster, not a verified individual fire.
 */

export const DEDUP_KM = 1
export const DEDUP_MINUTES = 90
/** Degrees per km for the pair search, using the box's shortest degree of longitude (85 km), as the API does. */
const KM_PER_DEG_MIN = 85

export interface DetectionLike {
  geometry: { coordinates: number[] }
  properties?: { frp?: number | string | null; confidence?: string | null; satellite?: string | null; acq_datetime_utc?: string | null } | null
}

export interface DedupResult<T> {
  /** One entry per group: the primary detection, with the group's size and whether it is high/nominal */
  groups: { primary: T; size: number; hn: boolean }[]
  /** Primaries of high/nominal groups: the report's "fires" */
  fires: T[]
  detections: number
}

const isHn = (c: string | null | undefined) => {
  const v = (c ?? '').toString().toLowerCase()
  return v === 'h' || v === 'n' || v === 'high' || v === 'nominal'
}

function km(lon1: number, lat1: number, lon2: number, lat2: number): number {
  const x = (lon2 - lon1) * Math.cos(((lat1 + lat2) / 2) * (Math.PI / 180)) * 111.32
  const y = (lat2 - lat1) * 110.57
  return Math.sqrt(x * x + y * y)
}

export function dedupDetections<T extends DetectionLike>(rows: T[]): DedupResult<T> {
  const n = rows.length
  const parent = Array.from({ length: n }, (_, i) => i)
  const find = (i: number): number => {
    while (parent[i] !== i) { parent[i] = parent[parent[i]]; i = parent[i] }
    return i
  }
  const union = (a: number, b: number) => { const ra = find(a), rb = find(b); if (ra !== rb) parent[rb] = ra }

  const step = DEDUP_KM / KM_PER_DEG_MIN
  const cells = new Map<string, number[]>()
  const time = rows.map(r => Date.parse(r.properties?.acq_datetime_utc ?? ''))
  rows.forEach((r, i) => {
    const [lon, lat] = r.geometry.coordinates
    const key = `${Math.floor(lon / step)},${Math.floor(lat / step)}`
    const list = cells.get(key)
    if (list) list.push(i); else cells.set(key, [i])
  })
  rows.forEach((r, i) => {
    const [lon, lat] = r.geometry.coordinates
    const cx = Math.floor(lon / step), cy = Math.floor(lat / step)
    for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) {
      for (const j of cells.get(`${cx + dx},${cy + dy}`) ?? []) {
        if (j <= i) continue
        const sa = r.properties?.satellite, sb = rows[j].properties?.satellite
        if (!sa || !sb || sa === sb) continue // one satellite's pixels never merge
        if (!(Math.abs(time[i] - time[j]) <= DEDUP_MINUTES * 60_000)) continue
        const [lon2, lat2] = rows[j].geometry.coordinates
        if (km(lon, lat, lon2, lat2) <= DEDUP_KM) union(i, j)
      }
    }
  })

  const byRoot = new Map<number, number[]>()
  for (let i = 0; i < n; i++) {
    const root = find(i)
    const list = byRoot.get(root)
    if (list) list.push(i); else byRoot.set(root, [i])
  }
  const frp = (i: number) => Number(rows[i].properties?.frp) || 0
  const groups = [...byRoot.values()].map(members => {
    const primary = members.reduce((best, i) => (frp(i) > frp(best) ? i : best), members[0])
    return { primary: rows[primary], size: members.length, hn: members.some(i => isHn(rows[i].properties?.confidence)) }
  })
  return { groups, fires: groups.filter(g => g.hn).map(g => g.primary), detections: n }
}
