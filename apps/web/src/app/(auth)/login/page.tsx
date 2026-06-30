"use client";

import { useRouter } from "next/navigation";
import { signIn } from "next-auth/react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:7870";

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = React.useState<string | null>(null);
  const [pending, setPending] = React.useState(false);
  // Phase 0: /api/auth/sso-status always reports enabled:false, so the
  // Microsoft button stays hidden. Phase 4 flips it once Entra is configured.
  const [ssoEnabled, setSsoEnabled] = React.useState(false);

  React.useEffect(() => {
    let cancelled = false;
    fetch(`${API_URL}/api/auth/sso-status`)
      .then((res) => (res.ok ? res.json() : { enabled: false }))
      .then((data: { enabled?: boolean }) => {
        if (!cancelled) setSsoEnabled(!!data?.enabled);
      })
      .catch(() => {
        // API down → no SSO button; the password form still works.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setError(null);
    setPending(true);
    const res = await signIn("credentials", {
      redirect: false,
      email: String(form.get("email") ?? "").trim(),
      password: String(form.get("password") ?? ""),
    });
    setPending(false);
    if (!res || res.error) {
      setError("Invalid email or password");
      return;
    }
    router.push("/dashboard");
    router.refresh();
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>VoiceQA</CardTitle>
        <CardDescription>
          Call quality &amp; compliance. Sign in with your work email.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        <form onSubmit={onSubmit} className="space-y-3">
          <Input
            name="email"
            type="email"
            placeholder="you@company.com"
            autoComplete="email"
            required
          />
          <Input
            name="password"
            type="password"
            placeholder="Password"
            autoComplete="current-password"
            required
          />
          {error ? (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          ) : null}
          <Button type="submit" className="w-full" disabled={pending}>
            {pending ? "Signing in…" : "Sign in"}
          </Button>
        </form>

        {ssoEnabled ? (
          <>
            <div className="relative my-2">
              <div className="absolute inset-0 flex items-center">
                <span className="w-full border-t" />
              </div>
              <div className="relative flex justify-center text-xs uppercase">
                <span className="bg-card px-2 text-muted-foreground">or</span>
              </div>
            </div>
            <Button
              type="button"
              variant="outline"
              className="w-full"
              onClick={() => signIn("microsoft-entra-id")}
            >
              Sign in with Microsoft
            </Button>
          </>
        ) : null}
      </CardContent>
    </Card>
  );
}
