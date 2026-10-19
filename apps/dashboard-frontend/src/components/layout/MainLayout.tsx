'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { FreshnessBadge } from '@/components/layout/FreshnessBadge'
import { useOptionalSelection } from '@/lib/selection'

const modules = [
  { id: 'aqi-tracker', name: 'Air Quality Tracker', href: '/' },
  { id: 'analyst-desk', name: 'Analyst Desk', href: '/analyst-desk' },
  { id: 'reports', name: 'Reports', href: '/reports' },
  { id: 'bam', name: 'BAM Monitor', href: '/bam', group: 'Staff tools' },
]

function cn(...classes: (string | false | undefined)[]) {
  return classes.filter(Boolean).join(' ')
}

function SelectionStrip() {
  const selection = useOptionalSelection()
  if (!selection || !selection.date) return null
  return (
    <div className="hidden lg:block text-[11px] text-slate-500 rounded-full border border-slate-200 bg-slate-50 px-3 py-1 truncate max-w-[380px]" title="Current selection">
      {selection.describe()}
    </div>
  )
}

export function MainLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()

  const normalizedPath = pathname !== '/' ? pathname.replace(/\/+$/, '') : pathname

  const currentModule = modules.find(m =>
    m.href === normalizedPath || (m.href !== '/' && normalizedPath.startsWith(m.href))
  )?.id || 'aqi-tracker'

  const isFullBleed = currentModule === 'aqi-tracker' || currentModule === 'analyst-desk'
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
                <FreshnessBadge />
                <div className="text-slate-400">|</div>
                <div className="text-slate-600">
                  Pakistan Air Quality Initiative
                </div>
              </div>

              <div className="flex items-center gap-4">
                {/* Persistent selection strip: what every panel on the page is describing */}
                <SelectionStrip />
                {/* Public site: link back to the main map */}
                <a href="https://hawanama.org" className="text-sm text-slate-500 hover:text-slate-900 hidden sm:block">
                  hawanama.org
                </a>
              </div>
            </div>
          </div>
        </header>

        {/* Row 2: Navigation strip */}
        <nav className="bg-gradient-to-r from-slate-800 to-slate-900">
          <div className="px-4 lg:px-8">
            <div className="flex items-center h-11 -mb-px -ml-5 overflow-x-auto scrollbar-hide">
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
                    {'group' in module && module.group && (
                      <span className="ml-1.5 rounded px-1 py-px text-[9px] uppercase tracking-wide bg-slate-700 text-slate-300">{module.group}</span>
                    )}
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
