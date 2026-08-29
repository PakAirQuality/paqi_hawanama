'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { UserMenu } from '@/components/auth/UserMenu'

const modules = [
  { id: 'aqi-dashboard', name: 'Dashboard', href: '/' },
  { id: 'station-management', name: 'Stations', href: '/stations' },
  { id: 'data-quality', name: 'Data Quality', href: '/data-quality' },
  { id: 'reports', name: 'Reports', href: '/reports' },
  { id: 'analyst-desk', name: 'Analyst Desk', href: '/analyst-desk' },
  { id: 'ml-ops', name: 'ML Ops', href: '/ops/pipeline' },
  { id: 'kilns', name: 'Kilns', href: '/kilns' },
]

function cn(...classes: (string | false | undefined)[]) {
  return classes.filter(Boolean).join(' ')
}

export function MainLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()

  const normalizedPath = pathname !== '/' ? pathname.replace(/\/+$/, '') : pathname

  const currentModule = modules.find(m =>
    m.href === normalizedPath || (m.href !== '/' && normalizedPath.startsWith(m.href))
  )?.id || 'aqi-dashboard'

  const isFullBleed = currentModule === 'aqi-dashboard' || currentModule === 'analyst-desk' || currentModule === 'ml-ops' || currentModule === 'kilns'
  return (
    <div className="h-screen flex flex-col overflow-hidden">
      {/* Header container — shrink-0 keeps it fixed height, no sticky needed */}
      <div className="shrink-0 z-50">
        {/* Row 1: Top bar */}
        <header className="bg-white border-b border-slate-200">
          <div className="px-4 lg:px-8">
            <div className="flex items-center justify-between h-16">
              {/* Logo + tagline */}
              <Link href="/" className="flex items-center gap-3">
                <img
                  src="/logo-cropped.png"
                  alt="Hawanama"
                  className="h-10 w-10 rounded-xl"
                />
                <div className="flex flex-col">
                  <span className="text-lg font-semibold text-slate-900 leading-tight">
                    Hawanama
                  </span>
                  <span className="text-xs text-slate-500 hidden sm:block">
                    Air Quality Intelligence Platform
                  </span>
                </div>
              </Link>

              {/* Center info - hidden on mobile */}
              <div className="hidden md:flex items-center gap-6 text-sm">
                <div className="flex items-center gap-2 text-slate-600">
                  <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                  <span>Live Monitoring</span>
                </div>
                <div className="text-slate-400">|</div>
                <div className="text-slate-600">
                  South Asia Air Quality Network
                </div>
              </div>

              {/* User menu */}
              <UserMenu />
            </div>
          </div>
        </header>

        {/* Row 2: Navigation strip */}
        <nav className="bg-gradient-to-r from-slate-800 to-slate-900">
          <div className="px-4 lg:px-8">
            <div className="flex items-center h-11 -mb-px overflow-x-auto scrollbar-hide">
              {modules.map((module) => {
                const isActive = currentModule === module.id
                return (
                  <Link
                    key={module.id}
                    href={module.href}
                    className={cn(
                      'relative px-5 h-11 flex items-center text-sm font-medium whitespace-nowrap transition-colors',
                      isActive
                        ? 'text-white'
                        : 'text-slate-400 hover:text-slate-200'
                    )}
                  >
                    {module.name}
                    {/* Active indicator - bottom border */}
                    {isActive && (
                      <span className="absolute bottom-0 left-3 right-3 h-0.5 bg-amber-400 rounded-t-full" />
                    )}
                  </Link>
                )
              })}
            </div>
          </div>
        </nav>
      </div>

      {/* Main Content - no padding for dashboard (full-bleed map) */}
      <main className={cn(
        'flex-1 min-h-0 flex flex-col',
        isFullBleed ? '' : 'p-4 lg:p-6 overflow-y-auto bg-slate-50'
      )}>
        {children}
      </main>
    </div>
  )
}
