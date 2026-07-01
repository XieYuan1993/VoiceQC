// Full Auth.js v5 setup — used in route handlers and server components.
// `src/middleware.ts` uses the edge-safe subset in `auth.config.ts` and never
// touches the DB; only this file reads the SSO config / appends the Entra
// provider, so middleware stays edge-safe and cheap.

import PostgresAdapter from "@auth/pg-adapter";
import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";
import MicrosoftEntraID from "next-auth/providers/microsoft-entra-id";

import { authConfig } from "@/auth.config";
import { decryptStr } from "@/lib/crypto";
import { pool } from "@/lib/db";

// Server-side base URL for the FastAPI backend. Inside compose the API sits
// on a different host than the browser-facing NEXT_PUBLIC_API_URL, hence the
// override. BACKEND_API_URL is the canonical prod var (see lib/api.ts +
// next.config.mjs); accept API_URL too for back-compat.
const API_URL =
  process.env.API_URL ??
  process.env.BACKEND_API_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:7870";

// Stable provider id — must match the button on the login page
// (`signIn("microsoft-entra-id")`) and the `account.provider` check below.
const ENTRA_PROVIDER_ID = "microsoft-entra-id";

/** Shape of a 200 from POST /api/auth/verify-credentials. */
interface VerifiedUser {
  id: string;
  email: string;
  name: string | null;
  role: string;
  session_version: number;
}

/** The singleton `sso_config` row (id=1), shaped for the lazy provider build. */
interface SsoConfigRow {
  enabled: boolean;
  tenant_id: string | null;
  client_id: string | null;
  client_secret_enc: string | null;
  allowed_email_domains: string[];
  group_role_mappings: { group_id: string; role: string }[];
  auto_provision: boolean;
  default_role: string;
}

// In-process cache so we don't hit the DB on every request that builds the
// config. ~60s is short enough that toggling SSO in the admin UI takes effect
// almost immediately, long enough to avoid hammering Postgres.
const SSO_CACHE_TTL_MS = 60_000;
let ssoCache: { value: SsoConfigRow | null; at: number } | null = null;

/**
 * Read the one `sso_config` row (id=1). Cached in-process for ~60s. Any DB
 * failure resolves to `null` (caller falls back to credentials-only) — login
 * must never break because the SSO row couldn't be read.
 */
async function getSsoConfig(): Promise<SsoConfigRow | null> {
  const now = Date.now();
  if (ssoCache && now - ssoCache.at < SSO_CACHE_TTL_MS) {
    return ssoCache.value;
  }
  try {
    const { rows } = await pool.query<SsoConfigRow>(
      `SELECT enabled, tenant_id, client_id, client_secret_enc,
              allowed_email_domains, group_role_mappings, auto_provision, default_role
         FROM sso_config
        WHERE id = 1`,
    );
    const value = rows[0] ?? null;
    ssoCache = { value, at: now };
    return value;
  } catch {
    // Cache the miss briefly too, so a flapping DB doesn't get queried on
    // every single request while it's down.
    ssoCache = { value: null, at: now };
    return null;
  }
}

/** Find the first group→role mapping that matches any of the user's groups. */
function roleFromGroups(
  groups: unknown,
  mappings: { group_id: string; role: string }[],
): string | null {
  if (!Array.isArray(groups) || mappings.length === 0) return null;
  const groupSet = new Set(groups.map((g) => String(g)));
  for (const m of mappings) {
    if (groupSet.has(m.group_id)) return m.role;
  }
  return null;
}

/** DB user fields we resolve by email after an Entra sign-in. */
interface DbUserRow {
  id: string;
  role: string;
  is_active: boolean;
  session_version: number;
}

async function getUserByEmail(email: string): Promise<DbUserRow | null> {
  const { rows } = await pool.query<DbUserRow>(
    `SELECT id, role, is_active, session_version FROM users WHERE lower(email) = lower($1)`,
    [email],
  );
  return rows[0] ?? null;
}

