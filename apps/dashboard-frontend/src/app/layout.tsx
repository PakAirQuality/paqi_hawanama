import "./globals.css";

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <title>Hawanama Internal Dashboard</title>
        <meta name="description" content="Internal air quality monitoring dashboard for South Asia" />
        <link rel="icon" href="/logo-cropped.png" type="image/png" />
        <link rel="shortcut icon" href="/logo-cropped.png" />
        <link rel="apple-touch-icon" href="/logo-cropped.png" />
      </head>
      <body>{children}</body>
    </html>
  );
}