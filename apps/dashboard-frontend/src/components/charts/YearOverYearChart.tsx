'use client'

import React, { useState, useEffect } from 'react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts'

const API_BASE = "https://hawanama-152782825429.asia-south1.run.app"

interface YearOverYearChartProps {
  selectedCity?: string
  onCityChange?: (city: string) => void
}

interface SeasonalData {
  day_of_year: number
  month_day: string
  month: number
  day: number
  [key: string]: any // year_XXXX properties
}

interface SeasonalTrendsResponse {
  city_slug: string
  city_name: string
  state: string
  country: string
  start_year: number
  end_year: number
  available_years: number[]
  count: number
  daily_data: SeasonalData[]
}

// City list for the dropdown
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

// Year colors matching the Python plot
const YEAR_COLORS: Record<number, string> = {
  2018: "#D803D8",
  2019: "#CD6D00",
  2020: "#9333ea",
  2021: "#0ECFCF",
  2022: "#064671",
  2023: "#0C6C1D",
  2024: "#5429CD",
  2025: "#AE0000",
  2026: "#0891b2", // Vibrant teal for current year
}

const formatCityName = (slug: string): string => {
  return slug.split('-').map(word => 
    word.charAt(0).toUpperCase() + word.slice(1)
  ).join(' ')
}

const transformHistoricalToSeasonal = (historicalData: any): SeasonalTrendsResponse => {
  const dailyDataByYear: { [year: number]: { [dayOfYear: number]: number } } = {}
  const availableYears = new Set<number>()
  
  // Group daily data by year and day-of-year
  historicalData.daily.forEach((day: any) => {
    if (!day.pm25_mean) return
    
    const date = new Date(day.date)
    const year = date.getFullYear()
    const startOfYear = new Date(year, 0, 1)
    const dayOfYear = Math.floor((date.getTime() - startOfYear.getTime()) / (1000 * 60 * 60 * 24)) + 1
    
    if (!dailyDataByYear[year]) {
      dailyDataByYear[year] = {}
    }
    
    dailyDataByYear[year][dayOfYear] = day.pm25_mean
    availableYears.add(year)
  })
  
  // Create daily data array with year columns
  const dailyData: SeasonalData[] = []
  for (let dayOfYear = 1; dayOfYear <= 366; dayOfYear++) {
    const date = new Date(2024, 0, dayOfYear) // Use 2024 as reference year
    const entry: SeasonalData = {
      day_of_year: dayOfYear,
      month_day: date.toLocaleDateString('en-US', { month: 'short', day: '2-digit' }),
      month: date.getMonth() + 1,
      day: date.getDate()
    }
    
    // Add year data
    Array.from(availableYears).forEach(year => {
      entry[`year_${year}`] = dailyDataByYear[year]?.[dayOfYear] || null
    })
    
    dailyData.push(entry)
  }
  
  return {
    city_slug: historicalData.city_slug,
    city_name: historicalData.city_name,
    state: historicalData.state,
    country: historicalData.country,
    start_year: Math.min(...Array.from(availableYears)),
    end_year: Math.max(...Array.from(availableYears)),
    available_years: Array.from(availableYears).sort(),
    count: dailyData.length,
    daily_data: dailyData
  }
}

