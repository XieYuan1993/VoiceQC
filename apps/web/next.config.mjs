import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Standalone output: works in compose now, deploys to Vercel later untouched.
  output: "standalone",
  // pnpm workspaces + standalone tracer: explicitly point at monorepo root.
  outputFileTracingRoot: resolve(__dirname, "../../"),
  reactStrictMode: true,
  // Note: experimental.typedRoutes is not yet Turbopack-compatible (Next 15.0.3).
  // Re-enable when Turbopack catches up, or drop --turbopack from `pnpm dev`.

  // Proxy browser API calls to the FastAPI backend SAME-ORIGIN. When web and api
  // live on different domains (e.g. *.vercel.app + *.onrender.com) the session
  // cookie is SameSite=Lax and would not ride along on cross-site client fetches;
  // routing /api/* through the web origin keeps it first-party. Set BACKEND_API_URL
  // in prod.
  //
  // IMPORTANT: exclude NextAuth's own routes (/api/auth/*) from the proxy. Next.js
  // rewrites in `afterFiles` run AFTER static files but BEFORE dynamic routes, and
  // [...nextauth] is a dynamic route — so a bare "/api/:path*" catch-all shadows it
  // and proxies /api/auth/csrf, /api/auth/callback, etc. to FastAPI (404). That
  // silently breaks sign-in for every fresh session. The negative lookahead keeps
  // /api/auth/* on the Next.js server and proxies only the rest.
  async rewrites() {
    const backend = process.env.BACKEND_API_URL ?? "http://localhost:7870";
    return {
      afterFiles: [
        { source: "/api/:path((?!auth/).*)", destination: `${backend}/api/:path` },
      ],
    };
  },
};

export default nextConfig;
