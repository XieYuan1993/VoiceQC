import { auth } from "@/auth";
import { canManage } from "@/lib/roles";

import { BatchDetail } from "./batch-detail";

export default async function BatchDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const session = await auth();
  return <BatchDetail batchId={id} canManage={canManage(session?.user?.role)} />;
}
