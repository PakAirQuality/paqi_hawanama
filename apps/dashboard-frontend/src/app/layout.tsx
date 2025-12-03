'use client'

import type { Metadata } from 'next'
import './globals.css'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState } from 'react'
import { MainLayout } from '@/components/layout/MainLayout'

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const [queryClient] = useState(() => new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 5 * 60 * 1000, // 5 minutes
        gcTime: 10 * 60 * 1000, // 10 minutes
        retry: 3,
        retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 30000),
      },
    },
  }))

  return (
    <html lang="en">
      <head>
        <title>Hawanama Internal Dashboard</title>
        <meta name="description" content="Internal air quality monitoring dashboard for Pakistan" />
        <link rel="icon" href="/logo-cropped.png" type="image/png" />
        <link rel="shortcut icon" href="/logo-cropped.png" />
        <link rel="apple-touch-icon" href="/logo-cropped.png" />
      </head>
      <body>
        <QueryClientProvider client={queryClient}>
          <MainLayout>
            {children}
          </MainLayout>
        </QueryClientProvider>
      </body>
    </html>
  )
}