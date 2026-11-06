'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { ArrowUpRight } from 'lucide-react'
import { FreshnessBadge } from '@/components/layout/FreshnessBadge'
import { REPORTS_SITE } from '@/lib/reports'
import { LazyMotion, MotionConfig, domMax, m } from 'motion/react'

// Hidden modules stay open by direct link, with no tab in the header
const modules = [
  { id: 'aqi-tracker', name: 'Tracker', href: '/' },
  { id: 'stations', name: 'Stations', href: '/stations', hidden: true },
  { id: 'data-quality', name: 'Data Quality', href: '/data-quality', hidden: true },
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

  const isFullBleed = currentModule === 'aqi-tracker'
  return (
    <LazyMotion features={domMax}>
    <MotionConfig reducedMotion="user">
    <div className="h-screen supports-[height:100dvh]:h-dvh flex flex-col overflow-hidden">
      <header className="shrink-0 z-50 bg-white border-slate-200">
        <div className="flex items-center h-14 px-3 sm:px-4 lg:px-6 gap-2 sm:gap-4 lg:gap-6">
          <Link href="/" className="flex items-center gap-2.5 shrink-0 rounded-lg" aria-label="Hawanama home">
            {/* Square mark with its own margin: the calligraphy's stroke tips and dots are never clipped */}
            <img src="/logo-mark.png" alt="" width={36} height={36} className="h-9 w-9 object-contain" />
            <span className="text-[15px] font-semibold tracking-tight text-slate-900 hidden sm:block">Hawanama</span>
          </Link>

          <nav aria-label="Main" className="flex items-center h-full min-w-0 overflow-x-auto scrollbar-hide -mx-1">
            {modules.filter(module => !module.hidden).map((module) => {
              const isActive = currentModule === module.id
              return (
                <Link
                  key={module.id}
                  href={module.href}
                  aria-current={isActive ? 'page' : undefined}
                  className={cn(
                    'relative px-1 min-[360px]:px-2 sm:px-3 h-full flex items-center text-[13px] font-medium whitespace-nowrap transition-colors',
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
            <a
              href={REPORTS_SITE}
              target="_blank"
              rel="noopener noreferrer"
              className="px-1 min-[360px]:px-2 sm:px-3 h-full flex items-center gap-0.5 text-[13px] font-medium whitespace-nowrap text-slate-600 transition-colors hover:text-slate-900"
            >
              Reports
              <ArrowUpRight size={13} aria-hidden />
            </a>
          </nav>

          <div className="ml-auto hidden md:flex items-center gap-4 shrink-0 text-[13px]">
            <FreshnessBadge />
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
