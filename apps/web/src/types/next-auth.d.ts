import type { DefaultSession } from "next-auth";

declare module "next-auth" {
  // Extra fields returned by `authorize` (verify-credentials response).
  interface User {
    role?: string;
    session_version?: number;
  }

  interface Session {
    user: {
      id: string;
      role: string;
    } & DefaultSession["user"];
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    role?: string;
    session_version?: number;
  }
}
