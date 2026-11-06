'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, m } from 'motion/react'
import { CalendarDays, ChevronLeft, ChevronRight } from 'lucide-react'

interface DatePickerProps {
  /** Dates that can be chosen, as YYYY-MM-DD */
  dates: string[]
  value: string
  onChange: (date: string) => void
  /** Text shown on the button */
  label: string
}

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

const pad = (n: number) => String(n).padStart(2, '0')
const monthKey = (y: number, mo: number) => `${y}-${pad(mo + 1)}`

/** Date button that opens a month calendar where only dates with data can be picked. */
export function DatePicker({ dates, value, onChange, label }: DatePickerProps) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)

  const available = useMemo(() => new Set(dates), [dates])
  const first = dates[0]
  const last = dates[dates.length - 1]

  const [year, setYear] = useState(() => Number(value.slice(0, 4)))
  const [month, setMonth] = useState(() => Number(value.slice(5, 7)) - 1)

  // Reopen on the selected date's month
  useEffect(() => {
    if (open) { setYear(Number(value.slice(0, 4))); setMonth(Number(value.slice(5, 7)) - 1) }
  }, [open, value])

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => { if (!rootRef.current?.contains(e.target as Node)) setOpen(false) }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey) }
  }, [open])

  const cells = useMemo(() => {
    const startOffset = (new Date(year, month, 1).getDay() + 6) % 7 // Monday first
    const daysInMonth = new Date(year, month + 1, 0).getDate()
    const out: (number | null)[] = Array(startOffset).fill(null)
    for (let d = 1; d <= daysInMonth; d++) out.push(d)
    return out
  }, [year, month])

  const canPrev = first ? monthKey(year, month) > first.slice(0, 7) : false
  const canNext = last ? monthKey(year, month) < last.slice(0, 7) : false
  const shift = (delta: number) => {
    const d = new Date(year, month + delta, 1)
    setYear(d.getFullYear()); setMonth(d.getMonth())
  }
  const monthLabel = new Date(year, month, 1).toLocaleDateString('en-US', { month: 'long', year: 'numeric' })

  return (
    <div ref={rootRef} className="relative shrink-0">
      <button
        onClick={() => setOpen(v => !v)}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={`Date, ${label}. Change date`}
        className={`flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1.5 text-[13px] font-semibold tabular-nums text-slate-900 transition-[background-color,transform] duration-150 hover:bg-slate-900/[0.06] active:scale-[0.97] ${open ? 'bg-slate-900/[0.06]' : ''}`}
      >
        <CalendarDays size={14} className="shrink-0 text-slate-500" aria-hidden />
        {/* The new label slides in over the old one */}
        <span className="relative inline-grid overflow-hidden">
          <AnimatePresence mode="popLayout" initial={false}>
            <m.span
              key={label}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.18, ease: [0.2, 0.8, 0.2, 1] }}
              className="col-start-1 row-start-1"
            >
              {label}
            </m.span>
          </AnimatePresence>
        </span>
      </button>

      <AnimatePresence>
        {open && (
          <m.div
            role="dialog"
            aria-label="Choose a date"
            initial={{ opacity: 0, y: 8, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8, scale: 0.98 }}
            transition={{ duration: 0.16, ease: [0.2, 0.8, 0.2, 1] }}
            className="absolute bottom-full left-0 mb-3 w-[280px] rounded-2xl p-3 text-slate-900"
            style={{
              background: 'rgba(255,255,255,0.94)',
              backdropFilter: 'blur(20px) saturate(180%)',
              WebkitBackdropFilter: 'blur(20px) saturate(180%)',
              border: '1px solid rgba(15,23,42,0.08)',
              boxShadow: '0 8px 32px rgba(15,23,42,0.18)',
            }}
          >
            <div className="mb-2 flex items-center justify-between">
              <button
                onClick={() => shift(-1)}
                disabled={!canPrev}
                aria-label="Previous month"
                className="flex h-8 w-8 items-center justify-center rounded-full text-slate-700 hover:bg-slate-900/[0.06] disabled:opacity-30 disabled:hover:bg-transparent"
              >
                <ChevronLeft size={16} />
              </button>
              <div className="text-[13px] font-semibold">{monthLabel}</div>
              <button
                onClick={() => shift(1)}
                disabled={!canNext}
                aria-label="Next month"
                className="flex h-8 w-8 items-center justify-center rounded-full text-slate-700 hover:bg-slate-900/[0.06] disabled:opacity-30 disabled:hover:bg-transparent"
              >
                <ChevronRight size={16} />
              </button>
            </div>

            <div className="grid grid-cols-7 text-center text-xs text-slate-600">
              {WEEKDAYS.map(d => <div key={d} className="py-1">{d}</div>)}
            </div>
            <div className="grid grid-cols-7 gap-y-0.5 text-center">
              {cells.map((d, i) => {
                if (d == null) return <div key={`b${i}`} />
                const iso = `${year}-${pad(month + 1)}-${pad(d)}`
                const ok = available.has(iso)
                const selected = iso === value
                return (
                  <button
                    key={iso}
                    disabled={!ok}
                    onClick={() => { onChange(iso); setOpen(false) }}
                    aria-label={new Date(year, month, d).toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' })}
                    aria-pressed={selected}
                    className={`mx-auto flex h-9 w-9 items-center justify-center rounded-full text-[13px] tabular-nums transition-colors ${
                      selected ? 'bg-slate-900 font-semibold text-white'
                        : ok ? 'text-slate-900 hover:bg-slate-900/[0.07]'
                        : 'cursor-default text-slate-300'
                    }`}
                  >
                    {d}
                  </button>
                )
              })}
            </div>
          </m.div>
        )}
      </AnimatePresence>
    </div>
  )
}
