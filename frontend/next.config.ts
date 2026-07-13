import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  // Pin the workspace root so Next doesn't pick up a parent lockfile.
  turbopack: {
    root: path.join(__dirname),
  },
};

export default nextConfig;
