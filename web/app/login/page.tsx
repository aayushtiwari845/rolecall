"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { ButtonLink, Button, Input, Wordmark } from "@/components/ui";
import { api } from "@/lib/api";
import { num } from "@/lib/format";
import { useStats } from "@/lib/hooks";

const ERRORS: Record<string, string> = {
  oauth: "Google sign-in didn't complete. Please try again.",
  unverified: "That Google account's email isn't verified yet.",
};

function GoogleMark() {
  return (
    <svg viewBox="0 0 24 24" className="size-5" aria-hidden>
      <path fill="#4285F4" d="M22.6 12.3c0-.8-.1-1.5-.2-2.3H12v4.3h6a5.1 5.1 0 0 1-2.2 3.4v2.8h3.6c2-1.9 3.2-4.7 3.2-8.2z" />
      <path fill="#34A853" d="M12 23c3 0 5.5-1 7.3-2.7l-3.6-2.8c-1 .7-2.2 1.1-3.7 1.1-2.9 0-5.3-1.9-6.2-4.5H2.1v2.9A11 11 0 0 0 12 23z" />
      <path fill="#FBBC05" d="M5.8 14.1a6.6 6.6 0 0 1 0-4.2V7H2.1a11 11 0 0 0 0 9.9l3.7-2.8z" />
      <path fill="#EA4335" d="M12 5.4c1.6 0 3.1.6 4.2 1.7l3.2-3.2A11 11 0 0 0 2.1 7l3.7 2.9C6.7 7.3 9.1 5.4 12 5.4z" />
    </svg>
  );
}

function LoginInner() {
  const params = useSearchParams();
  const next = params.get("next") || "/feed";
  const error = params.get("error");
  const router = useRouter();
  const qc = useQueryClient();
  const { data: stats } = useStats();
  const { data: cfg } = useQuery({
    queryKey: ["auth-config"],
    queryFn: () => api.get<{ google: boolean; dev_login: boolean }>("/auth/config"),
  });
  const [email, setEmail] = useState("dev@rolecall.local");
  const [busy, setBusy] = useState(false);

  async function devLogin() {
    setBusy(true);
    try {
      const res = await api.post<{ onboarded: boolean }>("/auth/dev-login", { email, name: email.split("@")[0] });
      await qc.invalidateQueries({ queryKey: ["me"] });
      router.replace(res.onboarded ? next : "/onboarding");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-dvh lg:grid-cols-[1.1fr_1fr]">
      <section className="board relative hidden flex-col justify-between p-12 lg:flex">
        <Wordmark className="text-chalk" />
        <div>
          <p className="score text-[9rem] font-extrabold text-chalk">{stats ? num(stats.new_today) : "–"}</p>
          <p className="label mt-3 text-chalk-2">new tech roles in the last 24 hours</p>
        </div>
        <p className="max-w-[44ch] text-chalk-2">
          Sign in, upload a resume and your scorecard is ready: every role ranked for you, with the reasons on the row.
        </p>
      </section>
      <section className="flex flex-col justify-center px-6 py-16 sm:px-16">
        <div className="mx-auto w-full max-w-sm">
          <Wordmark className="mb-12 lg:hidden" />
          <h1 className="score text-[3rem] font-extrabold uppercase">Sign in</h1>
          <p className="mt-3 text-ink-2">We only use your Google account to know it’s you. No posting, no spam.</p>
          {error && (
            <p role="alert" className="mt-6 rounded-md border border-red/40 bg-red/10 px-3 py-2 text-sm text-red">
              {ERRORS[error] ?? "Sign-in failed. Please try again."}
            </p>
          )}
          <div className="mt-8 grid gap-3">
            {cfg?.google !== false && (
              <ButtonLink
                href={`/api/auth/google/login?next=${encodeURIComponent(next)}`}
                variant="outline"
                size="lg"
                className="bg-panel font-semibold"
              >
                <GoogleMark /> Continue with Google
              </ButtonLink>
            )}
            {cfg?.google === false && !cfg.dev_login && (
              <p className="text-sm text-ink-2">Google sign-in isn’t configured on this server yet.</p>
            )}
            {cfg?.dev_login && (
              <form
                className="mt-6 grid gap-3 border-t border-rule pt-6"
                onSubmit={(e) => {
                  e.preventDefault();
                  devLogin();
                }}
              >
                <p className="label text-ink-3">Local development sign-in</p>
                <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} aria-label="Email" required />
                <Button type="submit" variant="primary" disabled={busy}>
                  Sign in as this user
                </Button>
              </form>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginInner />
    </Suspense>
  );
}
