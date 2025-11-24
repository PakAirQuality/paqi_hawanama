'use client'

import type { Metadata } from 'next'
import './globals.css'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState } from 'react'

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
        <title>Hawanama Dashboard</title>
        <meta name="description" content="Internal air quality monitoring dashboard for Pakistan" />
      </head>
      <body>
        <QueryClientProvider client={queryClient}>
          <div className="min-h-screen bg-background">
            <header className="border-b border-border bg-card">
              <div className="container mx-auto px-4 py-4">
                <div className="flex items-center space-x-3">
                  <img 
                    src="/logo-cropped.png" 
                    alt="Hawanama Logo" 
                    className="h-10 w-10"
                  />
                  <div>
                    <h1 className="text-2xl font-bold text-foreground">
                      Hawanama Dashboard
                    </h1>
                    <p className="text-sm text-muted-foreground">
                      Internal air quality monitoring system
                    </p>
                  </div>
                </div>
              </div>
            </header>
            <main className="container mx-auto px-4 py-6">
              {children}
            </main>
          </div>
        </QueryClientProvider>
      </body>
    </html>
  )
}