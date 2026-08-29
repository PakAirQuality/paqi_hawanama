import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV === 'development';

const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  eslint: {
    ignoreDuringBuilds: true,
  },
  typescript: {
    ignoreBuildErrors: true,
  },
  // Dev-only: proxy /api/** to Cloud Run so same-origin tile URLs work locally.
  // Stripped at build time (output: "export" ignores rewrites in production).
  ...(isDev ? {
    async rewrites() {
      return [{
        source: '/api/:path*',
        destination: 'https://hawanama-152782825429.asia-south1.run.app/api/:path*',
      }];
    },
  } : {}),
};

export default nextConfig;
