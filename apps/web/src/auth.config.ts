// Edge-safe Auth.js config — no DB adapter so it can run in middleware.
// The full auth.ts (with the Postgres adapter + Credentials provider) is used
// in route handlers and server components.

import type { NextAuthConfig } from "next-auth";

export const authConfig: NextAuthConfig = {
  session: { strategy: "jwt" },
  pages: {
    signIn: "/login",
  },
  providers: [], // Real providers live in src/auth.ts; middleware doesn't need them.
  callbacks: {
    authorized: ({ auth }) => !!auth,
  },
  trustHost: true,
};
