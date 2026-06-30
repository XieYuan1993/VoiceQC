import { auth } from "@/auth";
import { canManage, canReview } from "@/lib/roles";

import { RecordingDetailView } from "./recording-detail";

export default async function RecordingDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const session = await auth();
  const role = session?.user?.role;
  return (
    <RecordingDetailView recordingId={id} canManage={canManage(role)} canReview={canReview(role)} />
  );
}
