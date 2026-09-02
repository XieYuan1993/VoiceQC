import { auth } from "@/auth";
import { getActiveProject } from "@/lib/project";
import { canManage } from "@/lib/roles";

import { cookieHeader } from "../../_data";

import { BatchDetail } from "./batch-detail";

export default async function BatchDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const session = await auth();
  const { id: projectId } = await getActiveProject(await cookieHeader());
  return (
    <BatchDetail
      batchId={id}
      projectId={projectId}
      canManage={canManage(session?.user?.role)}
    />
  );
}
