/** @type {import('next').NextConfig} */
const nextConfig = {
  // Standalone runtime requires `sharp` installed as a production dependency for image optimization.
  output: "standalone",
  images: {
    unoptimized: false,
  },
};

module.exports = nextConfig;
