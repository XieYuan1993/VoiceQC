import { getActiveProject } from "@/lib/project";
import { cookieHeader } from "../_data";
import { RiskInbox } from "./risk-inbox";
export default async function RiskPage() {
  const { id } = await getActiveProject(await cookieHeader());
  return <RiskInbox key={id} projectId={id} />;
}
