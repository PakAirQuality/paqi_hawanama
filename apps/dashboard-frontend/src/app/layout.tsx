import "./globals.css";

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <title>Hawanama Analyst Dashboard: Pakistan PM2.5 model, observations and fires</title>
        <meta name="description" content="Public analyst dashboard of the Pakistan Air Quality Initiative: daily 1 km PM2.5 model estimates, ground observations, satellite fire detections and forecasts for Pakistan, with open data." />
        <link rel="icon" href="/logo-cropped.png" type="image/png" />
        <link rel="shortcut icon" href="/logo-cropped.png" />
        <link rel="apple-touch-icon" href="/logo-cropped.png" />
      </head>
      <body>{children}</body>
    </html>
  );
}