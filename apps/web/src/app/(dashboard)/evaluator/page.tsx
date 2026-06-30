import { auth } from "@/auth";
import { getActiveProject } from "@/lib/project";
import { canManage } from "@/lib/roles";

import { cookieHeader } from "../_data";
import { EvaluatorTabs } from "./evaluator-tabs";

export default async function EvaluatorPage() {
  const session = await auth();
  const manage = canManage(session?.user?.role);

  const { id: projectId, project } = await getActiveProject(await cookieHeader());

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Evaluator</h1>
        <p className="text-sm text-muted-foreground">
          The rubric, extraction fields and industry terms for{" "}
          <span className="font-medium text-foreground">{project?.name ?? "this project"}</span>.
          Generate a starting rubric from a plain-language description.
          {!manage && " Your role has read-only access."}
        </p>
      </div>

      <EvaluatorTabs projectId={projectId} canManage={manage} />
    </div>
  );
}
