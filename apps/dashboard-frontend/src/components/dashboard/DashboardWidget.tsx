'use client'

import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'

interface DashboardWidgetProps {
  title: string
  value: string
  subtitle?: string
  icon?: string
  loading?: boolean
  className?: string
}

export function DashboardWidget({ 
  title, 
  value, 
  subtitle, 
  icon, 
  loading, 
  className = '' 
}: DashboardWidgetProps) {
  return (
    <Card className={`${className}`}>
      <CardContent className="p-6">
        <div className="flex items-start justify-between">
          <div className="flex-1">
            <div className="flex items-center space-x-2 mb-2">
              {icon && <span className="text-lg">{icon}</span>}
              <h3 className="text-sm font-medium text-gray-600">{title}</h3>
            </div>
            
            {loading ? (
              <div className="space-y-2">
                <div className="h-8 bg-gray-200 rounded animate-pulse w-24"></div>
                <div className="h-4 bg-gray-200 rounded animate-pulse w-32"></div>
              </div>
            ) : (
              <>
                <div className="text-2xl font-bold text-gray-900 mb-1">
                  {value}
                </div>
                {subtitle && (
                  <p className="text-sm text-gray-500">
                    {subtitle}
                  </p>
                )}
              </>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}