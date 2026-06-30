// Active-project resolution for the multi-project web app.
//
// The active project id lives in a `vq_project` cookie. Routes are NOT
// namespaced by project — server pages read the cookie, resolve the active
// project, and thread its id into the scoped reads (see the page-level
// `params.query.project_id` calls).

import { apiCall } from "@/lib/api";
import type { components } from "@voiceqa/shared-types";

export type Project = components["schemas"]["ProjectOut"];

/** Cookie name holding the active project's uuid. */
export const PROJECT_COOKIE = "vq_project";

/** GET /api/projects — every project the caller can see. */
export async function listProjects(cookieHeader: string): Promise<Project[]> {
  return apiCall("/api/projects", "get", { cookieHeader });
}

export interface ActiveProject {
  /** The resolved project, or null when none exist / the list failed to load. */
  project: Project | null;
  /** Convenience: the active project's id (empty string when none). */
  id: string;
  /** Convenience: the active project's module flags ({} when none). */
  modules: Record<string, unknown>;
  /** The full list, so callers can hand it to the switcher without refetching. */
  projects: Project[];
}

/**
 * Resolve the active project from the `vq_project` cookie, falling back to the
 * default project, then the first project. Returns the list too so the layout
 * can pass it straight to <ProjectSwitcher>.
 */
export async function getActiveProject(cookieHeader: string): Promise<ActiveProject> {
  let projects: Project[] = [];
  try {
    projects = await listProjects(cookieHeader);
  } catch {
    projects = [];
  }

  // Dynamic import keeps this module's top level client-safe: `lib/project.ts`
  // is also imported by client components (the switcher and nav) for the cookie
  // name, the Project type and `hasTradeReconciliation`. A static
  // `next/headers` import would make the whole module server-only and break the
  // client bundle.
  const { cookies } = await import("next/headers");
  const cookieId = (await cookies()).get(PROJECT_COOKIE)?.value;
  const project =
    (cookieId && projects.find((p) => p.id === cookieId)) ||
    projects.find((p) => p.is_default) ||
    projects[0] ||
    null;

  return {
    project,
    id: project?.id ?? "",
    modules: project?.modules ?? {},
    projects,
  };
}

/** True when the project opts into the `trade_reconciliation` module. */
export function hasTradeReconciliation(modules: Record<string, unknown> | null | undefined): boolean {
  return Boolean(modules && modules["trade_reconciliation"]);
}
