import { auth } from "@/auth";
import { canManage } from "@/lib/roles";
import { getActiveProject } from "@/lib/project";

import { cookieHeader } from "../_data";
import { ReconView } from "./recon-view";

// recon:run and recon:review are granted to admin + compliance_manager only
// (see apps/api/app/permissions.py), i.e. the canManage pair — reviewers get
// read-only access here.
export default async function ReconPage() {
  const session = await auth();
  const manage = canManage(session?.user?.role);
  const { id: projectId } = await getActiveProject(await cookieHeader());
  return <ReconView canManage={manage} projectId={projectId} />;
}
