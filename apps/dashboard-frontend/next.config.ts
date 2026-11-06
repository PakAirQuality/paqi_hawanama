import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV === "development";

const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  // Dev-only: proxy /api/** to Cloud Run so local pages are same-origin (the API's CORS
  // only allows the production origins). Ignored by the static export build.
  ...(isDev ? {
    compress: false, // gzip would hold a streamed chat answer back until it had finished
    async rewrites() {
      return [
        // VOICE_DEV_API (e.g. http://localhost:8001 in .env.local) sends the spoken brief to a local API,
        // for trying it before it is deployed; everything else still goes to Cloud Run
        ...(process.env.VOICE_DEV_API ? [{
          source: "/api/v1/voice/:path*",
          destination: `${process.env.VOICE_DEV_API}/api/v1/voice/:path*`,
        }] : []),
        {
          source: "/api/:path*",
          destination: "https://hawanama-152782825429.asia-south1.run.app/api/:path*",
        },
      ];
    },
  } : {}),
};

export default nextConfig;
