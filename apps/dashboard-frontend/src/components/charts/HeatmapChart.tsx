'use client'

import React, { useEffect, useState, useMemo } from 'react'

const API_BASE = "https://hawanama-152782825429.asia-south1.run.app"

const CITIES = [
  "abbottabad", "bahawalpur", "bhopalwala", "chak-jhumra", "daska-kalan",
  "dera-ismail-khan", "eminabad", "faisalabad", "gujranwala", "haripur",
  "hundal", "hyderabad", "islamabad", "jhang", "jhelum", "kahna-nau",
  "karachi", "kasur", "khairpur-mirs", "kharan", "khurrianwala",
  "kot-malik-barkhurdar", "kotli-loharan", "kotri", "ladhewala-waraich",
  "lahore", "lodhran", "malam-jabba", "malir-cantonment", "mandi-bahauddin",
  "mirpur-khas", "multan", "murree", "pasrur", "pattoki", "peshawar",
  "pindi-bhattian", "qadirpur-ran", "quetta", "rahim-yar-khan", "raiwind",
  "rawalpindi", "rojhan", "sambrial", "sheikhupura", "sialkot", "skardu", "sukkur"
]

const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December'
]

const DAY_LABELS = ['M', 'T', 'W', 'T', 'F', 'S', 'S']

const formatCityName = (slug: string): string =>
  slug.split('-').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')

// PM2.5 color scale matching the reference image
function getPM25Color(value: number | null): string {
  if (value === null || value === undefined) return '#f3f4f6' // gray-100
  if (value <= 30) return '#15803d'   // dark green
  if (value <= 60) return '#22c55e'   // green
  if (value <= 90) return '#eab308'   // yellow
  if (value <= 120) return '#f97316'  // orange
  if (value <= 250) return '#dc2626'  // red
  return '#991b1b'                     // dark red
}

function getTextColor(value: number | null): string {
  if (value === null || value === undefined) return '#9ca3af'
  if (value <= 60) return '#ffffff'
  if (value <= 90) return '#1f2937'
  return '#ffffff'
}

interface DayData {
  date: string
  pm25_mean: number | null
}

interface MonthCalendar {
  year: number
  month: number
  label: string
  // 6 weeks x 7 days grid; each cell is { day: number | null, pm25: number | null, inMonth: boolean }
  grid: Array<Array<{ day: number | null; pm25: number | null; inMonth: boolean }>>
}

function buildMonthCalendars(dailyData: DayData[], selectedMonth: number): MonthCalendar[] {
  // Index pm25 by date string
  const pm25Map = new Map<string, number | null>()
  dailyData.forEach(d => {
    pm25Map.set(d.date, d.pm25_mean)
  })

  // Find all unique years
  const years = new Set<number>()
  dailyData.forEach(d => {
    const y = parseInt(d.date.substring(0, 4))
    if (!isNaN(y)) years.add(y)
  })

  const sortedYears = Array.from(years).sort()
  const calendars: MonthCalendar[] = []

  for (const year of sortedYears) {
    const firstDay = new Date(year, selectedMonth, 1)
    const daysInMonth = new Date(year, selectedMonth + 1, 0).getDate()

    // Monday=0 based day of week for first day
    let startDow = firstDay.getDay() - 1
    if (startDow < 0) startDow = 6 // Sunday becomes 6

    const grid: MonthCalendar['grid'] = []
    let currentDay = 1 - startDow // can be negative for padding

    for (let week = 0; week < 6; week++) {
      const row: MonthCalendar['grid'][0] = []
      for (let dow = 0; dow < 7; dow++) {
        if (currentDay >= 1 && currentDay <= daysInMonth) {
          const dateStr = `${year}-${String(selectedMonth + 1).padStart(2, '0')}-${String(currentDay).padStart(2, '0')}`
          row.push({ day: currentDay, pm25: pm25Map.get(dateStr) ?? null, inMonth: true })
        } else {
          // Show the day number from adjacent month but mark as out-of-month
          const adjDate = new Date(year, selectedMonth, currentDay)
          row.push({ day: adjDate.getDate(), pm25: null, inMonth: false })
        }
        currentDay++
      }
      grid.push(row)
      // Stop if we've passed end of month and completed the week
      if (currentDay > daysInMonth) break
    }

    calendars.push({
      year,
      month: selectedMonth,
      label: `${MONTH_NAMES[selectedMonth]}-${year}`,
      grid,
    })
  }

  return calendars
}

