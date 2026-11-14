import { auth } from "@/auth";
import { getActiveProject } from "@/lib/project";
import { canManage } from "@/lib/roles";
import { cookieHeader } from "../_data";
import { KnowledgeManager } from "./knowledge-manager";

export default async function KnowledgePage() {
  const session = await auth();
  const { id } = await getActiveProject(await cookieHeader());
  return <KnowledgeManager key={id} projectId={id} canManage={canManage(session?.user?.role)} />;
}
