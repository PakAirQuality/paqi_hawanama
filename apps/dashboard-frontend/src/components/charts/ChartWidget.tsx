'use client'

import { ReactNode } from 'react'

interface ChartWidgetProps {
  title: string
  children: ReactNode
  className?: string
  minHeight?: string
  headerActions?: ReactNode
  subtitle?: string
}

export function ChartWidget({ 
  title, 
  children, 
  className = '', 
  minHeight = '350px',
  headerActions,
  subtitle 
}: ChartWidgetProps) {
  return (
    <div 
      className={`chart-widget flex-1 ${className}`}
      style={{ 
        minHeight,
        background: 'white',
        borderRadius: '12px',
        padding: '20px',
        boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.1)',
        border: '1px solid #e5e7eb'
      }}
    >
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-lg font-semibold text-gray-800 mb-1">
            {title}
          </h2>
          {subtitle && (
            <p className="text-sm text-gray-500">{subtitle}</p>
          )}
        </div>
        {headerActions && (
          <div className="chart-actions">
            {headerActions}
          </div>
        )}
      </div>
      
      <div className="chart-content">
        {children}
      </div>
    </div>
  )
}