import { AudioWaveform } from "lucide-react";
import { redirect } from "next/navigation";

import { auth } from "@/auth";
import { NavLinks } from "@/components/nav-links";
import { SignOutButton } from "@/components/nav";
import { ProjectSwitcher } from "@/components/project-switcher";
import { ThemeToggle } from "@/components/theme-toggle";
import { Badge } from "@/components/ui/badge";
import { getActiveProject } from "@/lib/project";

import { cookieHeader } from "./_data";

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const session = await auth();
  if (!session?.user) redirect("/login");

  const { project, projects, id, modules } = await getActiveProject(await cookieHeader());
  const branding = project?.branding ?? {};
  const appName =
    typeof branding["app_name"] === "string" ? branding["app_name"] : "VoiceQA";
  const isDemo = branding["demo_mode"] === true;
  const industry = typeof branding["industry"] === "string" ? branding["industry"] : undefined;

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b bg-background/80 px-6 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <span className="flex items-center gap-2 text-sm font-semibold">
          <span
            aria-hidden
            className="inline-flex h-[26px] w-[26px] items-center justify-center rounded-md bg-primary text-primary-foreground"
          >
            <AudioWaveform className="h-4 w-4" />
          </span>
          <span>{appName}</span>
        </span>

        {isDemo && <Badge variant="info">Demo data</Badge>}

        <ProjectSwitcher projects={projects} activeId={id} />

        <div className="ml-auto flex items-center gap-3">
          <ThemeToggle />
          <span className="hidden text-sm text-muted-foreground sm:inline">
            {session.user.email}
          </span>
          <SignOutButton />
        </div>
      </header>
      <div className="flex flex-1">
        <aside className="w-56 shrink-0 border-r px-3 py-4">
          <NavLinks modules={modules} industry={industry} projectId={id} key={project?.id ?? "none"} />
        </aside>
        <main className="flex-1 p-6">{children}</main>
      </div>
    </div>
  );
}
