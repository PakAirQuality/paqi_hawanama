'use client'

import { useState } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { 
  BarChart3, 
  Settings, 
  Search, 
  TrendingUp,
  Menu,
  X
} from 'lucide-react'

const modules = [
  {
    id: 'aqi-dashboard',
    name: 'AQI Dashboard',
    href: '/',
    icon: BarChart3,
    description: 'Real-time air quality monitoring'
  },
  {
    id: 'station-management', 
    name: 'Station Management',
    href: '/stations',
    icon: Settings,
    description: 'Comprehensive station lifecycle management'
  },
  {
    id: 'data-quality',
    name: 'Data Quality',
    href: '/data-quality',
    icon: Search,
    description: 'QA/QC, validation, and ML readiness'
  },
  {
    id: 'network-analytics',
    name: 'Network Analytics', 
    href: '/analytics',
    icon: TrendingUp,
    description: 'System-wide insights and reporting'
  }
]

export function MainLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const getCurrentModuleFromPath = () => {
    const module = modules.find(m => 
      m.href === pathname || (m.href !== '/' && pathname.startsWith(m.href))
    )
    return module?.id || 'aqi-dashboard'
  }

  const currentModule = getCurrentModuleFromPath()

  const activeModule = modules.find(m => m.id === currentModule)

  return (
    <div className="min-h-screen bg-gray-50 flex">
      {/* Sidebar */}
      <div className={`${sidebarOpen ? 'translate-x-0' : '-translate-x-full'} lg:translate-x-0 fixed lg:static inset-y-0 left-0 z-50 w-64 bg-white shadow-xl lg:shadow-none transform transition-transform duration-300 ease-in-out`}>
        <div className="flex items-center justify-between h-20 px-6 border-b border-gray-200">
          {/* Logo and Title */}
          <div className="flex items-center space-x-3">
            <img 
              src="/logo-cropped.png" 
              alt="Hawanama Logo" 
              className="h-8 w-8 rounded-lg"
            />
            <div>
              <h1 className="text-lg font-bold text-gray-900">Hawanama</h1>
              <p className="text-xs text-gray-500">Air Quality</p>
            </div>
          </div>
          
          {/* Mobile close button */}
          <button
            className="lg:hidden"
            onClick={() => setSidebarOpen(false)}
          >
            <X className="h-6 w-6 text-gray-500" />
          </button>
        </div>

        {/* Navigation */}
        <nav className="mt-8 px-4">
          <div className="space-y-2">
            {modules.map((module) => {
              const isActive = currentModule === module.id
              const Icon = module.icon
              return (
                <Link
                  key={module.id}
                  href={module.href}
                  className={`flex items-center space-x-3 px-4 py-3 rounded-lg text-sm font-medium transition-colors ${
                    isActive
                      ? 'bg-blue-50 text-blue-700 border-r-4 border-blue-600'
                      : 'text-gray-600 hover:text-gray-900 hover:bg-gray-50'
                  }`}
                  onClick={() => setSidebarOpen(false)}
                >
                  <Icon className="h-5 w-5" />
                  <span>{module.name}</span>
                </Link>
              )
            })}
          </div>
        </nav>

      </div>

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Mobile Header */}
        <header className="bg-white border-b border-gray-200 shadow-sm lg:hidden">
          <div className="flex items-center justify-between h-16 px-4">
            {/* Mobile menu button */}
            <button
              onClick={() => setSidebarOpen(true)}
              className="text-gray-500 hover:text-gray-900"
            >
              <Menu className="h-6 w-6" />
            </button>
            
            {/* Mobile title */}
            <div className="flex items-center space-x-3">
              <img 
                src="/logo-cropped.png" 
                alt="Hawanama Logo" 
                className="h-8 w-8 rounded-lg"
              />
              <span className="text-lg font-bold text-gray-900">Hawanama</span>
            </div>

            <div></div>
          </div>
        </header>

        {/* Desktop Header - Page Title */}
        <header className="hidden lg:block bg-white border-b border-gray-200 shadow-sm">
          <div className="px-6 py-4 h-20 flex items-center justify-between">
            <div>
              <h2 className="text-2xl font-bold text-gray-900">
                {activeModule?.name || 'AQI Dashboard'}
              </h2>
              <p className="text-sm text-gray-500 mt-1">
                {activeModule?.description || 'Air Quality Monitoring System'}
              </p>
            </div>
            
            {/* System Status - Far right */}
            <div className="flex items-center space-x-2 px-4 py-2 bg-green-50 rounded-full">
              <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse"></div>
              <span className="text-sm text-green-700 font-medium">System Online</span>
            </div>
          </div>
        </header>

        {/* Main Content */}
        <main className="flex-1 overflow-auto p-6 lg:p-8">
          {children}
        </main>
      </div>

      {/* Mobile sidebar overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-40 bg-black bg-opacity-50 lg:hidden"
          onClick={() => setSidebarOpen(false)}
        ></div>
      )}
    </div>
  )
}