export function HeatmapChart() {
  const [dailyData, setDailyData] = useState<DayData[]>([])
  const [loading, setLoading] = useState(true)
  const [city, setCity] = useState('lahore')
  const [selectedMonth, setSelectedMonth] = useState(new Date().getMonth())

  useEffect(() => {
    const fetchData = async () => {
      setLoading(true)
      try {
        const res = await fetch(
          `${API_BASE}/api/v1/cities/${city}/historical-from-stations?hours=70080&resolution=daily`
        )
        if (!res.ok) throw new Error('Failed')
        const json = await res.json()
        setDailyData(json.daily || [])
      } catch {
        setDailyData([])
      } finally {
        setLoading(false)
      }
    }
    fetchData()
  }, [city])

  const calendars = useMemo(
    () => buildMonthCalendars(dailyData, selectedMonth),
    [dailyData, selectedMonth]
  )

  return (
    <div className="px-4 lg:px-8 py-8">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-6">
        <div>
          <h2 className="text-xl font-semibold text-slate-900">PM2.5 Calendar Heatmap</h2>
          <p className="text-sm text-slate-600 mt-1">
            Daily PM2.5 concentration for {formatCityName(city)} ({MONTH_NAMES[selectedMonth]})
          </p>
        </div>
        <div className="flex items-center gap-3">
          {calendars.length > 0 && (
            <span className="text-xs text-slate-500 bg-white px-2 py-1 rounded border border-slate-200">
              {calendars.length} years
            </span>
          )}
          <select
            value={selectedMonth}
            onChange={(e) => setSelectedMonth(parseInt(e.target.value))}
            className="px-3 py-2 border border-slate-300 rounded-md text-sm bg-white"
          >
            {MONTH_NAMES.map((name, i) => (
              <option key={i} value={i}>{name}</option>
            ))}
          </select>
          <select
            value={city}
            onChange={(e) => setCity(e.target.value)}
            className="px-3 py-2 border border-slate-300 rounded-md text-sm bg-white"
          >
            {CITIES.map(c => (
              <option key={c} value={c}>{formatCityName(c)}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Content */}
      {loading ? (
        <div className="flex items-center justify-center h-64">
          <div className="text-slate-500">Loading calendar data...</div>
        </div>
      ) : calendars.length === 0 ? (
        <div className="flex items-center justify-center h-64">
          <div className="text-slate-500">No data available</div>
        </div>
      ) : (
        <div className="flex gap-4 items-start">
          {/* Calendar grid */}
          <div className="flex flex-wrap gap-4 flex-1">
            {calendars.map((cal) => (
              <div key={`${cal.year}-${cal.month}`} className="flex-shrink-0">
                {/* Month-Year header */}
                <div className="text-center text-sm font-semibold text-slate-700 bg-white rounded-t px-2 py-1 border border-b-0 border-slate-200">
                  {cal.label}
                </div>
                <table className="border-collapse border border-slate-200">
                  <tbody>
                    {cal.grid.map((week, wi) => (
                      <tr key={wi}>
                        {week.map((cell, di) => (
                          <td
                            key={di}
                            className="w-8 h-7 text-center text-xs font-medium border border-slate-200/50"
                            style={{
                              backgroundColor: cell.inMonth ? getPM25Color(cell.pm25) : '#f8fafc',
                              color: cell.inMonth ? getTextColor(cell.pm25) : '#cbd5e1',
                            }}
                            title={
                              cell.inMonth && cell.pm25 !== null
                                ? `${cell.day} ${cal.label}: ${Math.round(cell.pm25)} µg/m³`
                                : undefined
                            }
                          >
                            {cell.day}
                          </td>
                        ))}
                      </tr>
                    ))}
                    {/* Day-of-week labels */}
                    <tr>
                      {DAY_LABELS.map((d, i) => (
                        <td key={i} className="text-center text-[10px] text-slate-500 pt-1 font-medium">
                          {d}
                        </td>
                      ))}
                    </tr>
                  </tbody>
                </table>
              </div>
            ))}
          </div>

          {/* Legend */}
          <div className="flex flex-col gap-1 ml-2 flex-shrink-0 pt-6">
            {[
              { label: '>250', color: '#991b1b' },
              { label: '121-250', color: '#dc2626' },
              { label: '91-120', color: '#f97316' },
              { label: '61-90', color: '#eab308' },
              { label: '31-60', color: '#22c55e' },
              { label: '0-30', color: '#15803d' },
            ].map((item) => (
              <div key={item.label} className="flex items-center gap-2">
                <div className="w-5 h-4 rounded-sm" style={{ backgroundColor: item.color }} />
                <span className="text-xs text-slate-600">{item.label}</span>
              </div>
            ))}
            <div className="text-[10px] text-slate-400 mt-1">µg/m³</div>
          </div>
        </div>
      )}
    </div>
  )
}