// Lazy init (config factory): Phase 4 reads the SSO (Microsoft Entra) config
// from the DB here and appends the provider at request time when enabled. The
// Credentials flow is preserved exactly and built unconditionally; a failure
// to read sso_config degrades to credentials-only, never an outage.
export const { handlers, auth, signIn, signOut } = NextAuth(async () => {
  const sso = await getSsoConfig();
  const ssoUsable = !!(sso?.enabled && sso.tenant_id && sso.client_id && sso.client_secret_enc);

  return {
    ...authConfig,
    // users/accounts tables already exist; the adapter is wired now so Entra
    // SSO (Phase 4) can link OAuth accounts without an auth rewrite.
    // Credentials sign-ins are JWT-only and never touch adapter sessions.
    adapter: PostgresAdapter(pool),
    providers: [
      Credentials({
        credentials: {
          email: {},
          password: {},
        },
        async authorize(credentials) {
          // Password verification lives in the API (hashing + lockout policy
          // stay server-side). X-Internal-Secret keeps the endpoint
          // server-to-server only.
          let res: Response;
          try {
            res = await fetch(`${API_URL}/api/auth/verify-credentials`, {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                "X-Internal-Secret": process.env.INTERNAL_API_SECRET ?? "",
              },
              body: JSON.stringify({
                email: credentials?.email,
                password: credentials?.password,
              }),
            });
          } catch {
            return null; // API unreachable → treat as a failed sign-in.
          }
          if (!res.ok) return null;
          const user = (await res.json()) as VerifiedUser;
          return user;
        },
      }),
      // Microsoft Entra ID, appended only when the stored config is complete.
      // decryptStr mirrors the backend's AES-256-GCM (see lib/crypto.ts).
      ...(ssoUsable
        ? [
            MicrosoftEntraID({
              clientId: sso!.client_id!,
              clientSecret: decryptStr(sso!.client_secret_enc!),
              issuer: `https://login.microsoftonline.com/${sso!.tenant_id}/v2.0`,
            }),
          ]
        : []),
    ],
    callbacks: {
      ...authConfig.callbacks,
      async signIn({ user, account, profile }) {
        // Credentials sign-ins were already vetted by verify-credentials.
        if (account?.provider !== ENTRA_PROVIDER_ID) return true;

        const email = (user?.email ?? (profile?.email as string | undefined) ?? "")
          .trim()
          .toLowerCase();
        if (!email) return false;

        // SSO must be usable for an Entra sign-in to be honoured at all.
        if (!sso || !ssoUsable) return false;

        // (1) Domain allow-list (only enforced when non-empty).
        if (sso.allowed_email_domains.length > 0) {
          const domain = email.split("@")[1] ?? "";
          const ok = sso.allowed_email_domains.some(
            (d) => d.trim().toLowerCase() === domain,
          );
          if (!ok) return false;
        }

        // groups claim (when the app registration emits it) drives role mapping.
        const groups = (profile as Record<string, unknown> | undefined)?.groups;
        const mappedRole = roleFromGroups(groups, sso.group_role_mappings);

        try {
          const existing = await getUserByEmail(email);
          if (existing) {
            if (!existing.is_active) return false; // deactivated → deny.
            // Keep role in sync with the matching group mapping, if any.
            if (mappedRole && mappedRole !== existing.role) {
              await pool.query(`UPDATE users SET role = $1 WHERE id = $2`, [
                mappedRole,
                existing.id,
              ]);
            }
            return true;
          }
          // Not found → provision or deny.
          if (!sso.auto_provision) return false;
          const role = mappedRole ?? sso.default_role;
          const name =
            user?.name ?? (profile?.name as string | undefined) ?? null;
          await pool.query(
            `INSERT INTO users (email, name, role, is_active, "emailVerified")
             VALUES ($1, $2, $3, true, now())
             ON CONFLICT (email) DO NOTHING`,
            [email, name, role],
          );
          return true;
        } catch {
          // Any DB error during the SSO gate → deny this sign-in rather than
          // let an unvetted user through. Credentials login is unaffected.
          return false;
        }
      },
      async jwt({ token, user, account }) {
        // Credentials path: `authorize` returned the DB id/role/session_version.
        if (account?.provider !== ENTRA_PROVIDER_ID && user?.id) {
          token.sub = user.id;
          token.role = user.role;
          // session_version comes from verify-credentials; the API bumps it to
          // invalidate outstanding JWTs and verifies it on each request.
          token.session_version = user.session_version ?? 0;
          return token;
        }
        // Entra path: on first sign-in the adapter has linked/created the
        // account+user, but `user.id` here is next-auth's, not necessarily
        // carrying our role/session_version. Stamp them from the DB by email so
        // the FastAPI side can resolve `claims.sub` and check session_version.
        if (account?.provider === ENTRA_PROVIDER_ID) {
          const email = (user?.email ?? token.email ?? "").toString();
          if (email) {
            try {
              const dbUser = await getUserByEmail(email);
              if (dbUser) {
                token.sub = dbUser.id;
                token.role = dbUser.role;
                token.session_version = dbUser.session_version ?? 0;
              }
            } catch {
              // Leave the token as-is; the API will reject a missing/invalid
              // session_version on its side.
            }
          }
        }
        return token;
      },
      async session({ session, token }) {
        if (token.sub && session.user) {
          session.user.id = token.sub;
          // `typeof` narrow: custom claims read back as `unknown` here (the
          // next-auth/jwt augmentation doesn't reach @auth/core's callbacks).
          session.user.role = typeof token.role === "string" ? token.role : "";
        }
        return session;
      },
    },
  };
});