export const YearOverYearChart: React.FC<YearOverYearChartProps> = ({
  selectedCity = "lahore",
  onCityChange
}) => {
  const [data, setData] = useState<SeasonalTrendsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [currentCity, setCurrentCity] = useState(selectedCity)
  const [visibleYears, setVisibleYears] = useState<Set<number>>(new Set())
  const [highlightedYear, setHighlightedYear] = useState<number | null>(null)

  const fetchSeasonalData = async (citySlug: string) => {
    setLoading(true)
    setError(null)
    
    try {
      // Fetch 5 years of historical data, daily resolution only (much smaller payload)
      const response = await fetch(`${API_BASE}/api/v1/cities/${citySlug}/historical-from-stations?hours=43800&resolution=daily`)
      
      if (!response.ok) {
        throw new Error(`Failed to fetch data for ${citySlug}`)
      }
      
      const historicalData = await response.json()
      
      // Transform the data to match the expected format
      const transformedData = transformHistoricalToSeasonal(historicalData)
      setData(transformedData)

      // Initialize only the 3 most recent years as visible
      const sortedYears = [...transformedData.available_years].sort((a, b) => b - a)
      const recentYears = sortedYears.slice(0, 3)
      setVisibleYears(new Set(recentYears))
      setHighlightedYear(null) // No year highlighted by default - all equal
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load data')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchSeasonalData(currentCity)
  }, [currentCity])

  const handleCityChange = (city: string) => {
    setCurrentCity(city)
    onCityChange?.(city)
  }

  const toggleYear = (year: number) => {
    const newVisibleYears = new Set(visibleYears)
    if (newVisibleYears.has(year)) {
      newVisibleYears.delete(year)
    } else {
      newVisibleYears.add(year)
    }
    setVisibleYears(newVisibleYears)
  }

  const toggleAllYears = () => {
    if (data) {
      if (visibleYears.size === data.available_years.length) {
        // Hide all
        setVisibleYears(new Set())
      } else {
        // Show all
        setVisibleYears(new Set(data.available_years))
      }
    }
  }

  const prepareChartData = () => {
    if (!data) return []
    
    // Sample every 7th day to make the chart more readable
    return data.daily_data.filter((_, index) => index % 7 === 0).map(dayData => {
      const chartPoint: any = {
        day_of_year: dayData.day_of_year,
        month_day: dayData.month_day,
        date: dayData.month_day
      }
      
      // Add year data
      data.available_years.forEach(year => {
        const yearKey = `year_${year}`
        chartPoint[year] = dayData[yearKey]
      })
      
      return chartPoint
    })
  }

  const chartData = prepareChartData()

  if (loading) {
    return (
      <div className="px-4 lg:px-8 py-8">
        <h2 className="text-xl font-semibold text-slate-900">Real-time PM₂.₅ Trends</h2>
        <div className="flex items-center justify-center h-64">
          <div className="text-slate-500">Loading seasonal trends...</div>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="px-4 lg:px-8 py-8">
        <h2 className="text-xl font-semibold text-slate-900">Real-time PM₂.₅ Trends</h2>
        <div className="flex items-center justify-center h-64">
          <div className="text-red-500">Error: {error}</div>
        </div>
      </div>
    )
  }

  return (
    <div className="px-4 lg:px-8 py-8">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-6">
        <div>
          <h2 className="text-xl font-semibold text-slate-900">Real-time PM₂.₅ Trends</h2>
          <p className="text-sm text-slate-600 mt-1">
            Year-over-year comparison for {data?.city_name || formatCityName(currentCity)}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {data && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-500 bg-slate-100 px-2 py-1 rounded">
                {data.available_years.length} years
              </span>
              <button
                onClick={toggleAllYears}
                className="px-3 py-1.5 text-sm bg-slate-100 hover:bg-slate-200 rounded-md transition-colors text-slate-700"
              >
                {visibleYears.size === data.available_years.length ? 'Hide All' : 'Show All'}
              </button>
            </div>
          )}
          <select
            value={currentCity}
            onChange={(e) => handleCityChange(e.target.value)}
            className="px-3 py-2 border border-slate-300 rounded-md text-sm bg-white"
          >
            {CITIES.map(city => (
              <option key={city} value={city}>
                {formatCityName(city)}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Chart - large like the map */}
      <div className="h-[calc(100vh-300px)] min-h-[400px]">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={chartData}
            onClick={(e) => {
              // Click on empty area to deselect
              if (!e?.activePayload) {
                setHighlightedYear(null)
              }
            }}
          >
            <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
            <XAxis
              dataKey="date"
              interval="preserveStartEnd"
              tick={{ fontSize: 12 }}
              angle={-45}
              textAnchor="end"
              height={60}
            />
            <YAxis
              label={{ value: 'PM₂.₅ (μg/m³)', angle: -90, position: 'insideLeft' }}
              tick={{ fontSize: 12 }}
            />
            <Tooltip
              labelFormatter={(label) => `Date: ${label}`}
              formatter={(value: any, name: any) => [
                value ? `${value.toFixed(1)} μg/m³` : 'No data',
                `Year ${name}`
              ]}
              cursor={{ strokeDasharray: '3 3' }}
            />
            <Legend />

            {/* Render non-highlighted lines first */}
            {data?.available_years
              .filter(year => visibleYears.has(year) && year !== highlightedYear)
              .map(year => (
                <Line
                  key={year}
                  type="monotone"
                  dataKey={year}
                  stroke={YEAR_COLORS[year] || '#666666'}
                  strokeWidth={highlightedYear ? 1.5 : 2}
                  strokeOpacity={highlightedYear ? 0.35 : 1}
                  dot={false}
                  name={year.toString()}
                  connectNulls={false}
                  activeDot={{
                    r: 6,
                    cursor: 'pointer',
                    onClick: () => setHighlightedYear(year)
                  }}
                />
              ))}

            {/* Highlighted line rendered last (on top) */}
            {highlightedYear && visibleYears.has(highlightedYear) && (
              <Line
                key={`highlighted-${highlightedYear}`}
                type="monotone"
                dataKey={highlightedYear}
                stroke={YEAR_COLORS[highlightedYear] || '#666666'}
                strokeWidth={4}
                dot={false}
                name={highlightedYear.toString()}
                connectNulls={false}
                activeDot={{
                  r: 8,
                  cursor: 'pointer',
                  onClick: () => setHighlightedYear(null)
                }}
              />
            )}
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Year toggles */}
      {data && data.available_years.length > 0 && (
        <div className="mt-6 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-slate-700 mr-2">Toggle Years:</span>
            {data.available_years.map(year => (
              <button
                key={year}
                onClick={() => toggleYear(year)}
                className={`px-3 py-1.5 text-sm rounded-full border transition-all ${
                  visibleYears.has(year)
                    ? ''
                    : 'bg-slate-100 border-slate-300 text-slate-600 hover:bg-slate-200'
                } ${highlightedYear === year ? 'ring-2 ring-offset-1' : ''}`}
                style={visibleYears.has(year) ? {
                  backgroundColor: `${YEAR_COLORS[year]}20`,
                  borderColor: YEAR_COLORS[year] || '#666666',
                  color: YEAR_COLORS[year] || '#666666',
                } : undefined}
              >
                {year}
                {highlightedYear === year && ' ★'}
              </button>
            ))}
          </div>
          <div className="text-xs text-slate-500">
            <p>
              Click on a data point in the chart to highlight that year. Click again to deselect.
            </p>
          </div>
        </div>
      )}
    </div>
  )
}