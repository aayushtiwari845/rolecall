"use client";

import clsx from "clsx";
import { BarChart3, ClipboardList, LogOut, MessageSquare, Moon, Search, Settings, Sun, Trophy } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { num } from "@/lib/format";
import { useMe, useSignOut, useStats, useTheme } from "@/lib/hooks";
import { Spinner, Wordmark } from "./ui";

const NAV = [
  { href: "/feed", label: "Scorecard", icon: Trophy },
  { href: "/search", label: "Search", icon: Search },
  { href: "/tracker", label: "Tracker", icon: ClipboardList },
  { href: "/chat", label: "Assistant", icon: MessageSquare },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function ThemeToggle({ className }: { className?: string }) {
  const [theme, setTheme] = useTheme();
  return (
    <button
      onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
      aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
      className={clsx("grid size-9 place-items-center rounded-md hover:bg-panel-2", className)}
    >
      {theme === "dark" ? <Sun className="size-[18px]" /> : <Moon className="size-[18px]" />}
    </button>
  );
}

function LiveCount() {
  const { data } = useStats();
  if (!data) return null;
  return (
    <span className="hidden items-center gap-2 text-sm text-ink-2 lg:inline-flex" title="New roles found in the last 24 hours">
      <span className="live-dot size-2 rounded-full bg-green" aria-hidden />
      <span className="score text-xl font-bold text-ink">{num(data.new_today)}</span> new today
    </span>
  );
}

export function AppShell({ children, wide }: { children: React.ReactNode; wide?: boolean }) {
  const { data: me, isLoading } = useMe();
  const pathname = usePathname();
  const router = useRouter();
  const signOut = useSignOut();

  useEffect(() => {
    if (isLoading) return;
    if (me === null) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    else if (me && !me.onboarded && pathname !== "/onboarding") router.replace("/onboarding");
  }, [me, isLoading, pathname, router]);

  if (isLoading || !me) {
    return (
      <div className="grid min-h-dvh place-items-center text-ink-2">
        <Spinner className="size-6" />
      </div>
    );
  }

  const nav = me.is_admin ? [...NAV, { href: "/admin", label: "Admin", icon: BarChart3 }] : NAV;

  return (
    <div className="min-h-dvh pb-20 md:pb-0">
      <header className="sticky top-0 z-40 border-b border-rule bg-bg/90 backdrop-blur-md">
        <div className="mx-auto flex h-14 max-w-[1240px] items-center gap-6 px-4 md:px-6">
          <Wordmark href="/feed" />
          <nav aria-label="Main" className="hidden items-center gap-1 md:flex">
            {nav.map((n) => {
              const active = pathname.startsWith(n.href);
              return (
                <Link
                  key={n.href}
                  href={n.href}
                  aria-current={active ? "page" : undefined}
                  className={clsx(
                    "relative px-3 py-2 text-sm transition-colors",
                    active ? "font-semibold text-ink" : "text-ink-2 hover:text-ink",
                  )}
                >
                  {n.label}
                  {active && <span className="absolute inset-x-3 -bottom-[11px] h-[3px] bg-amber" aria-hidden />}
                </Link>
              );
            })}
          </nav>
          <div className="ml-auto flex items-center gap-3">
            <LiveCount />
            <ThemeToggle />
            <button
              onClick={signOut}
              className="hidden size-9 place-items-center rounded-md text-ink-2 hover:bg-panel-2 hover:text-ink md:grid"
              aria-label="Sign out"
              title="Sign out"
            >
              <LogOut className="size-[18px]" />
            </button>
            {me.avatar_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={me.avatar_url} alt="" className="size-8 rounded-full border border-rule" referrerPolicy="no-referrer" />
            ) : (
              <span className="grid size-8 place-items-center rounded-full bg-panel-2 text-sm font-semibold">
                {(me.name ?? me.email)[0]?.toUpperCase()}
              </span>
            )}
          </div>
        </div>
      </header>

      <main className={clsx("mx-auto px-4 pt-6 md:px-6 md:pt-10", wide ? "max-w-[1400px]" : "max-w-[1240px]")}>{children}</main>

      <nav
        aria-label="Main"
        className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-5 border-t border-rule bg-bg/95 pb-[env(safe-area-inset-bottom)] backdrop-blur-md md:hidden"
      >
        {NAV.map((n) => {
          const active = pathname.startsWith(n.href);
          const Icon = n.icon;
          return (
            <Link
              key={n.href}
              href={n.href}
              aria-current={active ? "page" : undefined}
              className={clsx("flex flex-col items-center gap-1 py-2.5 text-[0.6875rem]", active ? "text-ink" : "text-ink-3")}
            >
              <Icon className={clsx("size-5", active && "text-amber-text")} />
              {n.label}
            </Link>
          );
        })}
      </nav>
    </div>
  );
}

export function PageHead({ title, sub, children }: { title: string; sub?: React.ReactNode; children?: React.ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4 md:mb-8">
      <div>
        <h1 className="score text-[2.75rem] font-extrabold uppercase md:text-[3.5rem]">{title}</h1>
        {sub && <p className="mt-2 max-w-2xl text-sm text-ink-2 md:text-base">{sub}</p>}
      </div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </div>
  );
}
