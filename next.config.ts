import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  // Pin the workspace root to this app so Next does not mis-detect a parent
  // directory when an unrelated package-lock.json exists higher up the tree.
  turbopack: {
    root: path.join(__dirname),
  },
  devIndicators: false,
};

export default nextConfig;
