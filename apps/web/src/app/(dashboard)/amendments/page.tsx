import { getActiveProject } from "@/lib/project";
import { cookieHeader } from "../_data";
import { AmendmentTable } from "./table";

export default async function AmendmentsPage() {
  const { id } = await getActiveProject(await cookieHeader());
  return <AmendmentTable key={id} projectId={id} />;
}
