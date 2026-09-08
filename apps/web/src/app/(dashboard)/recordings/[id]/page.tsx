import { auth } from "@/auth";
import { getActiveProject } from "@/lib/project";
import { canManage, canReview } from "@/lib/roles";

import { cookieHeader } from "../../_data";
import { RecordingDetailView } from "./recording-detail";

export default async function RecordingDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const { id: projectId } = await getActiveProject(await cookieHeader());
  const session = await auth();
  const role = session?.user?.role;
  return (
    <RecordingDetailView
      recordingId={id}
      projectId={projectId}
      canManage={canManage(role)}
      canReview={canReview(role)}
    />
  );
}
