import { auth } from "@/auth";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { isAdmin } from "@/lib/roles";

import { AdminTabs } from "./admin-tabs";

export default async function AdminPage() {
  const session = await auth();
  const admin = isAdmin(session?.user?.role);

  if (!admin) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-semibold">Admin</h1>
          <p className="text-sm text-muted-foreground">
            User management, single sign-on, audit log and usage.
          </p>
        </div>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Not authorized</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            This area is restricted to administrators. Ask an admin if you need
            access to user management or SSO settings.
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Admin</h1>
        <p className="text-sm text-muted-foreground">
          Users and roles, Microsoft Entra single sign-on, the audit log, and
          model-usage / data-retention controls.
        </p>
      </div>
      <AdminTabs />
    </div>
  );
}
