import type { AQICategory } from '@/lib/apiClient'
import { getAQICategory } from '@/lib/aqi'

interface AQICardProps {
  aqi: number
  categories: AQICategory[]
  mainPollutant: string
  mainValue: number
  mainUnits: string
}

export function AQICard({ aqi, categories, mainPollutant, mainValue, mainUnits }: AQICardProps) {
  const category = getAQICategory(aqi, categories)

  return (
    <div className="bg-white rounded-2xl border border-gray-200 p-6 shadow-sm">
      <div className="text-center">
        {/* AQI Badge */}
        <div 
          className="inline-flex items-center justify-center w-20 h-20 rounded-full mb-4"
          style={{ backgroundColor: category.color }}
        >
          <span 
            className="text-2xl font-bold"
            style={{ color: category.text_color }}
          >
            {aqi}
          </span>
        </div>

        {/* Category Label */}
        <h3 className="text-lg font-semibold text-gray-900 mb-2">
          {category.label}
        </h3>

        {/* Main Pollutant */}
        <div className="text-sm text-gray-600">
          <span className="font-medium">{mainPollutant}:</span>{' '}
          <span>{mainValue} {mainUnits}</span>
        </div>
      </div>
    </div>
  )
}