export const menuOptions = [
  ["/dashboard", "Overview"], ["/recordings", "Customer calls"],
  ["/risks", "Risk recordings"], ["/review", "QA review"],
  ["/agents", "Agent performance"], ["/batches", "Upload batches"],
  ["/evaluator", "QA criteria"], ["/amendments", "Transcript changes"],
  ["/transactions", "Transactions"], ["/recon", "Reconciliation"], ["/admin", "Admin"],
] as const;

export function menuVisible(path: string, overrides: Record<string, boolean>): boolean {
  if (path === "/settings") return true;
  return overrides[path] ?? path !== "/review";
}
