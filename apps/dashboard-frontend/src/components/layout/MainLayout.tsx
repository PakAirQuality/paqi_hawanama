'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { FreshnessBadge } from '@/components/layout/FreshnessBadge'
import { LazyMotion, MotionConfig, domMax, m } from 'motion/react'

const modules = [
  { id: 'aqi-tracker', name: 'Tracker', href: '/' },
  { id: 'analyst-desk', name: 'Analyst Desk', href: '/analyst-desk' },
  { id: 'stations', name: 'Stations', href: '/stations' },
  { id: 'data-quality', name: 'Data Quality', href: '/data-quality' },
  { id: 'reports', name: 'Reports', href: '/reports' },
]

function cn(...classes: (string | false | undefined)[]) {
  return classes.filter(Boolean).join(' ')
}

export function MainLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()

  const normalizedPath = pathname !== '/' ? pathname.replace(/\/+$/, '') : pathname

  const currentModule = modules.find(m =>
    m.href === normalizedPath || (m.href !== '/' && normalizedPath.startsWith(m.href))
  )?.id || 'aqi-tracker'

  const isFullBleed = currentModule === 'aqi-tracker' || currentModule === 'analyst-desk'
  return (
    <LazyMotion features={domMax}>
    <MotionConfig reducedMotion="user">
    <div className="h-screen flex flex-col overflow-hidden">
      <header className="shrink-0 z-50 bg-white border-slate-200">
        <div className="flex items-center h-14 px-4 lg:px-6 gap-4 lg:gap-6">
          <Link href="/" className="flex items-center gap-2.5 shrink-0 rounded-lg" aria-label="Hawanama home">
            <img src="/logo-cropped.png" alt="" className="h-8 w-8 rounded-lg" />
            <span className="text-[15px] font-semibold tracking-tight text-slate-900 hidden sm:block">Hawanama</span>
          </Link>

          <nav aria-label="Main" className="flex items-center h-full min-w-0 overflow-x-auto scrollbar-hide -mx-1">
            {modules.map((module) => {
              const isActive = currentModule === module.id
              return (
                <Link
                  key={module.id}
                  href={module.href}
                  aria-current={isActive ? 'page' : undefined}
                  className={cn(
                    'relative px-3 h-full flex items-center text-[13px] font-medium whitespace-nowrap transition-colors',
                    isActive ? 'text-slate-900' : 'text-slate-600 hover:text-slate-900'
                  )}
                >
                  {module.name}
                  {isActive && (
                    <m.span
                      layoutId="nav-active"
                      transition={{ type: 'spring', stiffness: 400, damping: 32 }}
                      className="absolute bottom-0 left-2 right-2 h-0.5 bg-slate-900 rounded-full"
                    />
                  )}
                </Link>
              )
            })}
          </nav>

          <div className="ml-auto flex items-center gap-4 shrink-0 text-[13px]">
            <div className="hidden md:block"><FreshnessBadge /></div>
            {/* Public site: link back to the main map */}
            <a href="https://hawanama-dashboard.web.app" className="text-slate-600 hover:text-slate-900 hidden sm:block">
              Public map
            </a>
          </div>
        </div>
      </header>

      <main className={cn(
        'flex-1 min-h-0 flex flex-col',
        isFullBleed ? '' : 'p-4 lg:p-6 overflow-y-auto bg-slate-50'
      )}>
        {children}
      </main>
    </div>
    </MotionConfig>
    </LazyMotion>
  )
}
