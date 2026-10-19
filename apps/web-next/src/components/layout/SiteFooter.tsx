import Link from 'next/link'
import { SITE } from '@/lib/site'

const ext = { target: '_blank', rel: 'noopener' } as const

export default function SiteFooter() {
  return (
    <footer className="border-t mt-12 bg-background">
      <div className="container mx-auto px-4 py-8 grid grid-cols-1 sm:grid-cols-3 gap-8 text-sm">
        <div>
          <p className="font-semibold text-foreground">{SITE.name}</p>
          <p className="text-muted-foreground mt-1">
            Real-time air quality for Pakistan and South Asia, a project of the{' '}
            <a href={SITE.links.paqi} className="underline hover:text-foreground" {...ext}>
              {SITE.org}
            </a>
            .
          </p>
        </div>
        <div>
          <p className="font-semibold text-foreground">Explore</p>
          <ul className="mt-1 space-y-1 text-muted-foreground">
            <li><Link href="/" className="hover:underline">Live map</Link></li>
            <li><Link href="/city/" className="hover:underline">Air quality by city</Link></li>
            <li><Link href="/about/" className="hover:underline">About, data sources and downloads</Link></li>
            <li><a href={SITE.links.emissions} className="hover:underline" {...ext}>Pakistan emissions inventory (PakEmis)</a></li>
          </ul>
        </div>
        <div>
          <p className="font-semibold text-foreground">Open source and data</p>
          <ul className="mt-1 space-y-1 text-muted-foreground">
            <li><a href={SITE.links.githubRepo} className="hover:underline" {...ext}>Hawanama on GitHub</a></li>
            <li><a href={SITE.links.estimationRepo} className="hover:underline" {...ext}>Satellite PM2.5 estimation (code and data)</a></li>
            <li><a href={SITE.links.emissionsRepo} className="hover:underline" {...ext}>PakEmis emissions inventory (code and data)</a></li>
            <li><a href={SITE.links.github} className="hover:underline" {...ext}>github.com/PakAirQuality</a></li>
            <li><a href={SITE.links.twitter} className="hover:underline" {...ext}>@pakairquality</a></li>
          </ul>
        </div>
      </div>
    </footer>
  )
}
