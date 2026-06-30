// Mirrors apps/api/app/permissions.py: batches:manage / terms:write /
// config:write are granted to admin + compliance_manager only. The UI gates
// mutating affordances on the same pair; the API stays the enforcement point.
const MANAGE_ROLES = new Set(["admin", "compliance_manager"]);

// evals:review is broader: reviewers can re-run evaluations, review them and
// override per-criterion results — but cannot touch config (criteria/fields).
const REVIEW_ROLES = new Set(["admin", "compliance_manager", "reviewer"]);

export function canManage(role: string | null | undefined): boolean {
  return role != null && MANAGE_ROLES.has(role);
}

export function canReview(role: string | null | undefined): boolean {
  return role != null && REVIEW_ROLES.has(role);
}

export function isAdmin(role: string | null | undefined): boolean {
  return role === "admin";
}

// Assignable roles, matching the API's pattern
// `^(admin|compliance_manager|reviewer|broker|auditor)$` (apps/api schemas.py).
// `broker` is row-scoped (own extensions only) and requires broker_codes.
export const ROLES = [
  "admin",
  "compliance_manager",
  "reviewer",
  "broker",
  "auditor",
] as const;

export type Role = (typeof ROLES)[number];

const ROLE_LABELS: Record<string, string> = {
  admin: "Admin",
  compliance_manager: "Compliance manager",
  reviewer: "Reviewer",
  broker: "Broker",
  auditor: "Auditor",
};

export function roleLabel(role: string): string {
  return ROLE_LABELS[role] ?? role;
}

// Badge color per role, reusing the Badge variant palette.
export function roleBadgeVariant(
  role: string,
): "default" | "info" | "secondary" | "warning" | "neutral" {
  switch (role) {
    case "admin":
      return "default";
    case "compliance_manager":
      return "info";
    case "reviewer":
      return "secondary";
    case "broker":
      return "warning";
    default:
      return "neutral";
  }
}
