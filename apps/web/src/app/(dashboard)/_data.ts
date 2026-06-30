// Server-side fetch helpers used by dashboard layout and pages.
import { cookies } from "next/headers";

import { apiCall } from "@/lib/api";

export async function cookieHeader(): Promise<string> {
  const all = (await cookies()).getAll();
  return all.map((c) => `${c.name}=${c.value}`).join("; ");
}

// GET /api/me response. Hand-written until `make codegen` replaces the
// shared-types placeholder with real OpenAPI types.
export interface Me {
  id: string;
  email: string;
  name: string | null;
  role: string;
}

export async function fetchMe(): Promise<Me> {
  // Cast: the shared-types placeholder leaves apiCall untyped until codegen.
  return (await apiCall("/api/me", "get", {
    cookieHeader: await cookieHeader(),
  })) as Me;
}
