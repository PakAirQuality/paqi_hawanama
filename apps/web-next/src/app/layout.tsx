import type { Metadata, Viewport } from "next";
import "./globals.css";
import { QueryProvider } from "@/components/providers/QueryProvider";
import { SITE, jsonLd, organizationJsonLd, websiteJsonLd } from "@/lib/site";

export const metadata: Metadata = {
  metadataBase: new URL(SITE.url),
  title: {
    default: "Hawanama: Real-time Air Quality in Pakistan and South Asia",
    template: "%s | Hawanama",
  },
  description:
    "Live air quality map for Pakistan and South Asia by the Pakistan Air Quality Initiative (PAQI). Hourly PM2.5 and US AQI for Lahore, Karachi, Islamabad, Peshawar and 600+ cities, with open data downloads.",
  keywords: [
    "Pakistan air quality",
    "AQI Pakistan",
    "PM2.5",
    "Lahore air quality",
    "Karachi air quality",
    "Islamabad air quality",
    "smog",
    "Pakistan Air Quality Initiative",
    "PAQI",
    "Hawanama",
  ],
  applicationName: SITE.name,
  authors: [{ name: SITE.org, url: SITE.links.paqi }],
  creator: SITE.org,
  publisher: SITE.org,
  alternates: { canonical: "/" },
  robots: { index: true, follow: true },
  openGraph: {
    type: "website",
    siteName: SITE.name,
    locale: "en_US",
    url: "/",
    title: "Hawanama: Real-time Air Quality in Pakistan and South Asia",
    description: SITE.description,
    images: [{ url: SITE.ogImage, width: 1200, height: 630, alt: "Hawanama air quality map of Pakistan" }],
  },
  twitter: {
    card: "summary_large_image",
    site: SITE.twitter,
    creator: SITE.twitter,
    title: "Hawanama: Real-time Air Quality in Pakistan and South Asia",
    description: SITE.description,
    images: [SITE.ogImage],
  },
  icons: {
    icon: "/icon.png",
    shortcut: "/icon.png",
    apple: "/icon.png",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#ffffff",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: jsonLd(organizationJsonLd) }}
        />
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: jsonLd(websiteJsonLd) }}
        />
      </head>
      <body
        className="antialiased font-sans"
        suppressHydrationWarning
      >
        <QueryProvider>
          {children}
        </QueryProvider>
      </body>
    </html>
  );
}
