'use client'

import { ChevronLeft, ChevronRight } from 'lucide-react'

interface Props {
  dates: string[]
  selectedDate: string | null
  onChange: (date: string) => void
}

function formatDisplayDate(dateStr: string): string {
  const [year, month, day] = dateStr.split('-').map(Number)
  const date = new Date(year, month - 1, day)
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

export default function EstimatedDateRail({ dates, selectedDate, onChange }: Props) {
  if (!dates.length || !selectedDate) return null

  const currentIndex = dates.indexOf(selectedDate)
  const safeIndex = currentIndex === -1 ? dates.length - 1 : currentIndex

  const goPrev = () => {
    if (safeIndex > 0) onChange(dates[safeIndex - 1])
  }

  const goNext = () => {
    if (safeIndex < dates.length - 1) onChange(dates[safeIndex + 1])
  }

  const handleSlider = (e: React.ChangeEvent<HTMLInputElement>) => {
    const idx = Number(e.target.value)
    onChange(dates[idx])
  }

  return (
    <div className="flex flex-col items-center gap-2 bg-black/20 backdrop-blur-md rounded-2xl border border-white/10 shadow-2xl px-4 py-3 min-w-[260px] max-w-[90vw]">
      {/* Date navigation */}
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={goPrev}
          disabled={safeIndex === 0}
          className="w-7 h-7 flex items-center justify-center rounded-full bg-white/10 hover:bg-white/20 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          aria-label="Previous date"
        >
          <ChevronLeft className="w-4 h-4 text-white" />
        </button>

        <span className="text-xs font-medium text-white/90 tracking-wide min-w-[120px] text-center">
          {formatDisplayDate(dates[safeIndex])}
        </span>

        <button
          type="button"
          onClick={goNext}
          disabled={safeIndex === dates.length - 1}
          className="w-7 h-7 flex items-center justify-center rounded-full bg-white/10 hover:bg-white/20 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          aria-label="Next date"
        >
          <ChevronRight className="w-4 h-4 text-white" />
        </button>
      </div>

      {/* Slider */}
      <input
        type="range"
        min={0}
        max={dates.length - 1}
        value={safeIndex}
        onChange={handleSlider}
        className="w-full h-1 appearance-none rounded-full cursor-pointer"
        style={{
          background: `linear-gradient(to right, #f59e0b ${(safeIndex / (dates.length - 1)) * 100}%, rgba(255,255,255,0.2) ${(safeIndex / (dates.length - 1)) * 100}%)`,
          accentColor: '#f59e0b',
        }}
        aria-label="Select date"
      />

      <span className="text-[10px] text-white/40">
        {dates.length} days available
      </span>
    </div>
  )
}
