import { auth } from "@/auth";
import { canManage } from "@/lib/roles";

import { ReconView } from "./recon-view";

// recon:run and recon:review are granted to admin + compliance_manager only
// (see apps/api/app/permissions.py), i.e. the canManage pair — reviewers get
// read-only access here.
export default async function ReconPage() {
  const session = await auth();
  const manage = canManage(session?.user?.role);
  return <ReconView canManage={manage} />;
}
