import { ArrowRight, ListChecks } from "lucide-react";
import Link from "next/link";

import { auth } from "@/auth";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getActiveProject } from "@/lib/project";
import { canManage } from "@/lib/roles";

import { cookieHeader } from "../_data";
import { AppSettingsSection } from "./app-settings-section";

export default async function SettingsPage() {
  const session = await auth();
  const manage = canManage(session?.user?.role);

  const { id: projectId, project } = await getActiveProject(await cookieHeader());

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Settings</h1>
        <p className="text-sm text-muted-foreground">
          App configuration. The evaluation rubric, extraction fields and industry terms now live
          on the Evaluator.
          {!manage && " Your role has read-only access."}
        </p>
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <CardTitle className="flex items-center gap-2 text-base">
                <ListChecks className="h-4 w-4 text-primary" aria-hidden />
                Evaluator
              </CardTitle>
              <CardDescription>
                Criteria, extraction fields and terms for{" "}
                <span className="font-medium text-foreground">{project?.name ?? "this project"}</span>{" "}
                — plus AI-assisted criteria generation.
              </CardDescription>
            </div>
            <Link
              href="/evaluator"
              className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-md bg-secondary px-3 text-sm font-medium text-secondary-foreground transition-colors hover:bg-secondary/80"
            >
              Open Evaluator
              <ArrowRight className="h-4 w-4" aria-hidden />
            </Link>
          </div>
        </CardHeader>
      </Card>

      <AppSettingsSection canManage={manage} projectId={projectId} />
    </div>
  );
}
