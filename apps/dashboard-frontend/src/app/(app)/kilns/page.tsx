"use client"

import { useEffect, useMemo, useState } from "react"
import { Search, ChevronLeft, ChevronRight } from "lucide-react"

interface KilnItem {
  id: string
  state: string
  district?: string
  fuel: string
  capacity_tonnes: string
  lat: number
  lon: number
}

function SatImage({ lat, lon, id }: { lat: number; lon: number; id: string }) {
  const url = `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export?bbox=${lon - 0.002},${lat - 0.0015},${lon + 0.002},${lat + 0.0015}&bboxSR=4326&size=600,400&imageSR=4326&format=png&f=image`
  return (
    <div className="relative overflow-hidden rounded-xl">
      <img src={url} alt={`Satellite view of ${id}`} className="w-full h-auto object-cover" loading="lazy" />
      <div className="absolute top-1.5 left-1.5">
        <span className="text-[10px] font-medium text-white/90 bg-black/40 backdrop-blur-sm px-2 py-0.5 rounded">{id}</span>
      </div>
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2">
        <div className="w-3 h-3 rounded-full" style={{ background: '#d97706', border: '2px solid rgba(255,255,255,0.9)', boxShadow: '0 0 0 3px rgba(217,119,6,0.3)' }} />
      </div>
    </div>
  )
}

const MAJOR_PROVINCES = ['Punjab', 'Sindh', 'Khyber-Pakhtunkhwa', 'Balochistan', 'Islamabad', 'Azad Kashmir']

export default function KilnsPage() {
  const [kilns, setKilns] = useState<KilnItem[]>([])
  const [loading, setLoading] = useState(true)
  const [province, setProvince] = useState('')
  const [district, setDistrict] = useState('')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(0)
  const PAGE_SIZE = 24

  useEffect(() => {
    fetch('/brick_kilns.geojson')
      .then(r => r.json())
      .then(data => {
        setKilns(data.features.map((f: any) => ({
          ...f.properties,
          lat: f.geometry.coordinates[1],
          lon: f.geometry.coordinates[0],
        })))
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [])

  const provinces = useMemo(() => {
    const set = new Set(kilns.map(k => k.state).filter(Boolean))
    const sorted = [...set].sort()
    return [...MAJOR_PROVINCES.filter(p => set.has(p)), ...sorted.filter(p => !MAJOR_PROVINCES.includes(p))]
  }, [kilns])

  const districts = useMemo(() => {
    let source = kilns
    if (province) source = source.filter(k => k.state === province)
    const set = new Set(source.map(k => k.district).filter(Boolean) as string[])
    return [...set].sort()
  }, [kilns, province])

  const filtered = useMemo(() => {
    let list = [...kilns]
    if (province) list = list.filter(k => k.state === province)
    if (district) list = list.filter(k => k.district === district)
    if (search.trim()) {
      const q = search.toLowerCase()
      list = list.filter(k => k.id.toLowerCase().includes(q) || k.state.toLowerCase().includes(q) || (k.district || '').toLowerCase().includes(q) || k.fuel.toLowerCase().includes(q))
    }
    list.sort((a, b) => a.id.localeCompare(b.id))
    return list
  }, [kilns, province, district, search])

  const paged = useMemo(() => filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE), [filtered, page])
  const totalPages = Math.ceil(filtered.length / PAGE_SIZE)

  useEffect(() => setPage(0), [province, district, search])
  useEffect(() => setDistrict(''), [province])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="w-5 h-5 border-2 border-slate-300 border-t-slate-600 rounded-full animate-spin" />
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col bg-[#fafbfc]">
      {/* Header */}
      <div className="px-6 pt-6 pb-4 border-b border-slate-200/60">
        <h1 className="text-[22px] font-semibold text-[#1e293b] tracking-[-0.01em]">Brick Kilns</h1>
        <p className="text-[13px] text-[#94a3b8] mt-1">{kilns.length.toLocaleString()} geolocated kilns across Pakistan with satellite imagery</p>

        <div className="flex items-center gap-3 mt-4">
          <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-white border border-slate-200 flex-1 max-w-xs">
            <Search size={14} className="text-slate-400 shrink-0" />
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search kilns..."
              className="flex-1 text-[13px] bg-transparent outline-none text-slate-700 placeholder:text-slate-400"
            />
          </div>
          <select
            value={province}
            onChange={e => setProvince(e.target.value)}
            className="text-[12px] text-slate-600 bg-white border border-slate-200 rounded-lg px-3 py-2 outline-none"
          >
            <option value="">All provinces</option>
            {provinces.map(p => <option key={p} value={p}>{p}</option>)}
          </select>
          <select
            value={district}
            onChange={e => setDistrict(e.target.value)}
            className="text-[12px] text-slate-600 bg-white border border-slate-200 rounded-lg px-3 py-2 outline-none"
          >
            <option value="">All districts</option>
            {districts.map(d => <option key={d} value={d}>{d}</option>)}
          </select>
          <span className="text-[12px] text-slate-400 ml-auto">{filtered.length.toLocaleString()} kilns</span>
        </div>
      </div>

      {/* Grid */}
      <div className="flex-1 overflow-y-auto scrollbar-hide p-6">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {paged.map(k => (
            <div key={k.id} className="bg-white border border-slate-200 rounded-xl overflow-hidden hover:shadow-md transition-shadow">
              <SatImage lat={k.lat} lon={k.lon} id={k.id} />
              <div className="px-3.5 py-3">
                <div className="text-[13px] font-semibold text-slate-800">{k.id}</div>
                <div className="text-[11px] text-slate-400 mt-0.5">{k.district ? `${k.district}, ` : ''}{k.state} &middot; {k.fuel}</div>
              </div>
            </div>
          ))}
        </div>

        {totalPages > 1 && (
          <div className="flex items-center justify-center gap-3 mt-6 pb-4">
            <button
              onClick={() => setPage(p => Math.max(0, p - 1))}
              disabled={page === 0}
              className="flex items-center gap-1 text-[12px] font-medium text-slate-500 hover:text-slate-700 disabled:opacity-30 disabled:cursor-not-allowed px-3 py-1.5 rounded-lg border border-slate-200 bg-white"
            >
              <ChevronLeft size={14} /> Prev
            </button>
            <span className="text-[12px] text-slate-400">
              Page {page + 1} of {totalPages}
            </span>
            <button
              onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1}
              className="flex items-center gap-1 text-[12px] font-medium text-slate-500 hover:text-slate-700 disabled:opacity-30 disabled:cursor-not-allowed px-3 py-1.5 rounded-lg border border-slate-200 bg-white"
            >
              Next <ChevronRight size={14} />
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
